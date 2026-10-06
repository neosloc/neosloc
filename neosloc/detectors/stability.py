"""Dimension 2 - Contract stability.

Can an integrator rely on the surface not moving under them? Signals: release
discipline (semver tags, changelog), API versioning, deprecation practice, and
the actual history of contract files (operations removed between revisions).
"""
from __future__ import annotations

import re
from typing import List

from ..model import DimensionResult, Evidence, clamp_level
from ..repo import Repo
from ..specs import openapi_operations
from .base import Context, register

SEMVER_TAG = re.compile(r"^v?\d+\.\d+(\.\d+)?([-+.].*)?$")
CHANGELOG = re.compile(r"^((docs?|packages/[^/]+)/)?(CHANGELOG|CHANGES|HISTORY|NEWS|RELEASES?)(\.(md|rst|txt|adoc))?$", re.I)
VERSIONED_PATH = re.compile(r"""['"`]/(api/)?v\d+(/|['"`])""")
DEPRECATION = re.compile(
    r"@Deprecated|@deprecated|DeprecationWarning|#\[deprecated|\bdeprecated\s*=\s*True"
    r"|Deprecation:|Sunset:|\[Obsolete"
)
RELEASE_AUTOMATION = re.compile(
    r"(^|/)(\.releaserc|release-please-config\.json|\.changeset/|\.goreleaser\.ya?ml|cliff\.toml)"
)
MAX_SPEC_REVISIONS = 60


def spec_history(repo: Repo, path: str):
    """Walk a spec file's git history oldest->newest; return (revisions, removals)."""
    revs = repo.git_safe("log", "--format=%H", "-n", str(MAX_SPEC_REVISIONS),
                         "--follow", "--", path).split()
    revs.reverse()
    prev = None
    removals: List[str] = []
    for rev in revs:
        text = repo.git_safe("show", "%s:%s" % (rev, path))
        ops = openapi_operations(text, path) if text else None
        if ops is None:
            continue
        if prev is not None:
            removals.extend(sorted(prev - ops))
        prev = ops
    return len(revs), removals


@register("stability", "Contract stability")
def detect(repo: Repo, ctx: Context) -> DimensionResult:
    ev: List[Evidence] = []
    gaps: List[str] = []
    score = 0.0

    tags = [t for t in repo.git_safe("tag", "--list").split() if t]
    semver = [t for t in tags if SEMVER_TAG.match(t)]
    commits = len(repo.git_safe("rev-list", "--all").split()) if repo.is_git else 0
    if semver:
        ev.append(Evidence("semver-tags", "%d semver tags (latest %s)" % (len(semver), semver[-1])))
        score += 1
    elif repo.is_git:
        gaps.append("Tag releases with semantic versions.")

    changelog = [f for f in repo.files if CHANGELOG.search(f)]
    if changelog:
        ev.append(Evidence("changelog", "", changelog[0]))
        score += 1
    else:
        gaps.append("Keep a CHANGELOG that calls out breaking changes.")

    automation = [f for f in repo.files if RELEASE_AUTOMATION.search(f)]
    if automation:
        ev.append(Evidence("release-automation", "", automation[0]))
        score += 0.5

    src = repo.source_files(include_tests=False)
    # Only where routes are declared: /v1/ in an HTTP client call is someone else's API.
    versioned = repo.grep(VERSIONED_PATH, ctx.get("route_files", []))
    versioned.update({s.path: 1 for s in ctx.get("specs", [])
                      if any(re.match(r"\w+ /(api/)?v\d+/", op) for op in s.operations)})
    if versioned:
        ev.append(Evidence("versioned-api-paths", "%d files reference /vN/ paths" % len(versioned),
                           next(iter(versioned))))
        score += 1

    deprecations = repo.grep(DEPRECATION, src)
    specs = ctx.get("specs", [])
    spec_deprecated = sum(s.deprecated for s in specs)
    if deprecations or spec_deprecated:
        ev.append(Evidence("deprecation-markers", "%d in code, %d in specs"
                           % (sum(deprecations.values()), spec_deprecated)))
        score += 1

    # Real behaviour beats declared policy: diff each OpenAPI file's history.
    removed_total, revisions_total = 0, 0
    for s in specs:
        if s.kind != "openapi" or not repo.is_git:
            continue
        nrev, removed = spec_history(repo, s.path)
        revisions_total += nrev
        removed_total += len(removed)
        if nrev > 1:
            ev.append(Evidence("spec-history", "%d revisions, %d operations removed"
                               % (nrev, len(removed)), s.path, 2))
    if revisions_total > 1:
        if removed_total == 0:
            score += 1
        elif not (deprecations or spec_deprecated):
            score -= 1
            gaps.append("%d operations were removed from the spec without deprecation markers."
                        % removed_total)

    has_surface = ctx.get("has_surface", bool(specs))
    if not has_surface:
        level = min(1, clamp_level(score))
        why = "No contract to keep stable; release hygiene only."
    else:
        level = clamp_level(score)
        why = {
            0: "No release, versioning or deprecation discipline detected.",
            1: "Some release hygiene, but integrators get no stability guarantees.",
            2: "Releases are versioned; the API itself has limited change management.",
            3: "Versioned releases plus API versioning or deprecation practice.",
            4: "Versioned releases, API versioning, deprecations and a clean contract history.",
        }[level]
    if ctx.get("route_total", 0) and not versioned and not specs:
        gaps.append("Version the API (path, header or media type) before external consumers depend on it.")

    return DimensionResult(
        "stability", "Contract stability", level, why, ev,
        metrics={
            "commits": commits,
            "tags": len(tags),
            "semver_tags": len(semver),
            "spec_revisions": revisions_total,
            "spec_operations_removed": removed_total,
            "deprecation_markers": sum(deprecations.values()) + spec_deprecated,
        },
        gaps=gaps,
    )
