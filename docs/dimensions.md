# Dimensions

Each dimension is scored 0–4:

| Level | Name | Meaning |
|---|---|---|
| 0 | absent | Not possible without changing the code. |
| 1 | ad hoc | Possible, but undocumented, internal or fragile. |
| 2 | partial | Available, with notable gaps. |
| 3 | solid | What a careful integrator would expect. Retrofit estimates target this level. |
| 4 | exemplary | Designed for machines and agents, beyond the norm. |

Detectors only read **product code**: tests, examples, docs, fixtures, vendored code
(`vendor/`, `third_party/`, `libs/`, …) and generated or minified files are excluded.
Library names are trusted only when they appear in dependency manifests, and transitive
dependencies (`// indirect` in `go.mod`) are ignored.

Content signals match the **code view** of each file, not its raw text. Text that talks
*about* a practice isn't evidence of it, so the code view removes:

- comments and docstrings;
- strings that read like English sentences (messages, help texts, prompts). Identifiers,
  headers, paths, MIME types and SQL stay;
- the contents of regex literals: Python raw strings and `re.*` arguments, JS `/…/`
  literals and `RegExp(…)`, Go `regexp.MustCompile`, Rust `Regex::new`, Java, C# and PHP
  equivalents. The delimiters stay, and route detection still sees regex contents,
  because Django routes are regexes.

A file whose strings are detection vocabulary (a linter's rules, a scanner's patterns) can
opt out of content signals entirely with a `neosloc: ignore` comment in its first five
lines. neosloc uses it on its own detector modules.

## Interface surface (`interface`)

*Is there a machine-readable contract, how much of the implemented surface does it cover,
and how many ways in are there?*

- **Contracts:** checked-in OpenAPI/Swagger (parsed, operations counted), AsyncAPI, GraphQL
  SDL, protobuf services; or a framework that generates one from code (FastAPI,
  django-ninja, drf-spectacular, springdoc, NestJS swagger, utoipa, …). A statically typed
  library API (`.d.ts`/TypeScript, `py.typed`, Go or Rust library crates) also counts as
  a contract the compiler checks.
- **Routes:** declarations counted for 13 framework idioms (FastAPI/Flask, Django, DRF,
  Express/Koa/Hono, NestJS, Next.js route handlers, Spring/JAX-RS, Rails, Laravel, Slim,
  Go net/http and routers, axum/actix, ASP.NET).
- **Coverage:** spec operations ÷ detected routes.
- **Other surfaces:** an MCP *server* (not a client), a CLI with JSON output, an SDK
  directory, a typed library.

Level 3 needs a contract that tracks the implementation; level 4 also needs a second surface.

## Contract stability (`stability`)

*Can integrators rely on the surface not moving under them?*

Semver tags, a changelog, release automation, versioned API paths (in route declarations
or the spec, not in outbound client calls), deprecation markers, and the **history of each
OpenAPI file**: neosloc walks up to 60 revisions and flags operations removed without
deprecation. Real behaviour outweighs declared policy.

## Events (`events`)

*Can other systems react to changes without polling?*

Webhooks this system **sends** count fully; webhooks it only receives from other platforms
count for little, because consuming events isn't publishing them. Signatures and
registration endpoints only count when outbound webhooks exist. Level 4 requires an
AsyncAPI or CloudEvents contract.

<!-- neosloc:signals events -->

## Identity (`identity`)

*Can a machine act with its own narrowly scoped, revocable identity?* Capped at level 1
when there is no programmatic surface.

<!-- neosloc:signals identity -->

## Data portability (`portability`)

*Can all the data get out and in, in bulk, in open formats, with an explicit schema?* Data
outlives code: once code is cheap to replace, trapped data is the expensive part. Without
an export, the level is capped at 2.

<!-- neosloc:signals portability -->

## Agent ergonomics (`ergonomics`)

*Given a surface exists, how forgiving is it for an automated caller?* Level 0 when there is
no programmatic surface.

<!-- neosloc:signals ergonomics -->

## Embeddability (`embeddability`)

*Can another system run, configure and compose it without a human?* Container image,
compose/Helm/Kubernetes/Terraform, env templates and config schemas, environment reads in
code, a command-line entry point (console scripts, npm `bin`, Go `main`, Cargo binaries,
Make/just tasks), and library packaging.

## Extensibility (`extensibility`)

*Can behaviour be added without forking?*

<!-- neosloc:signals extensibility -->

## Observability (`observability`)

*Can an operator, or an orchestrating agent, tell whether it is working and why not?*

<!-- neosloc:signals observability -->

## Change legibility (`legibility`)

*How much context does a change need, and how safe is it?* This is where SLOC went: size is
still measured, but in **tokens per module and per file**, because what matters is whether
a unit of change fits in an agent's working context.

| Signal | Points | Notes |
|---|---|---|
| Modules within 32k tokens, no file over 12k | 1 (0.5 if ≥70% of modules fit) | Oversized files are listed as gaps. |
| Test/source token ratio | 1 if ≥ 0.3, 0.5 if ≥ 0.1 | Tests are what make agent edits safe. |
| CI configuration | 0.5 | GitHub Actions, GitLab, CircleCI, Jenkins, … |
| Typed share | 1 if ≥ 70%, 0.5 if ≥ 30% | Statically typed languages, plus annotated Python functions. |
| Lockfile | 0.5 | uv, poetry, npm/yarn/pnpm, Cargo, go.sum, … |
| No import cycles | 0.5 | File-level graph for Python and JS/TS; lazy and `TYPE_CHECKING` imports ignored. |
| README / agent docs | 0.25 each | `AGENTS.md`, `CLAUDE.md`, `llms.txt`, Copilot instructions, … |

The level is the total × 0.9, rounded.
