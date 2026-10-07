"""Ladders: levels as cumulative lists of checkable requirements.

A surface reaches level N when it meets every requirement of levels 1..N. A
dimension's level is the best level among its applicable surfaces; with no
applicable surface it is not applicable (level None). See docs/dimensions.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple, Union

from .facts import Facts, Hits

SURFACES = ("service", "cli", "library", "desktop", "frontend")
UNIVERSAL = "all"

# A check returns evidence when the requirement is met. An empty list, or a
# string explaining what was found instead, means it isn't.
CheckResult = Union[Hits, str]


@dataclass(frozen=True)
class Requirement:
    level: int
    id: str
    text: str
    check: Callable[[Facts], CheckResult]


@dataclass
class DimensionSpec:
    key: str
    title: str
    question: str
    # surface -> requirements; UNIVERSAL applies to every applicable surface once.
    ladders: Dict[str, List[Requirement]]
    # surfaces present -> surfaces this dimension applies to (subset), plus a reason when none apply
    applicable: Callable[["Surfaces"], Tuple[List[str], str]]
    zero_reason: Dict[str, str] = field(default_factory=dict)  # surface -> why level 0 (e.g. frontend)


@dataclass
class Surfaces:
    kinds: List[str]
    evidence: Dict[str, Hits]
    long_running: Hits
    owns_data: Hits
    uses_credentials: Hits
    credential_store: Hits = field(default_factory=list)

    def has(self, kind: str) -> bool:
        return kind in self.kinds


SPECS: List[DimensionSpec] = []


def register(spec: DimensionSpec) -> DimensionSpec:
    """Add a dimension. Order of registration is report order."""
    SPECS.append(spec)
    return spec


def detect_surfaces(f: Facts) -> Surfaces:
    evidence: Dict[str, Hits] = {}
    service = f.route_hits() + f.server()[:2] + f.mcp_server()[:1] + f.protocol_servers()
    if service:
        evidence["service"] = service
    if f.entry_points() and f.arg_parsing():
        evidence["cli"] = f.entry_points()[:2] + f.arg_parsing()[:1]
    if f.library():
        evidence["library"] = f.library()
    if f.desktop():
        evidence["desktop"] = f.desktop()
    if f.frontend() and "service" not in evidence and "desktop" not in evidence:
        evidence["frontend"] = f.frontend()  # an Electron/Tauri index.html is the desktop app's UI
    kinds = [k for k in SURFACES if k in evidence]
    return Surfaces(kinds, evidence, f.long_running() if "cli" in evidence else [],
                    f.owns_data(), f.uses_credentials(), f.credential_store() if "desktop" in evidence else [])


@dataclass
class RequirementResult:
    level: int
    id: str
    text: str
    met: bool
    evidence: Hits
    note: str = ""

    def to_dict(self) -> Dict:
        return {"level": self.level, "id": self.id, "text": self.text, "met": self.met,
                "evidence": [{"path": h.path, "detail": h.detail} for h in self.evidence], "note": self.note}


@dataclass
class SurfaceResult:
    surface: str
    level: int
    requirements: List[RequirementResult]

    @property
    def first_missing(self) -> Optional[RequirementResult]:
        return next((r for r in self.requirements if not r.met), None)

    def to_dict(self) -> Dict:
        fm = self.first_missing
        return {"level": self.level, "first_missing": fm.id if fm else None,
                "requirements": [r.to_dict() for r in self.requirements]}


def run_ladder(f: Facts, surface: str, reqs: List[Requirement]) -> SurfaceResult:
    results = []
    for r in sorted(reqs, key=lambda r: r.level):
        out = r.check(f)
        met = bool(out) and not isinstance(out, str)
        results.append(RequirementResult(r.level, r.id, r.text, met, out if met else [],
                                         out if isinstance(out, str) else ""))
    level = 0
    for lvl in range(1, 5):
        at = [r for r in results if r.level == lvl]
        if at and all(r.met for r in at):
            level = lvl
        else:
            break
    return SurfaceResult(surface, level, results)
