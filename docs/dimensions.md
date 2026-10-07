# Dimensions

neosloc scores ten dimensions. Each one asks a single question, and the evidence that
answers it depends on **what kind of surface** the project offers. A CLI is asked about
`--json` output and exit statuses, not RFC 9457 errors and pagination.

The requirement tables on this page are generated from `neosloc/criteria.py` whenever the
docs are built, so they always match the code.

## How a level is decided

1. **Surfaces are detected.** A project can offer several:

    | Surface | Detected when |
    |---|---|
    | `service` | HTTP routes are declared, a server framework is instantiated, an MCP server exists, or a standard protocol is served (RESP, MQTT, gRPC, PostgreSQL wire, Kafka, SMTP, WebSocket: a protocol or broker library plus a listening socket). |
    | `cli` | A declared entry point (console script, npm `bin`, Go `main`, Cargo binary) and argument parsing. |
    | `library` | A distributable package with an importable API (a Python package, an npm package with `main`/`exports` that isn't a web app, a Go module with non-`main` packages, a Rust lib crate). A service counts as a library only if it is published. |
    | `desktop` | A desktop GUI toolkit: Electron, Tauri, Qt, GTK, Tkinter, wxWidgets, WPF/WinForms/MAUI, Avalonia, JavaFX/Swing, Compose Desktop, Rust GUI crates (egui, iced, slint), Fyne/Wails, Flutter desktop, or a macOS SwiftUI/AppKit app (SwiftUI alone may be iOS, so a macOS indicator is required). |
    | `frontend` | An `index.html` with a `package.json`, and no service or desktop app (an Electron/Tauri `index.html` is the desktop app's UI). |

    Three more properties decide whether some dimensions apply: a **long-running mode**
    (`--watch`, `serve`, `daemon`), **owning persistent data** (migrations, ORM models,
    database drivers, SQLite files), and **using credentials** (credential environment
    variables or secret options).

2. **Each applicable surface climbs a ladder.** Every level lists requirements. A surface
   reaches level N only when it meets *every* requirement of levels 1 to N; a met
   requirement above an unmet one doesn't count.

3. **The dimension's level is the best surface's level.** Integrators use the best way in.
   The other surfaces' levels and first missing requirements are still reported
   (`[cli] L2 …` in the gaps; the full ladders with `-v` or in the JSON).

4. **Not applicable (`n/a`) is a result, decided by rules, never by missing evidence.** A
   dimension that applies to none of the project's surfaces is reported as `n/a` and left
   out of the integrability index and the retrofit estimate. The rules are given with each
   dimension below. Interface is never `n/a`: having no programmatic surface is level 0.

| Level | Name |
|---|---|
| 0 | absent |
| 1 | ad hoc |
| 2 | partial |
| 3 | solid (the target of retrofit estimates) |
| 4 | exemplary |

## Languages

Every language is inventoried and counted, and Python, JavaScript/TypeScript, Go, Rust,
Java/Kotlin, C#, PHP, Ruby and **Swift** have dedicated patterns. For Swift that means
Swift Package Manager (`Package.swift` executables, libraries and dependencies, tags as
releases, `Package.resolved`), swift-argument-parser CLIs, Vapor/Hummingbird routes,
`Tests/` targets, swift-log and `os_log`, `Error` types, `@available(*, deprecated…)`,
DocC catalogs, and `"""` strings and `NSRegularExpression` patterns in the code view.

## What counts as evidence

Detectors read **product code** only: tests, examples, docs, fixtures, vendored code
(`vendor/`, `third_party/`, `libs/`, …) and generated or minified files are excluded.
Library names count only when they appear in dependency manifests, and transitive Go
dependencies (`// indirect`) are ignored.

Code is matched through a **code view** that removes text which talks *about* a practice
instead of using it:

- comments and docstrings;
- strings that read like sentences (messages, help texts, prompts);
- the contents of regex literals (Python raw strings and `re.*` arguments, JS `/…/` and
  `RegExp`, Go `regexp.MustCompile`, Rust `Regex::new`, and their Java, C# and PHP
  equivalents). Route detection still sees them, because Django routes are regexes.

A file whose strings are detection vocabulary (a linter's rules, a scanner's patterns) can
opt out with a `neosloc: ignore` comment in its first five lines.

## 1. Interface

<!-- neosloc:ladder interface -->

Never `n/a`. A frontend alone, or no surface at all, is level 0.

A standard application protocol is a contract in its own right: any off-the-shelf client
can use the server. What it leaves open is the application layer on top (which commands,
topics and payloads), so level 3 asks for that to be specified, in a protocol document or
AsyncAPI. A bare WebSocket only carries custom messages, so it is a surface but not a
contract.

## 2. Contract stability

<!-- neosloc:ladder stability -->

Applies when there is a service, CLI or library. The history check walks tagged releases
and compares OpenAPI operations, CLI long options and Python `__all__` symbols. An item
counts as properly removed only if the release before its removal mentioned it in a
deprecation warning.

## 3. Events

<!-- neosloc:ladder events -->

**n/a** for libraries, frontends and batch CLIs. A CLI is assessed only if it has a
long-running mode. Receiving other platforms' webhooks never counts as publishing events.

## 4. Identity

<!-- neosloc:ladder identity -->

**n/a** for frontends, and for CLIs and libraries that use no credentials.

## 5. Data portability

<!-- neosloc:ladder portability -->

**n/a** for projects that own no persistent data. A tool's *output* format belongs to
Interface (cli level 4).

## 6. Agent ergonomics

<!-- neosloc:ladder ergonomics -->

Applies to services, CLIs and libraries.

## 7. Embeddability

<!-- neosloc:ladder embeddability -->

Applies to services, CLIs and libraries.

## 8. Extensibility

<!-- neosloc:ladder extensibility -->

Applies to every project. "Documented" is checked by matching the docs against the
project's own registration functions (for example a `register` decorator), not by looking
for words like "plugin".

## 9. Observability

<!-- neosloc:ladder observability -->

Applies to services, CLIs and libraries.

## 10. Change legibility

<!-- neosloc:ladder legibility -->

Applies to every project. Size is measured in **tokens per module and per file**, because
what matters is whether a unit of change fits in an agent's working context. A module is
a directory of source files.
