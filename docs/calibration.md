# Calibration and limits

## Nothing is calibrated yet

Every threshold and coefficient is an informed guess, kept as a named constant with its
reasoning next to it:

| Where | What |
|---|---|
| `detectors/*.py` | signal points and level thresholds |
| `detectors/legibility.py` | module (32k) and file (12k) token budgets, test and type ratios |
| `estimate.py` | person-days per level, size and legibility factors, wrappability bands |
| `value.py` | agent floor, rediscovery share, person-months per fix and per change, capture weights, leverage, obsolescence |
| `agentic/runner.py` | success-rate → level bands |

Treat the numbers as **rankings**, not measurements, until they are calibrated.

## How to calibrate

1. **Detectors vs reviewers.** Run `neosloc --review --json` with two or three reviewer
   models from different vendors over a varied set of repositories. Collect the
   `disagreements`, read the reviewers' `false_positives` and `missed_evidence`, then fix
   the detector or move a threshold. Add a regression test for each fix.
2. **Static vs measured.** Run `neosloc --agentic --scope both` on the same set. Compare each
   task's outcome with the static level of the dimension it probes. A level-3 interface
   where the probe fails `list` and `create` from the docs means the detector rewards
   something that doesn't help integrators.
3. **Retrofit estimate.** Record the actual effort of real retrofits (adding an API, an
   MCP server, a container) and fit `BASE_DAYS_PER_LEVEL` and the multipliers.
4. **Value.** Compare against known rewrite costs or valuations of real projects to fit the
   agent floor, the rediscovery share and the per-commit knowledge.

## Known limits

- Route counting is regex-based per framework idiom: good for orders of magnitude, not exact.
- YAML OpenAPI is parsed by indentation (no YAML dependency); `$ref`'d path files are not followed.
- The import graph covers Python and JS/TS only.
- Tokens are estimated at 4 characters per token.
- Content signals are regexes over the code view. Identifier-like strings that only name a
  practice (a label `"websocket"`, a header list) still match. Files made of such
  vocabulary can opt out with a `neosloc: ignore` comment.
- The code view understands Python fully (via `tokenize`). Other languages use a
  lightweight scanner: unusual syntax (JS regex/division edge cases, heredocs) can slip
  through.
- The grader checks that what the agent names exists. It does not check that the steps
  achieve the task, unless `--judge` or live mode is used.
- Fix commits are recognised from commit subjects, so squash-merged or terse histories
  under-count knowledge.
