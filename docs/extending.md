# Writing detectors

## Layout

```text
neosloc/
  repo.py            file inventory, cached reads, git, classification (test/example/vendored/generated)
  specs.py           OpenAPI/AsyncAPI/GraphQL/proto discovery and parsing (no YAML dependency)
  detectors/
    base.py          register(), the Context dict, the DIMENSIONS registry
    signals.py       Signal tables and score_signals()
    interface.py …   one module per dimension
  estimate.py        retrofit effort
  value.py           neoCOCOMO
  agentic/           llm.py (providers), loop.py, runner.py (probe), judge.py, review.py,
                     workspace.py (agent tools), grader.py, tasks.py
  report.py, cli.py
```

## The detector contract

A detector is a function `(repo, ctx) -> DimensionResult`, registered with a decorator:

```python
from ..model import DimensionResult
from .base import Context, register
from .signals import Signal, level_from, score_signals

SIGNALS = [
    Signal("feature-flags", "code+deps", r"\b(unleash|launchdarkly|flipt|growthbook)\b", 1.0,
           "Use a feature-flag service so integrations can be rolled out safely."),
]
WHY = {0: "…", 1: "…", 2: "…", 3: "…", 4: "…"}


@register("rollout", "Rollout control")
def detect(repo, ctx: Context) -> DimensionResult:
    score, ev, found, gaps = score_signals(repo, ctx, SIGNALS)
    level = level_from(score, (0.5, 1.5, 2.5, 3.5))
    return DimensionResult("rollout", "Rollout control", level, WHY[level], ev,
                           metrics={"score": score, "signals": sorted(found)}, gaps=gaps)
```

Then import the module in `detectors/__init__.py`. Import order is report order. `interface`
runs first because it puts `specs`, `route_files`, `route_total` and `has_surface` into
`ctx` for later detectors.

## Signals

`Signal(name, where, pattern, points, gap=None, group=None)`:

| `where` | Searches |
|---|---|
| `code` | product source only |
| `deps` | dependency manifests (transitive Go deps removed) |
| `code+deps` | both |
| `config` | YAML/TOML/JSON/INI/Dockerfiles outside tests |
| `docs` | Markdown/reST/text and `docs/` trees |
| `path` | file *paths*, not contents |
| `routes` | files that declare HTTP routes |

Signals in the same `group` score once (for example, problem+json *or* a generic error
envelope). Gaps are reported only for signals that are missing and whose group wasn't
otherwise satisfied.

## Rules

- **Every level needs evidence with a path**, and every missing point should produce a gap
  phrased as an action.
- **Trust library names only in `deps`.** Matching them in code picks up string literals,
  including neosloc's own patterns when it scans itself.
- **Add a regression test for every false positive you fix.** `tests/test_neosloc.py` builds
  small fixture repositories in temporary directories.
- **Check against real repositories** before changing thresholds. `neosloc --review` with a
  couple of models is a quick way to find disagreements.

## Tests

```bash
python -m unittest discover -s tests -t .
```

LLM code is tested without network access: a scripted fake client for Anthropic, a local
mock of the Messages API for the real SDK (skipped when the SDK isn't installed), and a
local mock of OpenRouter. Never call real model APIs from tests.
