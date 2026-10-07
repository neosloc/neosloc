"""Run the criteria: detect surfaces, climb each ladder, pick the best surface."""
from __future__ import annotations

import importlib
import time
from typing import Dict, List, Optional, Tuple

from .facts import Facts
from .ladder import SPECS, UNIVERSAL, DimensionSpec, SurfaceResult, Surfaces, detect_surfaces, run_ladder
from .log import logger
from .model import DimensionResult, Evidence
from .repo import Repo

importlib.import_module(".criteria", __package__)  # registers the ten dimensions


def dimension_keys() -> List[str]:
    return [s.key for s in SPECS]


def surfaces_summary(s: Surfaces) -> Dict:
    def ev(hits):
        return [{"path": h.path, "detail": h.detail} for h in hits[:3]]
    return {
        "kinds": s.kinds,
        "evidence": {k: ev(v) for k, v in s.evidence.items()},
        "long_running": ev(s.long_running),
        "owns_data": ev(s.owns_data),
        "uses_credentials": ev(s.uses_credentials),
    }


def _result(spec: DimensionSpec, f: Facts, surfaces: Surfaces) -> DimensionResult:
    applicable, reason = spec.applicable(surfaces)
    if not applicable:
        return DimensionResult(spec.key, spec.title, None, "Not applicable: %s." % reason, question=spec.question)
    results: Dict[str, SurfaceResult] = {}
    for surface in applicable:
        ladder = spec.ladders[UNIVERSAL if surface == UNIVERSAL else surface]
        results[surface] = run_ladder(f, surface, ladder)
    best = max(results.values(), key=lambda r: (r.level, -applicable.index(r.surface)))
    label = "" if best.surface == UNIVERSAL or len(results) == 1 else "[%s] " % best.surface
    met = [r for r in best.requirements if r.met and r.level <= best.level]
    if met:
        rationale = label + met[-1].text
    else:
        fm = best.first_missing
        rationale = label + "Not yet: " + (fm.text if fm else "no requirement met")
    evidence = []
    for r in met:
        h = r.evidence[0]
        evidence.append(Evidence("L%d %s" % (r.level, r.id), h.detail, h.path))
    gaps = []
    for res in results.values():
        fm = res.first_missing
        if fm is None:
            continue
        prefix = "" if res.surface == UNIVERSAL or len(results) == 1 else "[%s] " % res.surface
        gaps.append("%sL%d %s%s" % (prefix, fm.level, fm.text, (" (%s)" % fm.note) if fm.note else ""))
    metrics: Dict = {}
    if spec.key == "legibility":
        metrics = {k: v for k, v in f.legibility().items() if k not in ("test_example",)}
    elif spec.key == "interface":
        cov = f.spec_coverage()
        metrics = {"route_declarations": f.route_total(),
                   "routes_by_framework": {k: sum(v.values()) for k, v in f.routes().items()},
                   "spec_files": len(f.specs()),
                   "spec_operations": sum(len(s.operations) for s in f.specs() if s.kind == "openapi"),
                   "spec_coverage": None if cov is None else round(cov, 2)}
    return DimensionResult(spec.key, spec.title, best.level, rationale, evidence, metrics, gaps,
                           question=spec.question, best_surface=best.surface,
                           surfaces={k: v.to_dict() for k, v in results.items()})


def assess(repo: Repo, only: Optional[List[str]] = None) -> Tuple[List[DimensionResult], Surfaces, Facts]:
    f = Facts(repo)
    t = time.time()
    surfaces = detect_surfaces(f)
    f.surfaces = surfaces
    logger.debug("surfaces: %s in %.2fs", ", ".join(surfaces.kinds) or "none", time.time() - t,
                 extra={"surfaces": surfaces.kinds, "seconds": round(time.time() - t, 3)})
    out = []
    for spec in SPECS:
        if only and spec.key not in only:
            continue
        t = time.time()
        res = _result(spec, f, surfaces)
        logger.debug("dimension %s: %s in %.2fs", spec.key, res.level_name, time.time() - t,
                     extra={"dimension": spec.key, "dimension_level": res.level, "seconds": round(time.time() - t, 3)})
        out.append(res)
    return out, surfaces, f
