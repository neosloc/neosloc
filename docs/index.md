# neosloc

`sloccount` counted lines of code and fed them to COCOMO to estimate the effort to *build*
software. With LLMs writing code, lines are cheap and that estimate has lost its meaning.
What is still expensive is everything *around* the code: how easily other systems and
agents can call it, run it, rely on it and change it safely, and the knowledge that exists
only in the code and its history.

neosloc measures those things.

```bash
pip install neosloc
neosloc path/to/repo
```

## What you get

| Section | Question it answers | Page |
|---|---|---|
| Ten dimensions, levels 0–4 | How integrable is this, and what exactly is missing? | [Dimensions](dimensions.md) |
| Retrofit effort | How much work to make it solidly integrable? | [Retrofit effort](estimate.md) |
| neoCOCOMO value | What is it worth when an agent can re-type it? | [Value](value.md) |
| Probe / judge / review | What happens when a model actually tries to integrate with it? Do models agree with the detectors? | [LLM evaluators](evaluators.md) |

Every level comes with **evidence** (the files that justify it) and **gaps** (what to do
next), so the report can be used as a to-do list, not just a score.

```text
Interface surface   ■■■□  3 solid      The framework generates a contract from code, so it tracks the implementation.
                      + routes:fastapi/flask: 15 route declarations in 3 files (app/routes/admin.py)
                      + generated-spec: FastAPI (auto OpenAPI) (app/main.py)
                      - Check the generated spec into the repo so changes are reviewable and diffable.
Contract stability  ■■□□  2 partial    Releases are versioned; the API itself has limited change management.
...
Integrability index (0-4, assessed dimensions):  1.80
Retrofit effort to level 3 (agent-assisted):     7.5 person-days

Value (neoCOCOMO, cost approach; see neosloc/value.py)
  Classic COCOMO (sloccount):    2.1 KSLOC -> 5.1 person-months, 4.7 months, $58k
  Behaviour captured:            65% (tests 0.42, contract 0.75, docs 1.00)
  ...
  Knowledge at risk:             4% of replacement cost lives only in code and history
```

## Design principles

- **No dependencies for the core.** The static analysis is standard library only and runs
  on Python 3.8+, so it works on old servers and in CI without setup.
- **Evidence over scores.** There is no single headline number. The mean of the levels is
  printed next to them, never instead of them.
- **Deterministic first, models second.** The static report is reproducible. LLM
  evaluators are opt-in, budgeted, and reported separately, so you can see where they
  disagree with the detectors.
- **Everything is a guess until calibrated.** Thresholds and coefficients are module
  constants with their rationale in the code. See [Calibration](calibration.md).
