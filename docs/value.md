# Value: neoCOCOMO

sloccount priced software with COCOMO: the effort to write it by hand. That figure is still
printed for comparison, but it no longer measures value, because an agent can re-type the
code for a fraction of it. What stays expensive is what an agent *can't* regenerate from
the repository: behaviour that is written down nowhere except in the code, and the
history of fixes that shaped it.

neoCOCOMO follows the accounting **cost approach** (replacement cost new, less
obsolescence), with replacement priced for the agent era.

## The model

```text
classic     = 2.4 × KSLOC^1.05                        COCOMO 81 organic (person-months)
capture     = 0.5·tests + 0.25·contract + 0.25·docs   share of behaviour pinned down outside the code, 0..1
reproduce   = classic × (0.10 + 0.45 × (1 − capture))  agent-era rewrite effort
knowledge   = 0.025 PM × fix commits + 0.005 PM × other commits
rediscover  = knowledge × (1 − capture)               lessons that live only in code and history
replacement = reproduce + rediscover
value       = replacement × leverage × obsolescence
```

| Term | Definition |
|---|---|
| KSLOC | Physical source lines of product code (non-blank, not comment-only), like sloccount. |
| tests | test/source token ratio ÷ 0.5, capped at 1. |
| contract | interface level ÷ 4. |
| docs | doc tokens ÷ source tokens ÷ 0.2, capped at 1. |
| floor (0.10) | Even perfectly specified code needs review, integration and verification. |
| rediscover share (0.5) | Re-deriving undocumented behaviour costs up to half the original effort. |
| fix commit (0.025 PM) | About half a day to find, understand and fix a defect. Fixes are recognised from commit subjects (fix, bug, hotfix, regression, crash, revert, …). |
| other commit (0.005 PM) | About 0.1 day of decision-making behind an ordinary change. |
| leverage | 0.75 + 0.125 × integrability index (0.75–1.25): integrable systems can be put to use by others. |
| obsolescence | staleness (1.0 if the last commit is ≤ 12 months old, 0.85 if ≤ 36, else 0.7) × (0.85 + 0.05 × legibility). |

Money uses sloccount's defaults ($56,286 salary, 2.4 overhead) so the two figures are
comparable. Set your own with `--salary` and `--overhead`.

## Reading it

```text
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

Two things the model makes visible:

- **Tests, contracts and docs make code cheap to replace, but they are where much of its
  value lives.** A well-captured project has a low agent factor: the artifacts carry the
  behaviour, so the code itself is the replaceable part.
- **Knowledge at risk** is the share of replacement cost found only in code and history.
  It is the bus-factor number SLOC never showed. A small frontend with 1 KSLOC but 421
  commits from 50 authors can carry 70% of its replacement cost in knowledge nobody wrote
  down.

## Caveats

This is a cost-approach estimate, not a market valuation: it ignores revenue, users and
network effects. All coefficients are in `neosloc/value.py` and are uncalibrated.
