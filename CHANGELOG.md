# Changelog

All notable changes are listed here. The project follows [semantic versioning](https://semver.org/);
breaking changes to the CLI, the JSON report or the scoring are called out explicitly.

## 0.4.0

- **JSON Schema for `--json` output**, printed by `neosloc --schema` and published in the
  docs. Every document now has `schema_version` (1).
- **Errors are JSON with `--json`:** `{"schema_version": 1, "error": {"code", "message",
  "exit_status", "details"}}` on stdout, for usage errors, bad paths, evaluator setup
  failures, interrupts and internal errors alike. With several paths, failed paths become
  error entries in the list and the other reports are kept.
- **Exit statuses distinguish error classes:** 1 internal, 2 usage, 3 path, 4 evaluator
  setup, 130 interrupted. **Breaking:** a missing path used to exit 2; it now exits 3.
- **Diagnostics are logged** on stderr through the `neosloc` logger: `--log-level
  debug|info|warning|error`, `NEOSLOC_LOG_LEVEL`, `-q/--quiet`, and `--log-format json`
  for one JSON object per line. Debug level shows per-detector levels and timings.
- `--only` now rejects unknown dimension keys (`unknown_dimension`) instead of ignoring them.
- Library API: evaluator failures raise `neosloc.errors.EvaluatorError` (with a `code`)
  instead of `SystemExit`.
- Tests: 87 → 116; line coverage 87% → 93%, with a 90% floor in CI and full schema
  validation of real output.

## 0.3.1

- **Scoring fix:** content signals now match a *code view* that drops comments,
  docstrings, prose strings and regex literals, so text that talks about a practice no
  longer counts as using it. neosloc scanning itself went from identity 4 / ergonomics 4 /
  events 3 / observability 3 to 1 / 2 / 0 / 0. Expect some levels to drop on other
  projects too: docstrings mentioning "idempotent" or "JWT" no longer count.
- New `neosloc: ignore` pragma (a comment in a file's first five lines) to exclude
  detection-vocabulary files from content signals.
- Portability: `json.dumps` and generic `dump()` methods are no longer exports.
- Stability: Django-style versioned routes (`r'^api/v1/…'`) now count as API versioning.

## 0.3.0

- OpenRouter as a model provider (`openrouter:<vendor/model>`), with no extra dependency.
- Three evaluator roles: `--agentic` (probe), `--judge` (checks grounded probe answers
  against the source) and `--review` (audits each static level). Comma-separated models
  run a panel and report agreement.
- One `--max-cost` budget shared by every model call; the report states total spend.
- **Breaking (JSON):** `agentic` is now `{"runs": [...], "panel": ...}` instead of a
  single run. New top-level `review` and `spend` keys.
- **Breaking (CLI):** `--model` is now an alias of `--probe-model` and accepts `provider:model`.
- `pip install neosloc` provides the `neosloc` command. Documentation site added.

## 0.2.0

- Events, identity, portability, agent ergonomics, extensibility and observability dimensions.
- neoCOCOMO value model (cost approach for the agent era), with classic COCOMO for comparison.
- Agentic probe with docs/source scopes, live HTTP mode and grounding grader.

## 0.1.0

- Static assessment of interface, stability, embeddability and legibility; retrofit estimate.
