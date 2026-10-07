"""Result types shared by all detectors."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

LEVEL_NAMES = {
    0: "absent",
    1: "ad hoc",
    2: "partial",
    3: "solid",
    4: "exemplary",
}


@dataclass
class Evidence:
    """One observed fact backing a level. `path` is repo-relative when present."""
    signal: str
    detail: str = ""
    path: Optional[str] = None
    weight: int = 1


@dataclass
class DimensionResult:
    key: str
    title: str
    level: int
    rationale: str
    evidence: List[Evidence] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    gaps: List[str] = field(default_factory=list)

    @property
    def level_name(self) -> str:
        return LEVEL_NAMES[self.level]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["level_name"] = self.level_name
        return d


@dataclass
class Report:
    target: str
    inventory: Dict[str, Any]
    dimensions: List[DimensionResult]
    estimate: Dict[str, Any]
    not_implemented: List[str]
    value: Optional[Dict[str, Any]] = None
    agentic: Optional[Dict[str, Any]] = None
    review: Optional[Dict[str, Any]] = None
    spend: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        from .schema import SCHEMA_VERSION
        return {
            "schema_version": SCHEMA_VERSION,
            "target": self.target,
            "inventory": self.inventory,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "estimate": self.estimate,
            "not_implemented": self.not_implemented,
            "value": self.value,
            "agentic": self.agentic,
            "review": self.review,
            "spend": self.spend,
        }


def clamp_level(n: float) -> int:
    return max(0, min(4, int(round(n))))
