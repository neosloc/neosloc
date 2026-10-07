"""Make or buy: rebuild an equivalent with agents, or adopt this project?

Once agents write code, a product is only worth adopting if rebuilding what
you need costs more. Both options are costed over the same horizon, in money,
tokens and time:

MAKE  tokens   final = code + tests needed to verify it + a spec for behaviour
                       that isn't captured (tests, contract, docs)
               output = final x DRAFT_FACTOR      (drafts, fixes, failed attempts)
               input  = output x CONTEXT_RATIO    (context re-read every turn),
                        CACHED_SHARE of it served from the prompt cache
      agents   output / OUTPUT_TPS x TOOL_OVERHEAD, spread over PARALLEL_AGENTS
      humans   final / REVIEW_TOKENS_PER_DAY x (1 + SPEC_DIFFICULTY x (1 - capture))
               + rediscovering uncaptured history (neoCOCOMO rediscover term)
      yearly   MAINTENANCE_SHARE of the build, every year
BUY   humans   retrofit to level 3 of the dimensions a consumer depends on (estimate.py,
               without legibility: buyers don't change the code) + onboarding
      yearly   price (--buy-price) + upgrade days, fewer when contracts are stable;
               onboarding and upgrades scale with size like the retrofit does

Calibration: REVIEW_TOKENS_PER_DAY is anchored on neosloc itself (~70k tokens of
code and tests, built in about two days by one person directing an agent). The
other constants are uncalibrated guesses, kept here so they can be fitted.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from .estimate import REFERENCE_TOKENS
from .model import DimensionResult

DRAFT_FACTOR = 3.0
CONTEXT_RATIO = 25.0
CACHED_SHARE = 0.85
MIN_TEST_RATIO = 0.3
SPEC_SHARE = 0.10
REVIEW_TOKENS_PER_DAY = 50_000
SPEC_DIFFICULTY = 2.0
OUTPUT_TPS = 50.0
TOOL_OVERHEAD = 2.0
PARALLEL_AGENTS = 4
AGENT_HOURS_PER_DAY = 8.0
MAINTENANCE_SHARE = 0.15
ONBOARDING_DAYS = 1.0
UPGRADE_DAYS = {0: 6.0, 1: 4.0, 2: 3.0, 3: 2.0, 4: 1.0}
AGENT_OUTPUT_PER_DAY = 60_000      # agent output tokens per day of agent-assisted integration work
WORK_DAYS_PER_MONTH = 21.0
DEFAULT_MODEL = "anthropic:claude-opus-5-5"
BUY_THRESHOLD, MAKE_THRESHOLD = 1.5, 1 / 1.5


def prices(spec: str) -> Optional[Dict[str, float]]:
    """USD per million tokens for a model spec, or None when unknown offline."""
    from .agentic.llm import ANTHROPIC_PRICES, parse_spec
    provider, model = parse_spec(spec)
    if provider == "anthropic" and model in ANTHROPIC_PRICES:
        pin, pout, pread = ANTHROPIC_PRICES[model]
        return {"input": pin, "output": pout, "cache_read": pread}
    if provider == "openrouter":
        try:
            from .agentic.llm import openrouter_models
            p = (openrouter_models().get(model) or {}).get("pricing") or {}
            if p.get("prompt") is not None:
                return {"input": float(p["prompt"]) * 1e6, "output": float(p.get("completion") or 0) * 1e6,
                        "cache_read": float(p.get("input_cache_read") or p["prompt"]) * 1e6}
        except Exception:  # offline: report tokens without a price
            return None
    return None


def _token_cost(price: Optional[Dict[str, float]], inp: int, cached: int, out: int) -> Optional[float]:
    if price is None:
        return None
    return ((inp - cached) * price["input"] + cached * price["cache_read"] + out * price["output"]) / 1e6


def _tokens(output: float) -> Dict[str, int]:
    out = int(output)
    inp = int(out * CONTEXT_RATIO)
    return {"output": out, "input": inp, "cached_input": int(inp * CACHED_SHARE)}


def make_or_buy(dims: List[DimensionResult], legibility: Dict, value: Dict, estimate: Dict,
                buy_price: float = 0.0, horizon: float = 3.0, model: str = DEFAULT_MODEL) -> Dict:
    day_rate = value["assumptions"]["cost_per_pm"] / WORK_DAYS_PER_MONTH
    capture = value["capture"]["capture"]
    price = prices(model)

    # ---- make ----------------------------------------------------------------
    code = legibility["source_tokens"]
    tests = max(legibility["test_tokens"], MIN_TEST_RATIO * code)
    spec = SPEC_SHARE * code * (1 - capture)
    final = code + tests + spec
    make_tok = _tokens(final * DRAFT_FACTOR)
    make_model_cost = _token_cost(price, make_tok["input"], make_tok["cached_input"], make_tok["output"])
    agent_hours = make_tok["output"] / OUTPUT_TPS / 3600 * TOOL_OVERHEAD
    review_days = final / REVIEW_TOKENS_PER_DAY * (1 + SPEC_DIFFICULTY * (1 - capture))
    rediscover_days = value["rediscover_pm"] * WORK_DAYS_PER_MONTH
    human_days = review_days + rediscover_days
    calendar_days = max(human_days, agent_hours / (AGENT_HOURS_PER_DAY * PARALLEL_AGENTS))
    make_build = human_days * day_rate + (make_model_cost or 0.0)
    make_yearly = MAINTENANCE_SHARE * make_build
    make_total = make_build + horizon * make_yearly

    # ---- buy -----------------------------------------------------------------
    size = min(4.0, max(0.5, math.sqrt(max(code, 1) / REFERENCE_TOKENS)))
    consumer_retrofit = sum(v for k, v in estimate["retrofit_by_dimension"].items() if k != "legibility")
    integration_days = consumer_retrofit + ONBOARDING_DAYS * size
    buy_tok = _tokens(integration_days * AGENT_OUTPUT_PER_DAY)
    buy_model_cost = _token_cost(price, buy_tok["input"], buy_tok["cached_input"], buy_tok["output"])
    stab = next((d.level for d in dims if d.key == "stability"), None)
    upgrade_days = UPGRADE_DAYS[2 if stab is None else stab] * size
    buy_fixed = integration_days * day_rate + (buy_model_cost or 0.0)
    buy_yearly = buy_price + upgrade_days * day_rate
    buy_total = buy_fixed + horizon * buy_yearly

    ratio = make_total / buy_total if buy_total else float("inf")
    verdict = "buy" if ratio >= BUY_THRESHOLD else ("make" if ratio <= MAKE_THRESHOLD else "toss-up")
    # Price per year at which both options cost the same over the horizon.
    break_even = (make_total - buy_fixed - horizon * upgrade_days * day_rate) / horizon if horizon else None

    def r(x):
        return None if x is None else round(x, 2)

    return {
        "verdict": verdict,
        "make_buy_ratio": round(ratio, 4),
        "horizon_years": horizon,
        "break_even_price_per_year": r(break_even),
        "make": {
            "model": model,
            "tokens": make_tok,
            "final_tokens": int(final),
            "model_cost": r(make_model_cost),
            "agent_hours": r(agent_hours),
            "human_days": r(human_days),
            "review_days": r(review_days),
            "rediscover_days": r(rediscover_days),
            "calendar_days": r(calendar_days),
            "build_cost": r(make_build),
            "yearly_cost": r(make_yearly),
            "total_cost": r(make_total),
        },
        "buy": {
            "tokens": buy_tok,
            "model_cost": r(buy_model_cost),
            "integration_days": r(integration_days),
            "upgrade_days_per_year": r(upgrade_days),
            "price_per_year": buy_price,
            "fixed_cost": r(buy_fixed),
            "yearly_cost": r(buy_yearly),
            "total_cost": r(buy_total),
        },
        "assumptions": {
            "day_rate": r(day_rate), "draft_factor": DRAFT_FACTOR, "context_ratio": CONTEXT_RATIO,
            "cached_share": CACHED_SHARE, "review_tokens_per_day": REVIEW_TOKENS_PER_DAY,
            "spec_difficulty": SPEC_DIFFICULTY, "maintenance_share": MAINTENANCE_SHARE,
            "model_priced": price is not None,
        },
    }
