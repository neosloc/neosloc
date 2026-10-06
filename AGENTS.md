# AGENTS.md

- Core is standard library only, Python >= 3.8. Do not add dependencies. The `anthropic`
  SDK is an optional extra, imported lazily by `neosloc/agentic/llm.py`; the OpenRouter
  backend uses urllib, so it needs nothing extra.
- Run: `python3 -m neosloc PATH [--json] [-v] [--only interface,legibility]`
- Test: `python3 -m unittest discover -s tests -t .` (the SDK contract test is skipped
  without the SDK; with it: `uv run --no-project --python 3.12 --with anthropic python -m unittest discover -s tests -t .`)
- Docs: `uv run --no-project --with-requirements docs/requirements.txt mkdocs build --strict`.
  `docs/hooks.py` renders signal tables, the CLI help and the task list from the code;
  don't copy those by hand.
- Release: bump `neosloc/__init__.py`, add a CHANGELOG section, push tag `vX.Y.Z`
  (`.github/workflows/release.yml` publishes to PyPI and creates the GitHub release).
- LLM roles (probe, judge, review) all go through `agentic/loop.py:run_loop` over a
  provider-neutral `Conversation` (`agentic/llm.py`). New roles should do the same and
  charge the shared `Budget`.
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
- Never call real model APIs in tests; use the fake client in `tests/test_agentic.py`,
  the Messages API mock in `tests/test_sdk_contract.py` or the OpenRouter mock in
  `tests/test_openrouter.py`.
