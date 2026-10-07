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
BUY   adoption time to first use through the best surface, read off the ladders:
               getting it running (embeddability level of its best surface: a
               published CLI installs in a minute, a source-only service takes hours)
               + first successful use (interface level: a specified contract with
               client libraries takes minutes; no programmatic surface means wrapping
               a UI, days). Measured by the agentic probe when it ran.
      yearly   price (--buy-price) + upgrade time, by contract stability

The retrofit estimate (estimate.py) is the *owner's* cost of making a project
integrable; a buyer adopts it as it is, so it isn't used here.

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
# Minutes to get it running, by the embeddability level (0..4) of its best surface.
INSTALL_MINUTES = {
    "cli": [240, 60, 15, 2, 1],        # source only ... published to a registry ... binary/container too
    "library": [240, 60, 15, 2, 1],
    "service": [960, 240, 60, 15, 5],  # undocumented setup ... env-configured ... container ... compose/Helm
}
INSTALL_MINUTES_OTHER = 60              # frontend-only or nothing detected (embeddability n/a)
# Minutes to the first successful use, by interface level (0..4); level 0 scales with size.
FIRST_USE_MINUTES = [2400, 240, 60, 10, 2]
# Upgrade minutes per year, by contract stability level (n/a: nothing to break).
UPGRADE_MINUTES = {0: 480, 1: 240, 2: 120, 3: 30, 4: 5, None: 15}
AGENT_OUTPUT_PER_HOUR = 7_500          # agent output tokens per hour of agent-assisted adoption work
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


def measured_adoption(agentic: Optional[Dict]) -> Optional[Dict]:
    """Adoption as the agentic probe measured it: the docs-scope 'run' (get it running) and
    'list' (first use) tasks of the first probe run, when both were attempted."""
    if not agentic or not agentic.get("runs"):
        return None
    tasks = {t["task"]: t for t in agentic["runs"][0]["tasks"] if t["scope"] == "docs" and t["task"] in ("run", "list")}
    if set(tasks) != {"run", "list"}:
        return None
    return {
        "model": agentic["runs"][0]["model"],
        "succeeded": all(t["success"] for t in tasks.values()),
        "outcomes": {k: t["outcome"] for k, t in tasks.items()},
        "minutes": round(sum(t.get("seconds") or 0 for t in tasks.values()) / 60.0, 2),
        "tokens": sum(t["input_tokens"] + t["output_tokens"] + t["cache_read_input_tokens"]
                      + t["cache_creation_input_tokens"] for t in tasks.values()),
        "cost_usd": None if any(t.get("cost_usd") is None for t in tasks.values())
        else round(sum(t["cost_usd"] for t in tasks.values()), 4),
    }


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

    # ---- buy: adopt as it is ------------------------------------------------
    size = min(4.0, max(0.5, math.sqrt(max(code, 1) / REFERENCE_TOKENS)))
    by_key = {d.key: d for d in dims}
    emb, iface, stab = by_key.get("embeddability"), by_key.get("interface"), by_key.get("stability")
    if emb is not None and emb.level is not None:
        install = INSTALL_MINUTES.get(emb.best_surface, INSTALL_MINUTES["service"])[emb.level]
    else:
        install = INSTALL_MINUTES_OTHER
    if_level = iface.level if iface is not None and iface.level is not None else 0
    first_use = FIRST_USE_MINUTES[if_level] * (size if if_level == 0 else 1.0)
    adoption_minutes = install + first_use
    upgrade_minutes = UPGRADE_MINUTES[stab.level if stab is not None else None]
    buy_tok = _tokens(adoption_minutes / 60.0 * AGENT_OUTPUT_PER_HOUR)
    buy_model_cost = _token_cost(price, buy_tok["input"], buy_tok["cached_input"], buy_tok["output"])
    minute_rate = day_rate / (8 * 60)
    buy_fixed = adoption_minutes * minute_rate + (buy_model_cost or 0.0)
    buy_yearly = buy_price + upgrade_minutes * minute_rate
    buy_total = buy_fixed + horizon * buy_yearly

    ratio = make_total / buy_total if buy_total else float("inf")
    verdict = "buy" if ratio >= BUY_THRESHOLD else ("make" if ratio <= MAKE_THRESHOLD else "toss-up")
    # Price per year at which both options cost the same over the horizon.
    break_even = (make_total - buy_fixed - horizon * upgrade_minutes * minute_rate) / horizon if horizon else None

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
            "via": {"install": emb.best_surface if emb is not None and emb.level is not None else None,
                    "use": iface.best_surface if iface is not None else None},
            "adoption_minutes": {"install": r(install), "first_use": r(first_use), "total": r(adoption_minutes)},
            "tokens": buy_tok,
            "model_cost": r(buy_model_cost),
            "upgrade_minutes_per_year": upgrade_minutes,
            "measured": None,
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
