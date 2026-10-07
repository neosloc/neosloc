"""The tool loop shared by every evaluator role.

Run a conversation until the model calls the submit tool with valid input,
gives up, refuses, or runs out of turns or budget. Tool calls other than the
submit tool are executed by `execute(name, args) -> str`, which raises
ToolError for anything the model should be told about.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from ..errors import EvaluatorError
from .llm import AuthFailure, Budget, empty_usage, validate
from .workspace import ToolError


@dataclass
class LoopResult:
    answer: Optional[Dict] = None
    outcome: str = "turn_limit"   # submitted | turn_limit | no_submit | refusal | budget | error
    turns: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    usage: Dict[str, int] = field(default_factory=empty_usage)
    cost_usd: Optional[float] = 0.0
    error: Optional[str] = None


def run_loop(conv: Any, prompt: str, execute: Callable[[str, Dict], str], submit: dict,
             budget: Budget, max_turns: int) -> LoopResult:
    res = LoopResult()
    conv.send_user(prompt)
    nudged = False
    try:
        while res.turns < max_turns:
            if budget.exhausted:
                res.outcome = "budget"
                return res
            turn = conv.next()
            res.turns += 1
            for k in res.usage:
                res.usage[k] += turn.usage.get(k, 0)
            budget.charge(turn.cost)
            res.cost_usd = None if (turn.cost is None or res.cost_usd is None) else res.cost_usd + turn.cost
            if turn.stop == "refusal":
                res.outcome = "refusal"
                return res
            if not turn.calls:
                if turn.stop == "max_tokens" or not nudged:
                    nudged = True
                    conv.send_user("Call %s with your answer." % submit["name"])
                    continue
                res.outcome = "no_submit"
                return res
            results = []
            for call in turn.calls:
                res.tool_calls += 1
                if call.error is None and call.name == submit["name"]:
                    problem = validate(submit["input_schema"], call.input)
                    if problem is None:
                        res.answer, res.outcome = call.input, "submitted"
                        return res
                    call.error = "invalid submission: %s; fix it and call %s again" % (problem, submit["name"])
                if call.error is not None:
                    results.append((call.id, "Error: " + call.error, True))
                    res.tool_errors += 1
                    continue
                try:
                    results.append((call.id, execute(call.name, call.input or {}), False))
                except (ToolError, TypeError) as e:
                    results.append((call.id, "Error: %s" % e, True))
                    res.tool_errors += 1
            conv.send_tool_results(results)
    except AuthFailure as e:
        raise EvaluatorError("credentials", "the model provider rejected the credentials: %s. Set "
                             "ANTHROPIC_API_KEY or OPENROUTER_API_KEY for the provider you chose." % e)
    except Exception as e:  # API failures end this task, not the run
        res.outcome, res.error = "error", "%s: %s" % (type(e).__name__, e)
    return res
