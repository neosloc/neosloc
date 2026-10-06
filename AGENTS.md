# AGENTS.md

- Core is standard library only, Python >= 3.8. Do not add dependencies. The `anthropic`
  SDK is an optional extra used only by `neosloc/agentic/` and imported lazily.
- Run: `python3 -m neosloc PATH [--json] [-v] [--only interface,legibility]`
- Test: `python3 -m unittest discover -s tests -t .` (the SDK contract test is skipped
  without the SDK; with it: `uv run --no-project --python 3.12 --with anthropic python -m unittest discover -s tests -t .`)
- A detector is `fn(repo, ctx) -> DimensionResult`, registered with `@register(key, title)`
  from `neosloc/detectors/base.py`. Import order in `detectors/__init__.py` is report order;
  `interface` runs first because it puts `specs`, `route_files`, `route_total` and
  `has_surface` into `ctx`.
- Signal-style detectors are tables of `Signal`s (`detectors/signals.py`). Trust library
  names only in dependency manifests (`deps`), not in code, so neosloc's own regexes and
  vendored code don't match.
- Every level must be backed by `Evidence` with a path, and every missing point should
  produce a `gap` phrased as an action.
- Calibrate against real repos before changing thresholds; add a regression test for each
  false positive you fix.
- Never run `--agentic` against the real API in tests; use the fake client in
  `tests/test_agentic.py` or the mock server in `tests/test_sdk_contract.py`.
