"""The agentic probe: let a model attempt the integration tasks and measure it.

Integrability measured directly: give a capable model only what an outside
integrator gets, ask it to do the standard tasks, check its answers against
the implementation, and record success, turns, tool calls and tokens.

Uses the official `anthropic` SDK (optional extra: pip install 'neosloc[agentic]',
Python >= 3.10). The client is injected so tests run without it.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional

from ..repo import Repo
from .grader import Grader
from .tasks import Task
from .workspace import ToolError, Workspace

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per million tokens: (input, output, cache read). Cache writes bill at 1.25x input.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
}

SYSTEM = """You are a software engineer on another team. You have been asked to integrate \
your own program with the software in this repository, and you must work out how from \
what you can read. {scope}

For each task: investigate with the tools, then call submit_result once with a concrete \
answer. Name exact HTTP methods and paths, exact commands and flags, exact environment \
variable or setting names, and exact importable symbols. Your answer is checked against \
the real implementation, so report only what the material supports; if the software \
offers no way to do the task, submit feasible=false rather than inventing one."""


def make_client():
    try:
        import anthropic
    except ImportError:
        raise SystemExit("neosloc: agentic mode needs the anthropic SDK (Python >= 3.10):\n"
                         "  pip install 'neosloc[agentic]'   or   uv run --with anthropic python -m neosloc ...")
    return anthropic.Anthropic()


def _block_dict(b: Any) -> Dict:
    if isinstance(b, dict):
        return b
    if hasattr(b, "model_dump"):
        return b.model_dump(mode="json", exclude_none=True)
    return dict(vars(b))


def _usage(resp: Any) -> Dict[str, int]:
    u = getattr(resp, "usage", None)
    get = (lambda k: int(getattr(u, k, 0) or 0)) if u is not None else (lambda k: 0)
    return {k: get(k) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                "cache_creation_input_tokens")}


def cost_usd(model: str, usage: Dict[str, int]) -> Optional[float]:
    price = PRICES.get(model)
    if price is None:
        return None
    pin, pout, pread = price
    return (usage["input_tokens"] * pin + usage["cache_creation_input_tokens"] * pin * 1.25
            + usage["cache_read_input_tokens"] * pread + usage["output_tokens"] * pout) / 1e6


def level_from_rate(rate: float) -> int:
    if rate >= 0.85:
        return 4
    if rate >= 0.65:
        return 3
    if rate >= 0.4:
        return 2
    return 1 if rate > 0 else 0


class Probe:
    def __init__(self, repo: Repo, client: Any, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT,
                 max_turns: int = 25, max_cost: float = 5.0, route_files: Optional[List[str]] = None,
                 base_url: Optional[str] = None, allow_writes: bool = False,
                 auth_headers: Optional[Dict[str, str]] = None, fallbacks: bool = True,
                 transcripts: Optional[str] = None, log: Callable[[str], None] = None):
        self.repo, self.client, self.model, self.effort = repo, client, model, effort
        self.max_turns, self.max_cost = max_turns, max_cost
        self.base_url, self.allow_writes = base_url, allow_writes
        self.auth_headers = auth_headers or {}
        self.fallbacks = fallbacks
        self.transcripts = transcripts
        self.grader = Grader(repo, route_files)
        self.spent = 0.0
        self.log = log or (lambda s: print(s, file=sys.stderr))

    def _create(self, system: str, tools: List[dict], messages: List[dict]):
        kwargs = dict(model=self.model, max_tokens=MAX_TOKENS, tools=tools, messages=messages,
                      system=[{"type": "text", "text": system}],
                      output_config={"effort": self.effort},
                      cache_control={"type": "ephemeral"})
        if self.fallbacks:
            return self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        return self.client.messages.create(**kwargs)

    def run_task(self, task: Task, scope: str) -> Dict:
        ws = Workspace(self.repo, scope, self.base_url, self.allow_writes, self.auth_headers)
        system = SYSTEM.format(scope=ws.describe())
        tools = ws.tools()
        messages: List[Dict] = [{"role": "user", "content": "Task: " + task.prompt}]
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                 "cache_creation_input_tokens": 0}
        rec = {"task": task.key, "dimension": task.dimension, "scope": scope, "turns": 0,
               "tool_calls": 0, "tool_errors": 0, "answer": None, "outcome": "turn_limit",
               "success": False, "problems": []}
        started = time.time()
        nudged = False
        try:
            while rec["turns"] < self.max_turns:
                if self.spent >= self.max_cost:
                    rec["outcome"] = "budget"
                    break
                resp = self._create(system, tools, messages)
                rec["turns"] += 1
                u = _usage(resp)
                for k in usage:
                    usage[k] += u[k]
                self.spent += cost_usd(self.model, u) or 0.0
                if resp.stop_reason == "refusal":
                    rec["outcome"] = "refusal"
                    break
                messages.append({"role": "assistant", "content": resp.content})
                calls = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
                submit = next((c for c in calls if c.name == "submit_result"), None)
                if submit is not None:
                    rec["answer"] = submit.input
                    rec["tool_calls"] += 1
                    break
                if not calls:
                    if resp.stop_reason == "max_tokens" or not nudged:
                        nudged = True
                        messages.append({"role": "user", "content": "Call submit_result with your answer."})
                        continue
                    rec["outcome"] = "no_submit"
                    break
                results = []
                for c in calls:
                    rec["tool_calls"] += 1
                    try:
                        out, err = ws.run(c.name, c.input), False
                    except (ToolError, TypeError) as e:
                        out, err = "Error: %s" % e, True
                        rec["tool_errors"] += 1
                    results.append({"type": "tool_result", "tool_use_id": c.id, "content": out,
                                    **({"is_error": True} if err else {})})
                messages.append({"role": "user", "content": results})
        except Exception as e:  # API failures end the task, not the run
            rec["outcome"] = "error"
            rec["problems"].append("%s: %s" % (type(e).__name__, e))

        ans = rec["answer"]
        if ans is not None:
            if not ans.get("feasible"):
                rec["outcome"] = "infeasible"
                rec["problems"].append("agent reported the task as not possible")
            else:
                g = self.grader.grade(ans, ws.http_log if self.base_url else None)
                rec["grounded_steps"], rec["checked_steps"] = g.grounded, g.checked
                rec["problems"].extend(g.problems)
                if g.checked == 0:
                    rec["outcome"] = "unverifiable"
                    rec["problems"].append("no step could be checked")
                elif g.grounded == g.checked:
                    rec["outcome"], rec["success"] = "solved", True
                else:
                    rec["outcome"] = "ungrounded"
        rec.update(usage)
        rec["cost_usd"] = cost_usd(self.model, usage)
        rec["seconds"] = round(time.time() - started, 1)
        rec["http_calls"] = len(ws.http_log)
        if self.transcripts:
            self._save(task, scope, system, messages, rec)
        return rec

    def _save(self, task: Task, scope: str, system: str, messages: List[Dict], rec: Dict) -> None:
        os.makedirs(self.transcripts, exist_ok=True)
        dump = []
        for m in messages:
            content = m["content"]
            if not isinstance(content, str):
                content = [_block_dict(b) for b in content]
            dump.append({"role": m["role"], "content": content})
        path = os.path.join(self.transcripts, "%s-%s.json" % (scope, task.key))
        with open(path, "w") as fh:
            json.dump({"system": system, "messages": dump, "result": rec}, fh, indent=2, default=str)

    def run(self, tasks: List[Task], scopes: List[str]) -> Dict:
        records = []
        for scope in scopes:
            for task in tasks:
                if self.spent >= self.max_cost:
                    self.log("neosloc: budget of $%.2f reached; skipping %s/%s" % (self.max_cost, scope, task.key))
                    records.append({"task": task.key, "dimension": task.dimension, "scope": scope,
                                    "outcome": "budget", "success": False, "turns": 0, "tool_calls": 0,
                                    "tool_errors": 0, "input_tokens": 0, "output_tokens": 0,
                                    "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                                    "cost_usd": 0.0, "problems": ["budget exhausted"]})
                    continue
                self.log("neosloc: agentic %s/%s ..." % (scope, task.key))
                rec = self.run_task(task, scope)
                self.log("neosloc:   %s (%d turns, $%.2f so far)" % (rec["outcome"], rec["turns"], self.spent))
                records.append(rec)
        return summarize(records, self.model, self.effort, scopes)


def summarize(records: List[Dict], model: str, effort: str, scopes: List[str]) -> Dict:
    summary = {}
    for scope in scopes:
        rs = [r for r in records if r["scope"] == scope and r["outcome"] != "budget"]
        ok = [r for r in rs if r["success"]]
        tokens = sum(r["input_tokens"] + r["output_tokens"] + r["cache_read_input_tokens"]
                     + r["cache_creation_input_tokens"] for r in rs)
        rate = len(ok) / float(len(rs)) if rs else 0.0
        summary[scope] = {
            "tasks": len(rs), "succeeded": len(ok), "success_rate": round(rate, 2),
            "level": level_from_rate(rate), "tokens": tokens,
            "tokens_per_success": (tokens // len(ok)) if ok else None,
            "cost_usd": round(sum(r.get("cost_usd") or 0.0 for r in rs), 2),
            "by_dimension": {r["dimension"]: r["success"] for r in rs},
        }
    out = {"model": model, "effort": effort, "scopes": scopes, "summary": summary, "tasks": records}
    if "docs" in summary and "source" in summary and summary["docs"]["tasks"] and summary["source"]["tasks"]:
        out["documentation_gap"] = round(summary["source"]["success_rate"] - summary["docs"]["success_rate"], 2)
    return out
