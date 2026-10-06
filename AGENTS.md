# AGENTS.md

- Standard library only, Python >= 3.8. Do not add dependencies.
- Run: `python3 -m neosloc PATH [--json] [-v] [--only interface,legibility]`
- Test: `python3 -m unittest -v tests/test_neosloc.py`
- A detector is `fn(repo, ctx) -> DimensionResult`, registered with `@register(key, title)` in
  `neosloc/detectors/`. Import order in `detectors/__init__.py` is report order; `interface`
  must run first because it puts `specs`, `route_files` and `route_total` into `ctx`.
- Every level must be backed by `Evidence` with a path, and every missing point should
  produce a `gap` phrased as an action.
- Calibrate against real repos before changing thresholds; add a regression test for each
  false positive you fix.
