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
from typing import Any, Callable, Dict, List, Optional

from ..model import LEVEL_NAMES, DimensionResult
from ..log import logger
from ..repo import Repo
from .llm import Budget
from .loop import run_loop
from .workspace import Workspace

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
You can read the whole repository. You are given one dimension at a time: its question, and for \
each surface of the project (service, cli, library, frontend) a ladder of requirements. A surface \
reaches level N only when it meets every requirement of levels 1 to N; the dimension's level is \
the best surface's level. For each requirement you see whether the detector found it met, with \
its evidence or the reason it failed.

Check the detector's verdicts against the code: is each "met" real, and is each "not met" truly \
missing? Then call submit_review with the level the ladders give when applied correctly, and list \
wrong verdicts (false_positives: requirements marked met that aren't; missed_evidence: paths \
showing requirements marked unmet that are met)."""


class Reviewer:
    def __init__(self, repo: Repo, backend: Any, budget: Budget, max_turns: int = 15):
        self.repo, self.backend, self.budget, self.max_turns = repo, backend, budget, max_turns

    def review(self, dim: DimensionResult) -> Dict:
        ws = Workspace(self.repo, "source")
        tools = [t for t in ws.tools() if t["name"] != "submit_result"] + [REVIEW_TOOL]
        conv = self.backend.conversation(SYSTEM, tools)
        prompt = json.dumps({
            "dimension": dim.title,
            "question": dim.question,
            "levels": LEVEL_NAMES,
            "detector_level": dim.level,
            "best_surface": dim.best_surface,
            "surfaces": {name: {"level": res["level"], "requirements": [
                {"level": r["level"], "requirement": r["text"], "met": r["met"],
                 "evidence": [e["path"] or e["detail"] for e in r["evidence"]][:3],
                 "reason_not_met": r["note"] or None} for r in res["requirements"]]}
                for name, res in dim.surfaces.items()},
        }, indent=2)
        res = run_loop(conv, prompt, ws.run, REVIEW_TOOL, self.budget, self.max_turns)
        out = dict(res.answer) if res.answer else {"level": None, "rationale": "no review (%s)" % res.outcome,
                                                   "false_positives": [], "missed_evidence": []}
        out.update({"model": self.backend.label, "turns": res.turns, "cost_usd": res.cost_usd})
        return out


def review_all(repo: Repo, dims: List[DimensionResult], backends: List[Any], budget: Budget,
               log: Optional[Callable[[str], None]] = None) -> Dict:
    warn = log or logger.warning
    log = log or logger.info
    per_dim: Dict[str, Dict] = {}
    for dim in dims:
        if dim.level is None:
            continue  # not applicable: nothing to audit
        reviews = []
        for b in backends:
            if budget.exhausted:
                warn("budget reached; skipping review of %s by %s" % (dim.key, b.label))
                continue
            log("review %s by %s ..." % (dim.key, b.label))
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
