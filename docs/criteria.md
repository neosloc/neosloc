# Criteria (proposal)

!!! note "Status: proposal"
    This page specifies a revised scoring model to replace the current points-and-thresholds
    model. It is not implemented yet; the shipped detectors still use the model described in
    [Dimensions](dimensions.md).

## Why the criteria change

The 0.3 criteria assume every project is a web service. A CLI was asked for RFC 9457
errors, `Idempotency-Key` headers and cursor pagination, and got nothing for `--json`
output or documented exit codes. Levels were sums of points from loose signals, so a
level could be reached by evidence that had nothing to do with the question (an HTTP
*client* reading rate-limit headers counted as offering them).

The revision rests on three rules.

1. **Each dimension asks one question, answered per surface.** The question is
   universal ("can an automated caller use it without guessing?"). The evidence that
   answers it depends on what kind of surface the project offers: an HTTP service, a
   CLI, a library, or a UI-only frontend.
2. **Levels are ladders, not sums.** Each level lists concrete requirements, and a
   surface reaches level N only when it meets every requirement of levels 1 to N. Every
   requirement is checkable, and the report names the first one that is missing.
3. **"Not applicable" is a result.** A batch CLI with no persistent data has no data to
   export. Dimensions that don't apply to any of a project's surfaces are reported as
   `n/a` and left out of the index and the retrofit estimate. N/A is decided by explicit
   rules (below), never by missing evidence.

## Surfaces

A project can offer several surfaces; each is detected independently.

| Surface | Detected when |
|---|---|
| `service` | HTTP route declarations, a server framework instance, or an MCP server. |
| `cli` | A declared entry point (console script, npm `bin`, Go `main`, Cargo binary) whose code parses arguments. |
| `library` | A publishable package whose importable API is not only an entry point (Python package, npm package with `main`/`exports`, Go non-`main` package, Rust lib crate). |
| `frontend` | An `index.html` with a bundler or framework and no server routes. |

**A dimension's level is the best level among the applicable surfaces.** An integrator
uses the best way in. The per-surface levels are reported too, so a weak CLI next to a
strong API is still visible.

The per-dimension tables use these markers: ✓ requirement, — not applicable to that
surface. Requirements are cumulative within a column.

## 1. Interface: can a program use it through a documented, machine-readable surface?

| Level | service | cli | library |
|---|---|---|---|
| 1 | Routes exist. | Invocable non-interactively: all inputs via arguments, stdin or files. | An importable API exists. |
| 2 | A contract exists (checked-in spec, or one generated from code). | `--help` documents every command and option. | The public API is delimited (`__all__`, `exports`, an explicit public module). |
| 3 | The contract covers ≥ 80% of declared routes. | Every data-producing command has machine-readable output (`--json` / `--format json`). Exit codes are documented. | The public API is statically typed (`py.typed`, `.d.ts`, a statically typed language). |
| 4 | Plus a second surface (MCP, CLI with JSON output, SDK). | The output format is specified (JSON Schema or an equivalent typed spec). | API reference generated from the code is published. |

`frontend`: — (a UI is not a programmatic surface; with no other surface the level is 0).

## 2. Contract stability: can integrators rely on it not changing under them?

Universal, applied to whichever contract each surface has (spec operations, CLI options,
public symbols).

| Level | Requirement |
|---|---|
| 1 | Releases are versioned (semver tags or published versions). |
| 2 | A changelog exists, with breaking changes explicitly marked. |
| 3 | A deprecation mechanism is used in code (`DeprecationWarning`, `@deprecated`, `Deprecation`/`Sunset` headers, deprecated CLI aliases that warn) or the API is versioned. |
| 4 | The contract's history is clean: across tagged releases, nothing was removed without first being deprecated. Checked from history for OpenAPI operations, CLI options (`add_argument`, cobra/clap definitions) and public symbols (`__all__`, `exports`). |

## 3. Events: can others react to state changes without polling?

| Level | service | long-running cli (`watch`, `serve`, daemon modes) |
|---|---|---|
| 1 | Internal events exist (signals, queues, an outbox). | Progress is printed while running. |
| 2 | Outbound webhooks *sent by this system*, or a streaming endpoint (SSE, WebSocket). | A machine-readable event stream (NDJSON / JSON Lines). |
| 3 | Webhooks are signed and registrable through the API, or there are two mechanisms. | Hooks run commands or URLs on events (`--on-change`, webhooks). |
| 4 | Events are described by AsyncAPI or CloudEvents. | The event format is specified. |

**N/A:** libraries, frontends, and CLIs without a long-running mode. Receiving other
platforms' webhooks never counts.

## 4. Identity: can a machine act with its own revocable, least-privilege identity?

| Level | service | cli / library that uses credentials |
|---|---|---|
| 1 | Some programmatic auth (bearer token, API key). | Credentials can be supplied non-interactively (env var, file, flag). |
| 2 | Credentials are per client and revocable (managed API keys, service accounts) or OAuth2. | Credentials never *need* to be on the command line (env, file or keyring), and this is documented. |
| 3 | Credentials carry scopes or permissions. | Secrets are never written to output, logs or transcripts. |
| 4 | Standard provisioning or federation (OIDC client credentials, SCIM). | Several profiles or scoped credentials per target. |

**N/A:** a CLI or library that uses no credentials, and frontends (their identity is the
backend's).

## 5. Data portability: can its data get in and out, in bulk, in open formats, with an explicit schema?

| Level | Requirement (service or app that owns persistent data) |
|---|---|
| 1 | The schema is explicit (migrations, DDL, schema files). |
| 2 | An export exists for some entities (endpoint or command, not only the UI). |
| 3 | A full bulk export in an open format (CSV, JSON/NDJSON, Parquet, a domain standard), plus a bulk import. |
| 4 | The export format is documented and versioned, and the round trip is tested. |

**N/A:** projects that own no persistent data (no ORM models, migrations or database
drivers), which includes most CLIs and libraries. A tool's *output* format belongs to
Interface (cli level 4).

## 6. Agent ergonomics: can an automated caller use it without guessing, and recover from failure?

| Level | service | cli | library |
|---|---|---|---|
| 1 | Errors are consistent JSON. | Never blocks on a prompt when stdin is not a TTY. | Errors are raised as specific exception types (no bare `Exception`, no `sys.exit` in library code). |
| 2 | Field-level validation errors; lists are paginated. | Data goes to stdout and diagnostics to stderr; failures exit non-zero. | Inputs are validated, with messages naming the bad argument. |
| 3 | Typed errors (RFC 9457 or equivalent); writes are idempotent (`Idempotency-Key` or PUT semantics); rate limits are signalled. | Documented exit codes distinguish error classes; in `--json` mode errors are JSON too; color and progress are off when not a TTY (`NO_COLOR`). | No side effects at import; timeouts and retries are configurable. |
| 4 | Dry-run or validate-only; conditional requests; agent docs (`llms.txt`). | `--dry-run` for side-effecting commands; re-runs are idempotent; long or costly operations have limits (timeouts, budgets); agent docs. | Agent docs; examples run as tests. |

## 7. Embeddability: can another system run and compose it without a human?

| Level | service | cli | library |
|---|---|---|---|
| 1 | Runnable from source with documented steps. | Runnable from source. | Importable from source. |
| 2 | Configured through environment variables, documented (`.env.example` or a schema). | Installable as a package that provides the command. | Installable as a package. |
| 3 | A container image. | Published to a public registry (PyPI, npm, crates.io, Homebrew, …) and used non-interactively in CI. | Published to a public registry with minimal dependencies. |
| 4 | Composition artifacts (compose, Helm, IaC). | Also shipped as a container image or a single binary. | Optional features behind extras; no global state. |

## 8. Extensibility: can behaviour be added without modifying the code?

Universal.

| Level | Requirement |
|---|---|
| 1 | Internal seams: a registry, decorator or strategy interface used inside the codebase. |
| 2 | The extension API is documented: the docs show how to add behaviour through those seams, even if extensions must live in the source tree. |
| 3 | **Out-of-tree extensions:** discovered through entry points, a plugin directory or configuration, without editing the package. |
| 4 | The extension API is versioned with documented compatibility, has hooks at lifecycle points, and comes with example or third-party extensions. |

"Documented" is checked by matching the docs against the project's own registration
symbols (for example a `register` decorator), not by looking for words like "plugin".

## 9. Observability: can an operator, or an orchestrating agent, tell whether it works and why not?

| Level | service | cli | library |
|---|---|---|---|
| 1 | Health or readiness endpoint, or a container healthcheck. | Meaningful exit codes; errors on stderr. | Uses a standard logger namespace (`logging.getLogger(__name__)`, `debug`), never `print`. |
| 2 | Structured logs. | Verbosity control for diagnostics (`--quiet`, `--log-level`). | Log levels are used meaningfully. |
| 3 | Metrics. | A machine-readable run summary (counts, timings, costs) or structured logs (`--log-format json`). | Optional metrics or tracing hooks. |
| 4 | Distributed tracing (OpenTelemetry). | Tracing hooks. | OpenTelemetry instrumentation available. |

## 10. Change legibility: can an agent change it safely with limited context?

Universal.

| Level | Requirement |
|---|---|
| 1 | A README and some tests. |
| 2 | CI runs the tests. Applications pin dependencies (lockfile); libraries and zero-dependency projects are exempt. |
| 3 | ≥ 90% of modules fit 32k tokens and no file exceeds 12k; test/source token ratio ≥ 0.3; ≥ 70% of the code is typed. |
| 4 | No import cycles, and agent docs (`AGENTS.md`, `CLAUDE.md`, `llms.txt`). |

## Index and estimate

- **Integrability index** = mean level over the *applicable* dimensions; the number of
  dimensions it covers is printed next to it.
- **Retrofit effort** sums only applicable dimensions, and each gap is the *first missing
  requirement* on the ladder.
- The LLM reviewer receives the surface, the ladder and the requirement that failed, so a
  disagreement points at a specific requirement.

## Worked example: neosloc 0.3.1

Surfaces: `cli` and `library`.

| Dimension | 0.3.1 | Proposed | First missing requirement |
|---|---|---|---|
| Interface | 2 | **3** (cli) | cli 4: output is described in prose (`docs/json.md`), not a JSON Schema |
| Stability | 3 | **2** | 3: no deprecation mechanism (`--model` became an alias without a warning) |
| Events | 0 | **n/a** | batch CLI and library |
| Identity | 1 | **1** | cli 2: `--auth-header` puts secrets on the command line, visible in shell history and `ps` |
| Portability | 1 | **n/a** | owns no persistent data |
| Agent ergonomics | 2 | **2** | cli 3: with `--json`, errors are still plain text on stderr |
| Embeddability | 1 | **3** | cli 4: no container image or single binary |
| Extensibility | 1 | **2** | 3: detectors must be added inside the package; no entry-point discovery |
| Observability | 0 | **1** | cli 2: no `--quiet` or log-level control (agentic progress always goes to stderr) |
| Legibility | 4 | **2** | 3: test/source ratio 0.27 < 0.3 |
| **Index** | 1.50 over 10 | **2.00 over 8** | |

Each "first missing requirement" is a concrete change to neosloc, and several are an
afternoon's work (JSON errors, `--quiet`, an `--auth-header-env` option, a
`neosloc.detectors` entry-point group).
