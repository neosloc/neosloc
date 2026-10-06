# Retrofit effort

How much agent-assisted work would bring every dimension up to level 3 ("solid")?

```text
effort = Σ base[d] × (3 − level[d]) × legibility_multiplier × size_factor
```

| Term | Value | Why |
|---|---|---|
| `base[d]` | person-days per level per dimension at ~250k tokens: interface 3, legibility 4, events/identity/portability/extensibility 2, ergonomics 1.5, stability/embeddability/observability 1 | Adding a contract or a safety net touches more than adding a health endpoint. |
| `size_factor` | √(tokens / 250k), clamped to 0.5–4 | Retrofits work at boundaries, so cost grows sub-linearly with size. |
| `legibility_multiplier` | 2.5, 1.6, 1.0, 0.75, 0.5 for legibility 0–4 | Hard-to-change code makes every other fix more expensive. It isn't applied to legibility itself. |

The report also gives **wrappability**:

| Effort | Verdict |
|---|---|
| index already ≥ 3 | already integrable |
| ≤ 5 days | cheap to wrap |
| ≤ 20 days | moderate retrofit |
| ≤ 60 days | expensive retrofit |
| more | replace or wrap externally |

This is the answer that matters most when re-evaluating older applications. A legacy
system with no API but a clean CLI, tests and a readable schema is often cheap to wrap,
and the per-dimension breakdown shows where the days would go.

All values are in `neosloc/estimate.py` and are uncalibrated. See [Calibration](calibration.md).
