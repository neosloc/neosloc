"""The review role: an LLM audits each static dimension level.

The static detectors are regex heuristics. A reviewer model gets one
dimension's rubric, the levels' meaning, the detector's evidence and gaps, and
read access to the whole repository, then returns the level it would assign
and why. Disagreements are where detectors need fixing or recalibrating;
several reviewer models form a panel.
"""
from __future__ import annotations

import json
import statistics
import sys
from typing import Any, Callable, Dict, List, Optional

from ..model import LEVEL_NAMES, DimensionResult
from ..repo import Repo
from .llm import Budget
from .loop import run_loop
from .workspace import Workspace

RUBRIC = {
    "interface": "Is there a machine-readable contract (OpenAPI, GraphQL, protobuf, AsyncAPI, a framework-generated "
                 "spec, or a typed library API) covering the implemented surface, and more than one surface (MCP, CLI "
                 "with JSON output, SDK)?",
    "stability": "Can integrators rely on the surface not changing under them: versioned releases, changelog, API "
                 "versioning, deprecation before removal?",
    "events": "Can other systems learn about changes without polling: outbound (ideally signed, self-service) "
              "webhooks, streams, brokers, CDC, an AsyncAPI/CloudEvents contract?",
    "identity": "Can a machine act with its own narrowly scoped, revocable identity: tokens, OAuth2/OIDC, scopes, "
                "managed API keys or service accounts, SCIM?",
    "portability": "Can all the data get out and in, in bulk, in open formats, with an explicit schema?",
    "ergonomics": "Is the surface forgiving for automated callers: structured (RFC 9457) errors, validation, "
                  "idempotency keys, pagination, rate-limit signals, dry-run, docs for agents?",
    "embeddability": "Can another system run, configure and compose it without a human: container, "
                     "compose/Helm/IaC, documented env config, headless entry point, library packaging?",
    "extensibility": "Can behaviour be added without forking: plugin discovery, hooks, scripting, documented "
                     "extension points?",
    "observability": "Can an operator tell if it is working and why not: health/readiness, metrics, tracing, "
                     "structured logs, error tracking?",
    "legibility": "Can an agent change it safely with limited context: small modules, few import cycles, tests, "
                  "types, CI, lockfiles, agent docs?",
}

REVIEW_TOOL = {
    "name": "submit_review",
    "description": "Submit the level you would assign to this dimension, with reasons.",
    "strict": True,
    "input_schema": {
        "type": "object", "additionalProperties": False,
        "required": ["level", "rationale", "false_positives", "missed_evidence"],
        "properties": {
            "level": {"type": "integer", "enum": [0, 1, 2, 3, 4]},
            "rationale": {"type": "string"},
            "false_positives": {"type": "array", "items": {"type": "string"},
                                "description": "Detector evidence that doesn't show what it claims."},
            "missed_evidence": {"type": "array", "items": {"type": "string"},
                                "description": "Repository paths showing practices the detector missed."},
        },
    },
}

SYSTEM = """You audit an automated integrability assessment of the software in this repository. \
You can read the whole repository. You are given one dimension at a time: its question, the \
meaning of the levels, the level an automated detector assigned, and the evidence it used.

Check the evidence against the code: is each piece real and relevant, and did the detector \
miss practices that are present? Then call submit_review with the level you would assign. \
Judge the software as it is, not the detector's thresholds."""


class Reviewer:
    def __init__(self, repo: Repo, backend: Any, budget: Budget, max_turns: int = 15):
        self.repo, self.backend, self.budget, self.max_turns = repo, backend, budget, max_turns

    def review(self, dim: DimensionResult) -> Dict:
        ws = Workspace(self.repo, "source")
        tools = [t for t in ws.tools() if t["name"] != "submit_result"] + [REVIEW_TOOL]
        conv = self.backend.conversation(SYSTEM, tools)
        prompt = json.dumps({
            "dimension": dim.title,
            "question": RUBRIC.get(dim.key, ""),
            "levels": LEVEL_NAMES,
            "detector_level": dim.level,
            "detector_rationale": dim.rationale,
            "detector_evidence": [{"signal": e.signal, "detail": e.detail, "path": e.path} for e in dim.evidence],
            "detector_gaps": dim.gaps,
        }, indent=2)
        res = run_loop(conv, prompt, ws.run, REVIEW_TOOL, self.budget, self.max_turns)
        out = dict(res.answer) if res.answer else {"level": None, "rationale": "no review (%s)" % res.outcome,
                                                   "false_positives": [], "missed_evidence": []}
        out.update({"model": self.backend.label, "turns": res.turns, "cost_usd": res.cost_usd})
        return out


def review_all(repo: Repo, dims: List[DimensionResult], backends: List[Any], budget: Budget,
               log: Optional[Callable[[str], None]] = None) -> Dict:
    log = log or (lambda s: print(s, file=sys.stderr))
    per_dim: Dict[str, Dict] = {}
    for dim in dims:
        reviews = []
        for b in backends:
            if budget.exhausted:
                log("neosloc: budget reached; skipping review of %s by %s" % (dim.key, b.label))
                continue
            log("neosloc: review %s by %s ..." % (dim.key, b.label))
            reviews.append(Reviewer(repo, b, budget).review(dim))
        levels = [r["level"] for r in reviews if r.get("level") is not None]
        per_dim[dim.key] = {
            "static": dim.level,
            "reviews": reviews,
            "consensus": int(statistics.median_low(levels)) if levels else None,
            "spread": (max(levels) - min(levels)) if levels else None,
        }
    reviewed = [v["consensus"] for v in per_dim.values() if v["consensus"] is not None]
    return {
        "models": [b.label for b in backends],
        "dimensions": per_dim,
        "reviewed_index": round(sum(reviewed) / float(len(reviewed)), 2) if reviewed else None,
        "disagreements": sorted(k for k, v in per_dim.items()
                                if v["consensus"] is not None and v["consensus"] != v["static"]),
    }
