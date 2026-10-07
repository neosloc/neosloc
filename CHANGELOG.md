# Changelog

All notable changes are listed here. The project follows [semantic versioning](https://semver.org/);
breaking changes to the CLI, the JSON report or the scoring are called out explicitly.

## 0.7.1

- The project moved to the **neosloc** organization: https://github.com/neosloc/neosloc
  (old `sirmmo/neosloc` URLs redirect). Docs: https://neosloc.github.io/neosloc/
- The JSON Schema is published at its `$id`:
  https://neosloc.github.io/neosloc/schema/report-v2.json

## 0.7.0

- **Make or buy.** Every report now costs rebuilding an equivalent with agents (tokens,
  model cost, agent hours, human days for steering and for rediscovering history) against
  adopting the project as it is, over a horizon, with a verdict and a break-even price.
  Adoption is time to first use through the best surface, read off the ladders
  (embeddability: getting it running; interface: first use; stability: upgrades), so a
  published CLI or a standard service with client libraries is adopted in minutes. With
  `--agentic`, the probe's docs-only run and list tasks measure adoption. New options: `--buy-price`, `--horizon`, `--make-model`. New JSON field
  `make_or_buy` (additive; schema_version stays 2).
- **Desktop GUI applications** are a fifth surface (Electron, Tauri, Qt, GTK, Tkinter,
  wxWidgets, WPF/WinForms/MAUI, Avalonia, JavaFX/Swing, Compose Desktop, Rust GUI crates,
  Fyne/Wails, Flutter desktop, macOS SwiftUI/AppKit), with their own ladders: interface
  (arguments/URL schemes, automation interfaces, headless mode, automation contract),
  embeddability (installers, package-manager distribution, managed settings), observability
  (logs, verbosity, crash reports), ergonomics through the headless mode, identity through
  OS credential stores. Internal UI IPC (Electron ipcMain, Tauri commands) is not counted
  as automation. Products with a UI are adopted through it in minutes.
- **Swift**: Swift Package Manager, swift-argument-parser, Vapor/Hummingbird, `Tests/`
  targets, swift-log/os_log, `Error` types, `@available` deprecations, DocC, tag-based
  SwiftPM releases, `"""` strings and `NSRegularExpression` in the code view.
- Log-level usage is recognised on any logger variable (`log.debug(…)`), not only `logger`.
- The steering rate is calibrated on neosloc's own build (2.2 estimated vs about 2 real
  days). neoCOCOMO's reproduce term is about 20× higher for neosloc; aligning it is open.

## 0.6.0

Two criteria refinements for protocol servers and env-configured services (scores change):

- **Embeddability (service L2):** configuration counts as documented when the docs name at
  least half of the environment variables the code reads, as well as with a `.env` example
  or a config schema. Variable names are taken from `X_Y` string literals in the files that
  read the environment, so helpers like `env_or("APP_PORT", …)` are covered.
- **Agent ergonomics (service L1, and the typed-errors part of L3):** a standard protocol's
  native error replies (RESP errors, MQTT reason codes, gRPC status, SQLSTATE) count as
  machine-readable, typed errors, when the project serves that protocol.
- On the 11 validation repositories only geomqtt changes: ergonomics 0 → 1, embeddability
  1 → 4.

## 0.5.1

- **Interface: standard wire protocols are contracts.** A service that serves RESP, MQTT,
  gRPC, PostgreSQL wire, Kafka or SMTP (detected from a protocol/broker library *and* a
  listening socket, so client libraries don't count) meets the contract requirement, since
  off-the-shelf clients speak it. Level 3 is met when the application layer on top
  (commands, topics, payloads) is specified in a protocol document or AsyncAPI; each
  protocol and HTTP count as separate transports for level 4. A bare WebSocket is a surface,
  not a contract. Example: geomqtt (RESP in, MQTT out, PROTOCOL.md, HTTP) goes from 1 to 4.
- `bench/` is excluded from product code like `benchmarks/`.

## 0.5.0

- **New scoring model** (the criteria proposal, as decided):
  - **Surfaces:** each project is detected as one or more of service, CLI, library and
    frontend, and every dimension is answered per surface. A CLI is judged on `--json`,
    exit statuses and `--quiet`, not on HTTP pagination.
  - **Ladders:** levels are cumulative lists of checkable requirements instead of sums of
    points. The report names the first unmet requirement of each surface, and `-v` shows
    every ladder.
  - **Best surface:** a dimension's level is the best level among its surfaces.
  - **n/a:** dimensions that can't apply (events for libraries and batch CLIs, identity
    without credentials, portability without persistent data) are `n/a`, by explicit
    rules, and are left out of the index and the retrofit estimate.
  - Existing thresholds are unchanged (32k/12k tokens, 0.3 test ratio, 70% typed).
- **Expect different levels.** On the ten repositories used for validation, levels moved
  in both directions; see the release notes. neosloc itself goes from 1.50 over 10
  dimensions to 2.88 over 8.
- **Breaking (JSON, schema_version 2):** `level` can be `null` (with `level_name` `n/a`);
  new `question`, `applicable`, `best_surface` and per-surface `surfaces` ladders; the report
  has a top-level `surfaces` block; `estimate` has `assessed_dimensions` and
  `not_applicable`. Evidence signals are now `L<level> <requirement id>`.
- **Breaking (library):** `neosloc.detectors` is replaced by `neosloc.facts` (observations),
  `neosloc.criteria` (the ladders) and `neosloc.assess`.
- The LLM reviewer audits requirement by requirement and skips `n/a` dimensions.
- Fixes found while porting: prompts in helper modules now count against non-interactive
  CLIs; a method named `entry_points()` no longer counts as plugin discovery; strings in
  `specs.py` are no longer read as deprecation markers.
- Docs: every requirement table is generated from `criteria.py`.

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
