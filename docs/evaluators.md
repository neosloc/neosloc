# LLM evaluators: probe, judge, review

The static detectors infer integrability from proxies. The LLM evaluators measure it
directly, or check the inference. There are three roles, each of which can use any
supported model on either provider:

| Role | Flag | What the model does | What it tells you |
|---|---|---|---|
| **Probe** | `--agentic` | Attempts eight standard integration tasks, with access limited to what an outside integrator gets. | Whether integrating actually works from the docs, and how many turns and tokens it takes. |
| **Judge** | `--judge` | Reads the full source and decides whether each grounded probe answer would actually accomplish its task. | Catches answers that name real things but would not work: wrong method, missing fields or auth, wrong order. |
| **Review** | `--review` | Audits each static dimension level against the detector's evidence and the code, and assigns its own level. | Where the regex detectors are wrong; the input for [calibration](calibration.md). |

!!! warning "These flags call model APIs and cost money"
    All roles share one budget, `--max-cost` (default $5). No new task or review starts
    once it is spent, and the report ends with the total. A full single-scope probe is
    roughly 30–80 model calls; a review is 10 short conversations per reviewer.

## Choosing models

Models are written `provider:model`:

```bash
--probe-model anthropic:claude-opus-5-5                 # the default
--probe-model openrouter:google/gemini-3.8-flash        # any tool-capable OpenRouter model
--judge-model openrouter:openai/gpt-5.6-luna            # default: the first probe model
--review-model anthropic:claude-opus-5-5,openrouter:deepseek/deepseek-v4-pro-0813   # a panel
```

A spec without a prefix is Anthropic if it starts with `claude-` and OpenRouter if it
contains `/`. `--effort` (`low` … `max`, default `medium`) applies to every role; on
OpenRouter it is sent as `reasoning.effort` to models that support it.

| Provider | Needs | Notes |
|---|---|---|
| `anthropic` | `pip install 'neosloc[agentic]'` (Python ≥ 3.10), `ANTHROPIC_API_KEY` | Official SDK. Strict tool schemas, prompt caching, and server-side fallbacks on refusals (`--no-fallbacks` to disable). |
| `openrouter` | `OPENROUTER_API_KEY` only | Standard library HTTP. Tool support is checked against OpenRouter's model list before the run starts; arguments are validated locally. See [Using OpenRouter](openrouter.md). |

## Probe

```bash
neosloc --agentic --scope both --transcripts runs/ path/to/repo
```

The tasks are generic, so success rates are comparable across projects. Each one probes a
dimension, and the report prints the measured outcome next to the static level:

<!-- neosloc:tasks -->

**Scopes.** `--scope docs` (the default) gives the agent the docs, contracts, manifests,
deployment files and examples, but no implementation. `--scope source` gives it everything.
`--scope both` runs both and reports the **documentation gap**: how much success depends on
reading the code.

**Grading.** The agent submits structured steps (http, cli, library or config) through a
submit tool. The grader always sees the whole repository and requires each checkable step
to be **grounded**:

- HTTP: the method and path match the OpenAPI spec or a declared route. Path parameters and
  mount prefixes are normalised, so `/api/v1/items/42` matches `/items/{id}`.
- CLI: the program is provided by the repository (a console script, npm `bin`, file, module,
  docker/compose, or a Make/just target) and every `--flag` appears in the code.
- Library: the symbol is defined in the code.
- Config: every environment variable is read by the code.

| Outcome | Meaning |
|---|---|
| `solved` | Feasible, every checkable step grounded (and, with `--judge`, judged to work). |
| `ungrounded` | Names something that doesn't exist: an invented route, flag or variable. |
| `judged_wrong` | Grounded, but the judge found it would not work. |
| `infeasible` | The agent concluded the system offers no way to do it. |
| `unverifiable` | Only free-text steps; nothing could be checked. |
| `no_submit`, `turn_limit`, `refusal`, `budget`, `error` | The run didn't produce an answer. |

The success rate per scope maps to a level: ≥ 85% → 4, ≥ 65% → 3, ≥ 40% → 2, > 0 → 1.

**Live mode.** `--base-url https://staging.example.com` adds an `http_request` tool. It is
limited to that host and read-only unless you pass `--allow-writes`. `--auth-header
'Authorization: Bearer …'` (repeatable) injects credentials the agent never sees. In live
mode, HTTP steps also have to have been exercised successfully.

**Panels.** A comma-separated `--probe-model` runs every model on the same tasks, and the
report shows how often they agree on each task. Tasks where strong models disagree usually
point to ambiguous documentation.

**Transcripts.** `--transcripts DIR` saves every conversation and its graded result as JSON.

## Judge

```bash
neosloc --judge --judge-model openrouter:openai/gpt-5.6-luna path/to/repo
```

`--judge` implies `--agentic`. The judge only sees answers that passed grounding, so it adds
cost only where the cheap check is already satisfied. Using a different model or provider
from the probe avoids a model grading its own reasoning.

## Review

```bash
neosloc --review --review-model anthropic:claude-opus-5-5,openrouter:google/gemini-3.8-flash .
```

For each dimension, each reviewer receives the question it asks, the meaning of the levels,
the detector's level, rationale, evidence and gaps, and read access to the whole
repository. It returns its own level, a rationale, any detector evidence it considers a
false positive, and evidence the detector missed. The report shows:

```text
LLM review (anthropic:claude-opus-5-5, openrouter:google/gemini-3.8-flash)
    interface      static 3 -> reviewed 3  [3, 3]  FastAPI generates the OpenAPI document ...
  ! events         static 1 -> reviewed 0  [0, 1]  The only webhook code verifies inbound Stripe ...
  Reviewed integrability index: 1.70
  Disagreements to calibrate: events
```

With several reviewers the consensus is the lower median, so a single generous reviewer
can't inflate a level. The JSON includes each reviewer's full answer.
