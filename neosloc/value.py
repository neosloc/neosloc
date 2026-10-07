"""neoCOCOMO - what a codebase is worth when writing code is cheap.

sloccount priced software with COCOMO: effort to write it by hand. That number
is still printed for comparison, but it no longer measures value: an agent can
re-type the code for a fraction of it. What stays expensive is what an agent
can't regenerate from the repo: behaviour that is not written down anywhere
except in the code and in the history of fixes that shaped it.

The model follows the accounting *cost approach* (replacement cost new, less
obsolescence), with replacement priced for the agent era:

    classic   = 2.4 * KSLOC^1.05                     (COCOMO organic, person-months)
    capture   = share of behaviour pinned by tests, contracts and docs   (0..1)
    reproduce = classic * (FLOOR + (1 - FLOOR) * REDISCOVER_SHARE * (1 - capture))
    knowledge = FIX_PM * fix_commits + CHANGE_PM * other_commits
    rediscover = knowledge * (1 - capture)
    replacement = reproduce + rediscover
    value = replacement * leverage(integrability) * obsolescence(staleness, legibility)

All coefficients are module constants so they can be calibrated; none of them
is empirically fitted yet.
"""
from __future__ import annotations

import re
import time
from typing import Dict, List

from .model import DimensionResult
from .repo import Repo, estimate_tokens

# Classic COCOMO 81 organic mode and sloccount's defaults, for comparison.
COCOMO_A, COCOMO_B = 2.4, 1.05
SCHEDULE_C, SCHEDULE_D = 2.5, 0.38
SLOCCOUNT_SALARY, SLOCCOUNT_OVERHEAD = 56_286, 2.4

# Agent-era reproduction: even perfectly specified code needs review,
# integration and verification (FLOOR); undocumented behaviour has to be
# re-derived, which costs up to REDISCOVER_SHARE of the original effort.
FLOOR = 0.10
REDISCOVER_SHARE = 0.5

# Knowledge embodied in history, in person-months per commit.
FIX_PM = 0.025      # ~half a day to find, understand and fix a defect
CHANGE_PM = 0.005   # ~0.1 day of decision-making behind an ordinary change
FIX_RE = re.compile(r"\b(fix(e[sd])?|bug|hotfix|patch|regression|crash|broken|workaround|revert)\b", re.I)


def git_history(repo: Repo) -> Dict:
    out = repo.git_safe("log", "--no-merges", "--format=%ct\t%ae\t%s")
    commits = [line.split("\t", 2) for line in out.splitlines() if line.count("\t") >= 2]
    if not commits:
        return {"commits": 0, "fix_commits": 0, "authors": 0, "age_months": 0.0,
                "months_since_last": None}
    stamps = [int(c[0]) for c in commits]
    now = time.time()
    return {
        "commits": len(commits),
        "fix_commits": sum(1 for c in commits if FIX_RE.search(c[2])),
        "authors": len({c[1].lower() for c in commits}),
        "age_months": round((max(stamps) - min(stamps)) / (30.44 * 86400), 1),
        "months_since_last": round((now - max(stamps)) / (30.44 * 86400), 1),
    }


def _capture(repo: Repo, dims: Dict[str, DimensionResult]) -> Dict[str, float]:
    """How much of the behaviour is pinned down outside the implementation."""
    leg = dims.get("legibility")
    src_tokens = (leg.metrics.get("source_tokens") if leg else 0) or 1
    test_ratio = leg.metrics.get("test_ratio", 0.0) if leg else 0.0
    tests = min(1.0, test_ratio / 0.5)
    iface = dims.get("interface")
    contract = (iface.level / 4.0) if iface and iface.level is not None else 0.0
    doc_tokens = sum(estimate_tokens(repo.read(f)) for f in repo.doc_files())
    docs = min(1.0, (doc_tokens / float(src_tokens)) / 0.2)
    total = 0.5 * tests + 0.25 * contract + 0.25 * docs
    return {"tests": round(tests, 2), "contract": round(contract, 2), "docs": round(docs, 2),
            "capture": round(total, 2)}


def _staleness(months_since_last) -> float:
    if months_since_last is None or months_since_last <= 12:
        return 1.0
    if months_since_last <= 36:
        return 0.85
    return 0.7


def value(repo: Repo, results: List[DimensionResult], salary: float = SLOCCOUNT_SALARY,
          overhead: float = SLOCCOUNT_OVERHEAD) -> Dict:
    dims = {d.key: d for d in results}
    src = repo.source_files(include_tests=False)
    sloc = sum(repo.sloc(f) for f in src)
    ksloc = sloc / 1000.0
    pm_cost = salary / 12.0 * overhead

    classic_pm = COCOMO_A * ksloc ** COCOMO_B if ksloc else 0.0
    schedule = SCHEDULE_C * classic_pm ** SCHEDULE_D if classic_pm else 0.0

    cap = _capture(repo, dims)
    c = cap["capture"]
    agent_factor = FLOOR + (1 - FLOOR) * REDISCOVER_SHARE * (1 - c)
    reproduce = classic_pm * agent_factor

    hist = git_history(repo)
    knowledge = FIX_PM * hist["fix_commits"] + CHANGE_PM * (hist["commits"] - hist["fix_commits"])
    rediscover = knowledge * (1 - c)
    replacement = reproduce + rediscover

    assessed = [d.level for d in results if d.level is not None]
    index = sum(assessed) / float(len(assessed)) if assessed else 0.0
    leverage = 0.75 + 0.125 * index
    legibility = dims["legibility"].level if "legibility" in dims and dims["legibility"].level is not None else 2
    obsolescence = _staleness(hist["months_since_last"]) * (0.85 + 0.05 * legibility)
    val = replacement * leverage * obsolescence

    return {
        "ksloc": round(ksloc, 2),
        "classic": {
            "person_months": round(classic_pm, 2),
            "schedule_months": round(schedule, 1),
            "cost": round(classic_pm * pm_cost),
        },
        "capture": cap,
        "agent_factor": round(agent_factor, 2),
        "reproduce_pm": round(reproduce, 2),
        "history": hist,
        "knowledge_pm": round(knowledge, 2),
        "rediscover_pm": round(rediscover, 2),
        "replacement_pm": round(replacement, 2),
        "leverage": round(leverage, 2),
        "obsolescence": round(obsolescence, 2),
        "value_pm": round(val, 2),
        "value_cost": round(val * pm_cost),
        "knowledge_at_risk": round(rediscover / replacement, 2) if replacement else 0.0,
        "assumptions": {"salary": salary, "overhead": overhead, "cost_per_pm": round(pm_cost),
                        "floor": FLOOR, "rediscover_share": REDISCOVER_SHARE,
                        "fix_pm": FIX_PM, "change_pm": CHANGE_PM},
    }
