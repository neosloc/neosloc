"""Table-driven scoring shared by the signal-style detectors.

A `Signal` is one observable practice: where to look, what to match, how many
points it is worth, and the gap to report when it is missing. Detectors list
their signals and map the summed points to a level.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ..model import Evidence
from ..repo import Repo

# Where a signal looks:
#   code      product source (no tests/examples/generated)
#   deps      dependency manifests (library names are only trusted here)
#   code+deps either of the above
#   config    yaml/toml/json/ini/Dockerfile outside tests
#   docs      markdown/rst/txt and docs/ trees
#   path      the regex matches file paths, not contents
#   routes    files that declare HTTP routes (needs the interface detector)
WHERE = ("code", "deps", "code+deps", "config", "docs", "path", "routes", "any")


@dataclass
class Signal:
    name: str
    where: str
    pattern: str
    points: float
    gap: Optional[str] = None
    group: Optional[str] = None  # only the first matching signal of a group scores

    def __post_init__(self):
        assert self.where in WHERE, self.where


def _files(repo: Repo, where: str, ctx: dict) -> List[str]:
    code = repo.source_files(include_tests=False)
    return {
        "code": lambda: code,
        "deps": repo.manifests,
        "code+deps": lambda: code + repo.manifests(),
        "config": repo.config_files,
        "docs": repo.doc_files,
        "routes": lambda: ctx.get("route_files", []),
        "any": lambda: code + repo.manifests() + repo.config_files() + repo.doc_files(),
    }[where]()


def score_signals(repo: Repo, ctx: dict, signals: Sequence[Signal]
                  ) -> Tuple[float, List[Evidence], Set[str], List[str]]:
    """Return (points, evidence, names found, gaps for missing signals)."""
    score = 0.0
    evidence: List[Evidence] = []
    found: Set[str] = set()
    groups_scored: Set[str] = set()
    gaps: List[str] = []
    for sig in signals:
        if sig.where == "path":
            rx = re.compile(sig.pattern)
            hits: Dict[str, int] = {f: 1 for f in repo.files if rx.search(f)}
        else:
            hits = repo.grep(re.compile(sig.pattern, re.M | re.I), _files(repo, sig.where, ctx),
                             keep_regex=sig.where == "routes")
        if hits:
            found.add(sig.name)
            top = max(hits, key=hits.get)
            evidence.append(Evidence(sig.name, "%d file(s)" % len(hits), top))
            if sig.group is None or sig.group not in groups_scored:
                score += sig.points
                if sig.group:
                    groups_scored.add(sig.group)
        elif sig.gap and (sig.group is None or sig.group not in groups_scored):
            gaps.append(sig.gap)
    # A gap for a group that was satisfied later in the list is not a gap.
    gaps = [g for g, s in ((s.gap, s) for s in signals if s.gap)
            if g in gaps and (s.group is None or s.group not in groups_scored)
            and s.name not in found]
    return score, evidence, found, list(dict.fromkeys(gaps))


def level_from(score: float, thresholds: Sequence[float]) -> int:
    """thresholds = points needed for levels 1..4."""
    level = 0
    for i, t in enumerate(thresholds, start=1):
        if score >= t:
            level = i
    return level
