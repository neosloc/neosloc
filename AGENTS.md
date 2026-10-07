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
- Scoring is ladders of requirements per surface (`neosloc/criteria.py`, the specification;
  docs/dimensions.md renders it). Checks combine facts from `neosloc/facts.py`, where all
  pattern knowledge lives. `neosloc/ladder.py` detects surfaces and climbs ladders;
  `neosloc/assess.py` picks the best surface. n/a is decided by applicability rules over
  surfaces and properties, never by missing evidence.
- Vocabulary files (`facts.py`, `criteria.py`, `specs.py`) start with `# neosloc: ignore`.
  Trust library names only via `f.deps(...)` (manifests), never in code.
- A check returns evidence (`Hit`s with paths) when met, or a short reason when not; the
  first unmet requirement per surface becomes the gap.
- Calibrate against real repos before changing thresholds; add a regression test for each
  false positive you fix.
- Never call real model APIs in tests; use the fake client in `tests/test_agentic.py`,
  the Messages API mock in `tests/test_sdk_contract.py` or the OpenRouter mock in
  `tests/test_openrouter.py`.
- CLI contract: results on stdout, diagnostics on stderr via `neosloc.log.logger` (never
  `print` to stderr). Failures raise a `neosloc.errors.NeoslocError` subclass with a code
  listed in `schema.ERROR_CODES`; `cli.main` renders it (JSON with `--json`). Any change to
  `--json` output must update `neosloc/schema.py`; the strict schema makes tests fail otherwise.
