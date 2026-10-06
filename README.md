# neosloc

`sloccount` counted lines of code and fed them to COCOMO to estimate the effort to *build*
software. With LLMs writing code, lines are cheap and that estimate has lost its meaning.
What is still expensive is everything *around* the code: how easily other systems and
agents can call it, run it, rely on it and change it safely, and the knowledge that exists
only in the code and its history.

neosloc measures that. Point it at a repository and you get:

- a level (0–4) for each of ten **integrability** dimensions, with the evidence behind
  each level and the gaps phrased as actions;
- the **retrofit effort** to bring every dimension up to "solid";
- a **value** estimate (neoCOCOMO): what the codebase is worth when an agent can re-type it;
- optionally, a measured **agentic probe**: a model attempts standard integration tasks
  using only the docs, and its answers are checked against the implementation.

```
$ python3 -m neosloc /srv/aiproxy
Interface surface   ■■■□  3 solid      The framework generates a contract from code, so it tracks the implementation.
                      + routes:fastapi/flask: 15 route declarations in 3 files (app/routes/admin.py)
                      + generated-spec: FastAPI (auto OpenAPI) (app/main.py)
                      - Check the generated spec into the repo so changes are reviewable and diffable.
...
Integrability index (0-4, assessed dimensions):  1.80
Retrofit effort to level 3 (agent-assisted):     7.5 person-days
```

The static analysis has no dependencies and runs on Python ≥ 3.8:
`python3 -m neosloc PATH... [--json] [-v] [--only KEYS] [--salary N] [--overhead N]`,
or `pip install .` for a `neosloc` command.

## Dimensions

| Key | Dimension | What it asks |
|---|---|---|
| `interface` | Interface surface | Is there a machine-readable contract (OpenAPI, GraphQL, proto, AsyncAPI, or one a framework generates)? How many of the detected routes does it cover? Are there other surfaces (MCP server, CLI `--json`, SDK, typed library API)? |
| `stability` | Contract stability | Semver tags, changelog, API versioning, deprecation markers, and the **actual git history of OpenAPI files**: operations removed between revisions without a deprecation marker first. |
| `events` | Events | Webhooks this system *sends* (signed? registrable via API?), SSE/WebSocket streams, brokers, CDC/outbox, AsyncAPI/CloudEvents. Webhooks it only receives count for little. |
| `identity` | Identity | Token auth, OAuth2/OIDC, scopes and permissions, API keys or service accounts as managed objects, SCIM, SAML, `securitySchemes` in the spec. |
| `portability` | Data portability | Bulk export and import, open formats, schema in the repo (migrations/DDL), bulk APIs, documented export. |
| `ergonomics` | Agent ergonomics | RFC 9457 errors, request validation, idempotency keys, pagination, rate-limit headers, dry-run, ETags, `llms.txt`. |
| `embeddability` | Embeddability | Container image, compose/Helm/IaC, config from env vars (and documented), command-line entry point, library packaging. |
| `extensibility` | Extensibility | Plugin discovery (entry points, pluggy), hooks, plugin directories, scripting, docs on writing extensions. |
| `observability` | Observability | Health/readiness endpoints and probes, metrics, tracing, structured logs, error tracking. |
| `legibility` | Change legibility | The heir to SLOC: size in **tokens per module** (does a unit of change fit in context?), file-level import cycles, test/source ratio, typed share, CI, lockfiles, agent docs (`AGENTS.md`, `CLAUDE.md`, `llms.txt`). |

Levels: 0 absent · 1 ad hoc · 2 partial · 3 solid · 4 exemplary. There is deliberately no
single headline score. The mean ("integrability index") is printed next to the
per-dimension levels, so it can't hide them.

## Retrofit effort

```
effort = Σ base[d] × (3 − level[d]) × legibility_multiplier × size_factor
```

`base[d]` is agent-assisted person-days per level for dimension `d`, on a codebase of
about 250k tokens. `size_factor` is √(tokens / 250k), clamped to 0.5–4. The legibility
multiplier (0.5–2.5) reflects that hard-to-change code makes every other fix more
expensive. The result is also given as *wrappability*, from "cheap to wrap" to "replace or
wrap externally". A legacy system with no API but a clean CLI, tests and a readable schema
is often cheap to wrap, and that is what re-evaluating old applications should show.

## Value: neoCOCOMO

COCOMO priced software as the effort to write it by hand. neoCOCOMO uses the accounting
**cost approach** (replacement cost new, less obsolescence), with replacement priced for
the agent era:

```
classic     = 2.4 × KSLOC^1.05                       COCOMO organic, as sloccount printed it
capture     = 0.5·tests + 0.25·contract + 0.25·docs  share of behaviour pinned down outside the code
reproduce   = classic × (0.10 + 0.45 × (1 − capture)) re-typing is cheap; re-deriving unwritten behaviour isn't
knowledge   = 0.025 PM × fix commits + 0.005 PM × other commits
rediscover  = knowledge × (1 − capture)              lessons that live only in code and history
value       = (reproduce + rediscover) × leverage(integrability) × obsolescence(staleness, legibility)
```

```
Value (neoCOCOMO, cost approach; see neosloc/value.py)
  Classic COCOMO (sloccount):    4.6 KSLOC -> 11.8 person-months, 6.4 months, $133k
  Behaviour captured:            38% (tests 0.14, contract 0.25, docs 1.00)
  Reproduce with agents:         x0.38 of classic -> 4.5 PM
  Rediscover uncaptured history: 102 fix / 474 commits, 19 authors -> 4.4 PM knowledge, 2.7 PM uncaptured
  Replacement cost new:          7.2 PM
  x leverage 0.90 (integrability) x obsolescence 0.81 (staleness, legibility)
  Value:                         5.2 PM ~ $59k  (at $11k per PM)
  Knowledge at risk:             38% of replacement cost lives only in code and history
```

The model makes two claims. Tests, contracts and docs make code cheap to *replace*, but
they are also where much of its value lives. And **knowledge at risk** (the share of
replacement cost found only in code and history) is the bus-factor number that SLOC never
showed. Money uses sloccount's defaults ($56,286 salary, 2.4 overhead) so the two are
comparable; change them with `--salary` and `--overhead`.

## Agentic mode

```
pip install 'neosloc[agentic]'      # anthropic SDK; needs Python >= 3.10
export ANTHROPIC_API_KEY=...
neosloc --agentic --scope both --transcripts runs/ PATH
```

The probe gives `claude-opus-5-5` (effort `medium`; change with `--model` and `--effort`)
what an outside integrator would get, then asks it to do eight standard tasks: `auth`,
`list`, `create`, `subscribe`, `export`, `run`, `errors` and `extend`. Each task maps to a
dimension, so the measured result is printed next to the static level.

- **`--scope docs`** (the default): the agent can read the docs, contracts, manifests,
  deployment files and examples, but not the implementation.
  **`--scope source`** adds the implementation. **`--scope both`** runs both and reports the
  **documentation gap**: how much success depends on reading the code.
- **Grading:** the agent submits structured steps through a strict tool, and the grader
  checks them against the whole repository. HTTP routes must be declared in code or in the
  contract, CLI programs and flags must exist, env vars must be read, and symbols must be
  defined. A task succeeds only when every checkable step is grounded.
- **Live mode:** `--base-url URL` adds an `http_request` tool for a running instance. It is
  read-only unless you pass `--allow-writes`, and `--auth-header 'Authorization: Bearer …'`
  injects credentials. In live mode, HTTP steps also have to be exercised successfully.
- **Cost control:** `--max-cost` (default $5) stops new tasks once that much has been spent,
  and `--max-turns` (default 25) caps each task. A full 8-task, single-scope run is
  typically about 30–80 requests. Prompt caching is on.
- **Refusals:** requests opt into server-side fallbacks (`fallbacks: "default"`), so a
  refused request is retried on a fallback model. Disable this with `--no-fallbacks`.

The success rate per scope maps to a level (≥85% → 4, ≥65% → 3, ≥40% → 2, >0 → 1).

## Known limits

- All coefficients in `estimate.py`, `value.py` and the detector thresholds are
  **uncalibrated**. Calibrating them against real retrofits and valuations is the main
  open work item.
- Route counting is regex-based per framework idiom: good for orders of magnitude, not exact.
- YAML OpenAPI is parsed by indentation (no YAML dependency); `$ref`'d path files are not followed.
- The import graph covers Python and JS/TS only.
- Tokens are estimated at 4 characters per token.
- Content signals are regexes over source text, so string literals can match (neosloc
  scanning itself sees its own patterns as env reads and deprecation markers).
- The agentic grader checks that what the agent names *exists*. It does not check that the
  steps achieve the task, unless live mode exercises them.
