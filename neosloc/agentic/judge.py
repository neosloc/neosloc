"""The judge role: would a grounded answer actually accomplish the task?

Grounding proves that what the probe named exists. The judge, which may be a
different model and provider, reads the full source and decides whether the
steps would work as described (right method, required fields, correct order,
auth). A probe answer only counts as a success when both agree.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from ..repo import Repo
from .llm import Budget
from .loop import run_loop
from .tasks import Task
from .workspace import Workspace

VERDICT_TOOL = {
    "name": "submit_verdict",
    "description": "Submit your verdict on the proposed integration once you have checked it against the code.",
    "strict": True,
    "input_schema": {
        "type": "object", "additionalProperties": False,
        "required": ["works", "reason", "issues"],
        "properties": {
            "works": {"type": "boolean",
                      "description": "True if following the steps as written would accomplish the task."},
            "reason": {"type": "string"},
            "issues": {"type": "array", "items": {"type": "string"},
                       "description": "Concrete problems: wrong paths, missing fields, missing auth, wrong order."},
        },
    },
}

SYSTEM = """You review integration instructions written by another engineer for the software \
in this repository. You can read the whole repository, implementation included.

Check the proposed steps against the code: do the routes, commands, settings and symbols \
behave the way the steps assume, are required inputs and authentication covered, and would \
following the steps in order accomplish the task? Minor omissions a competent engineer \
would fill in without reading the code don't make an answer wrong. Then call submit_verdict."""


class Judge:
    def __init__(self, repo: Repo, backend: Any, budget: Budget, max_turns: int = 20):
        self.repo, self.backend, self.budget, self.max_turns = repo, backend, budget, max_turns

    def judge(self, task: Task, answer: Dict) -> Dict:
        ws = Workspace(self.repo, "source")
        tools = [t for t in ws.tools() if t["name"] != "submit_result"] + [VERDICT_TOOL]
        conv = self.backend.conversation(SYSTEM, tools)
        prompt = "Task given to the engineer:\n%s\n\nTheir answer:\n%s" % (
            task.prompt, json.dumps(answer, indent=2, sort_keys=True))
        res = run_loop(conv, prompt, ws.run, VERDICT_TOOL, self.budget, self.max_turns)
        verdict = dict(res.answer) if res.answer else {"works": None, "reason": "judge did not decide (%s)"
                                                                         % res.outcome, "issues": []}
        verdict.update({"model": self.backend.label, "turns": res.turns, "cost_usd": res.cost_usd})
        return verdict
