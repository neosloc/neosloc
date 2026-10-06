# neosloc

[![ci](https://github.com/sirmmo/neosloc/actions/workflows/ci.yml/badge.svg)](https://github.com/sirmmo/neosloc/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/neosloc)](https://pypi.org/project/neosloc/)
[![docs](https://img.shields.io/badge/docs-ingmmo.com%2Fneosloc-blue)](https://ingmmo.com/neosloc/)

`sloccount` counted lines of code and fed them to COCOMO to estimate the effort to *build*
software. With LLMs writing code, lines are cheap and that estimate has lost its meaning.
What is still expensive is everything *around* the code: how easily other systems and
agents can call it, run it, rely on it and change it safely, and the knowledge that exists
only in the code and its history.

neosloc measures that:

- **ten integrability dimensions**, each scored 0–4 with the evidence behind the level and
  the gaps phrased as actions;
- the **retrofit effort** to bring every dimension up to "solid", and whether the system
  is cheap to wrap;
- **neoCOCOMO**: what the codebase is worth when an agent can re-type it, next to classic
  COCOMO;
- optional **LLM evaluators** on Anthropic or [OpenRouter](https://openrouter.ai): a
  *probe* attempts real integration tasks using only the docs, a *judge* checks the
  answers against the source, and a *review* audits every static level.

```bash
pip install neosloc
neosloc path/to/repo
```

```text
Interface surface   ■■■□  3 solid      The framework generates a contract from code, so it tracks the implementation.
                      + routes:fastapi/flask: 15 route declarations in 3 files (app/routes/admin.py)
                      + generated-spec: FastAPI (auto OpenAPI) (app/main.py)
                      - Check the generated spec into the repo so changes are reviewable and diffable.
...
Integrability index (0-4, assessed dimensions):  1.80
Retrofit effort to level 3 (agent-assisted):     7.5 person-days

Value (neoCOCOMO, cost approach; see neosloc/value.py)
  Classic COCOMO (sloccount):    4.6 KSLOC -> 11.8 person-months, 6.4 months, $133k
  Behaviour captured:            38% (tests 0.14, contract 0.25, docs 1.00)
  Reproduce with agents:         x0.38 of classic -> 4.5 PM
  Rediscover uncaptured history: 102 fix / 474 commits, 19 authors -> 4.4 PM knowledge, 2.7 PM uncaptured
  Value:                         5.2 PM ~ $59k  (at $11k per PM)
  Knowledge at risk:             38% of replacement cost lives only in code and history
```

**Documentation: <https://ingmmo.com/neosloc/>**

## Install

| | |
|---|---|
| `pip install neosloc` (or `pipx install neosloc`, `uv tool install neosloc`) | the `neosloc` command; the static analysis has **no dependencies** and runs on Python ≥ 3.8 |
| `pip install 'neosloc[agentic]'` | adds the anthropic SDK, needed for `anthropic:` models (Python ≥ 3.10) |
| `pip install git+https://github.com/sirmmo/neosloc` | the development version |

OpenRouter models need no extra package, only `OPENROUTER_API_KEY`.

## Dimensions

| Key | Asks |
|---|---|
| `interface` | Is there a machine-readable contract covering the implemented surface, and more than one way in (MCP, CLI `--json`, SDK, typed library)? |
| `stability` | Semver, changelog, API versioning, deprecations, and the real git history of the OpenAPI files. |
| `events` | Outbound webhooks (signed, self-service), streams, brokers, CDC, AsyncAPI/CloudEvents. |
| `identity` | Token auth, OAuth2/OIDC, scopes, managed API keys or service accounts, SCIM. |
| `portability` | Bulk export/import, open formats, schema in the repo. |
| `ergonomics` | RFC 9457 errors, validation, idempotency keys, pagination, rate-limit headers, dry-run, `llms.txt`. |
| `embeddability` | Container, compose/Helm/IaC, documented env config, headless entry point, library packaging. |
| `extensibility` | Plugin discovery, hooks, scripting, extension docs. |
| `observability` | Health/readiness, metrics, tracing, structured logs, error tracking. |
| `legibility` | The heir to SLOC: tokens per module, import cycles, tests, types, CI, lockfiles, agent docs. |

Details: [dimensions](https://ingmmo.com/neosloc/dimensions/),
[retrofit effort](https://ingmmo.com/neosloc/estimate/),
[neoCOCOMO](https://ingmmo.com/neosloc/value/).

## LLM evaluators

```bash
# Probe: a model attempts 8 integration tasks from the docs; answers are graded against the code
neosloc --agentic --scope both --transcripts runs/ .

# Probe with Claude, judge with another vendor through OpenRouter
neosloc --judge --judge-model openrouter:openai/gpt-5.6-luna .

# Review: a panel audits every static level against the code
neosloc --review --review-model openrouter:google/gemini-3.8-flash,openrouter:deepseek/deepseek-v4-pro-0813 .
```

Models are written `provider:model`. The default is `anthropic:claude-opus-5-5` at effort
`medium`. A comma-separated list runs a panel and reports agreement. Every model call
shares one `--max-cost` budget (default $5), and the report states the total. See
[LLM evaluators](https://ingmmo.com/neosloc/evaluators/) and
[Using OpenRouter](https://ingmmo.com/neosloc/openrouter/).

## Status

All thresholds and coefficients are uncalibrated, so treat the numbers as rankings.
[Calibration and limits](https://ingmmo.com/neosloc/calibration/) describes how to fix
that; `--review` and `--agentic` exist partly to do it.

## Development

```bash
python -m unittest discover -s tests -t .     # no network, no API spend
python -m neosloc .
```

See [Writing detectors](https://ingmmo.com/neosloc/extending/) and `AGENTS.md`.
Releases: bump `neosloc/__init__.py`, add a `CHANGELOG.md` section, push a `vX.Y.Z` tag.

MIT licensed.
