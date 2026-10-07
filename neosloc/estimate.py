"""Integration cost estimate - the slot COCOMO filled in sloccount.

COCOMO turned size into effort to *build*. Here the question is the effort to
make a system *integrable*: bring every assessed dimension up to level 3
("solid"). The model is deliberately simple and every coefficient is exposed so
it can be calibrated against real retrofits:

    effort = sum(base[d] * (TARGET - level[d])) * legibility_mult * size_factor

- base[d]: person-days to raise dimension d by one level on a ~250k-token
  codebase, with agent assistance.
- legibility_mult: change legibility decides how cheaply anything else can be
  fixed, so it scales all other work.
- size_factor: sub-linear in size (sqrt), since retrofits touch boundaries,
  not every line.
"""
from __future__ import annotations

import math
from typing import Dict, List

from .model import DimensionResult

TARGET_LEVEL = 3
REFERENCE_TOKENS = 250_000
BASE_DAYS_PER_LEVEL = {
    "interface": 3.0,
    "stability": 1.0,
    "events": 2.0,
    "identity": 2.0,
    "portability": 2.0,
    "ergonomics": 1.5,
    "embeddability": 1.0,
    "extensibility": 2.0,
    "observability": 1.0,
    "legibility": 4.0,
}
LEGIBILITY_MULT = {0: 2.5, 1: 1.6, 2: 1.0, 3: 0.75, 4: 0.5}


def estimate(dims: List[DimensionResult], source_tokens: int) -> Dict:
    not_applicable = [d.key for d in dims if d.level is None]
    dims = [d for d in dims if d.level is not None]
    levels = {d.key: d.level for d in dims}
    leg = levels.get("legibility", 2)
    size_factor = min(4.0, max(0.5, math.sqrt(max(source_tokens, 1) / REFERENCE_TOKENS)))
    mult = LEGIBILITY_MULT[leg]

    per_dim = {}
    for d in dims:
        gap = max(0, TARGET_LEVEL - d.level)
        days = BASE_DAYS_PER_LEVEL.get(d.key, 1.5) * gap * size_factor
        if d.key != "legibility":
            days *= mult
        per_dim[d.key] = round(days, 1)
    total = sum(per_dim.values())

    index = sum(levels.values()) / float(len(levels)) if levels else 0.0
    return {
        "integrability_index": round(index, 2),   # 0..4, mean over applicable dimensions
        "assessed_dimensions": len(levels),
        "not_applicable": not_applicable,
        "retrofit_person_days": round(total, 1),  # agent-assisted effort to reach level 3
        "retrofit_by_dimension": per_dim,
        "wrappability": _grade(total, index),
        "assumptions": {
            "target_level": TARGET_LEVEL,
            "size_factor": round(size_factor, 2),
            "legibility_multiplier": mult,
            "reference_tokens": REFERENCE_TOKENS,
        },
    }


def _grade(days: float, index: float) -> str:
    if index >= TARGET_LEVEL:
        return "already integrable"
    if days <= 5:
        return "cheap to wrap"
    if days <= 20:
        return "moderate retrofit"
    if days <= 60:
        return "expensive retrofit"
    return "replace or wrap externally"
