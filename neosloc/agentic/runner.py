"""The probe role: let a model attempt the integration tasks and measure it.

Integrability measured directly: give a model only what an outside integrator
gets, ask it to do the standard tasks, check its answers against the
implementation (and optionally have a judge model confirm they would work),
and record success, turns, tool calls, tokens and cost.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional

from ..repo import Repo
from .grader import Grader
from .llm import Budget
from .loop import run_loop
from .tasks import Task
from .workspace import SUBMIT_TOOL, Workspace

DEFAULT_MODEL = "anthropic:claude-opus-5-5"
DEFAULT_EFFORT = "medium"

SYSTEM = """You are a software engineer on another team. You have been asked to integrate \
your own program with the software in this repository, and you must work out how from \
what you can read. {scope}

For each task: investigate with the tools, then call submit_result once with a concrete \
answer. Name exact HTTP methods and paths, exact commands and flags, exact environment \
variable or setting names, and exact importable symbols. Your answer is checked against \
the real implementation, so report only what the material supports; if the software \
offers no way to do the task, submit feasible=false rather than inventing one."""


def level_from_rate(rate: float) -> int:
    if rate >= 0.85:
        return 4
    if rate >= 0.65:
        return 3
    if rate >= 0.4:
        return 2
    return 1 if rate > 0 else 0


class Probe:
    def __init__(self, repo: Repo, backend: Any, budget: Optional[Budget] = None, max_turns: int = 25,
                 route_files: Optional[List[str]] = None, base_url: Optional[str] = None,
                 allow_writes: bool = False, auth_headers: Optional[Dict[str, str]] = None,
                 judge: Any = None, transcripts: Optional[str] = None,
                 log: Optional[Callable[[str], None]] = None):
        self.repo, self.backend = repo, backend
        self.budget = budget or Budget(5.0)
        self.max_turns = max_turns
        self.base_url, self.allow_writes = base_url, allow_writes
        self.auth_headers = auth_headers or {}
        self.judge = judge
        self.transcripts = transcripts
        self.grader = Grader(repo, route_files)
        self.log = log or (lambda s: print(s, file=sys.stderr))

    def run_task(self, task: Task, scope: str) -> Dict:
        ws = Workspace(self.repo, scope, self.base_url, self.allow_writes, self.auth_headers)
        system = SYSTEM.format(scope=ws.describe())
        conv = self.backend.conversation(system, ws.tools())
        started = time.time()
        res = run_loop(conv, "Task: " + task.prompt, ws.run, SUBMIT_TOOL, self.budget, self.max_turns)
        rec = {"task": task.key, "dimension": task.dimension, "scope": scope, "model": self.backend.label,
               "turns": res.turns, "tool_calls": res.tool_calls, "tool_errors": res.tool_errors,
               "answer": res.answer, "outcome": res.outcome, "success": False, "problems": []}
        if res.error:
            rec["problems"].append(res.error)
        ans = res.answer
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
                if rec["success"] and self.judge is not None:
                    verdict = self.judge.judge(task, ans)
                    rec["judge"] = verdict
                    if verdict.get("works") is False:
                        rec["success"], rec["outcome"] = False, "judged_wrong"
                        rec["problems"].append("judge: " + verdict.get("reason", ""))
        rec.update(res.usage)
        rec["cost_usd"] = res.cost_usd
        rec["seconds"] = round(time.time() - started, 1)
        rec["http_calls"] = len(ws.http_log)
        if self.transcripts:
            self._save("%s-%s-%s" % (_slug(self.backend.label), scope, task.key), system, conv.dump(), rec)
        return rec

    def _save(self, name: str, system: str, messages: List[Dict], rec: Dict) -> None:
        os.makedirs(self.transcripts, exist_ok=True)
        with open(os.path.join(self.transcripts, name + ".json"), "w") as fh:
            json.dump({"system": system, "messages": messages, "result": rec}, fh, indent=2, default=str)

    def run(self, tasks: List[Task], scopes: List[str]) -> Dict:
        records = []
        for scope in scopes:
            for task in tasks:
                if self.budget.exhausted:
                    self.log("neosloc: budget of $%.2f reached; skipping %s/%s"
                             % (self.budget.max_usd, scope, task.key))
                    records.append(_skipped(task, scope, self.backend.label))
                    continue
                self.log("neosloc: probe %s %s/%s ..." % (self.backend.label, scope, task.key))
                rec = self.run_task(task, scope)
                self.log("neosloc:   %s (%d turns, $%.2f spent so far)"
                         % (rec["outcome"], rec["turns"], self.budget.spent))
                records.append(rec)
        return summarize(records, self.backend.label, getattr(self.backend, "effort", None), scopes,
                         judge=self.judge.backend.label if self.judge else None)


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-." else "_" for c in s)


def _skipped(task: Task, scope: str, model: str) -> Dict:
    return {"task": task.key, "dimension": task.dimension, "scope": scope, "model": model,
            "outcome": "budget", "success": False, "turns": 0, "tool_calls": 0, "tool_errors": 0,
            "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0, "cost_usd": 0.0, "problems": ["budget exhausted"]}


def summarize(records: List[Dict], model: str, effort: Optional[str], scopes: List[str],
              judge: Optional[str] = None) -> Dict:
    summary = {}
    for scope in scopes:
        rs = [r for r in records if r["scope"] == scope and r["outcome"] != "budget"]
        ok = [r for r in rs if r["success"]]
        tokens = sum(r["input_tokens"] + r["output_tokens"] + r["cache_read_input_tokens"]
                     + r["cache_creation_input_tokens"] for r in rs)
        rate = len(ok) / float(len(rs)) if rs else 0.0
        costs = [r.get("cost_usd") for r in rs]
        summary[scope] = {
            "tasks": len(rs), "succeeded": len(ok), "success_rate": round(rate, 2),
            "level": level_from_rate(rate), "tokens": tokens,
            "tokens_per_success": (tokens // len(ok)) if ok else None,
            "cost_usd": None if any(c is None for c in costs) else round(sum(costs), 2),
            "by_dimension": {r["dimension"]: r["success"] for r in rs},
        }
    out = {"model": model, "effort": effort, "judge": judge, "scopes": scopes,
           "summary": summary, "tasks": records}
    if "docs" in summary and "source" in summary and summary["docs"]["tasks"] and summary["source"]["tasks"]:
        out["documentation_gap"] = round(summary["source"]["success_rate"] - summary["docs"]["success_rate"], 2)
    return out


def panel(runs: List[Dict]) -> Optional[Dict]:
    """Agreement across probe models on each (scope, task)."""
    if len(runs) < 2:
        return None
    cells: Dict[str, List[bool]] = {}
    for run in runs:
        for t in run["tasks"]:
            if t["outcome"] != "budget":
                cells.setdefault("%s/%s" % (t["scope"], t["task"]), []).append(t["success"])
    unanimous = sum(1 for v in cells.values() if len(set(v)) == 1)
    return {
        "models": [r["model"] for r in runs],
        "success_share": {k: round(sum(v) / float(len(v)), 2) for k, v in cells.items()},
        "agreement": round(unanimous / float(len(cells)), 2) if cells else None,
    }
