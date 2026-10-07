# Command line

`neosloc PATH...` assesses one or more repositories. Everything below is generated from
`neosloc --help` when the documentation is built.

<!-- neosloc:cli -->

## Output and diagnostics

- **stdout** carries the result: the text report, or with `--json` one JSON document,
  including errors ([JSON output](json.md)).
- **stderr** carries diagnostics through the `neosloc` logger.

| Level | What you see |
|---|---|
| `error` | Fatal errors. `-q`/`--quiet` shows only these. |
| `warning` | Degraded results, such as a budget exhausted before every task ran. |
| `info` (default) | Progress of LLM evaluators. Static runs print nothing here. |
| `debug` | Per-detector levels and timings, inventory size, total time, tracebacks of internal errors. |

Set the level with `--log-level` or `NEOSLOC_LOG_LEVEL`; `--quiet` wins over both.
`--log-format json` writes one JSON object per line (`ts`, `level`, `logger`, `message`,
plus fields such as `detector`, `seconds`, `code`), which is useful in CI logs.

## Exit status

| Status | Meaning | JSON `error.code` |
|---|---|---|
| `0` | Every path was assessed. | |
| `1` | Internal error, a bug in neosloc. | `internal` |
| `2` | Invalid command line. | `usage`, `unknown_dimension`, `unknown_task`, `bad_model_spec` |
| `3` | At least one path couldn't be assessed; the others are still reported. | `not_a_directory` |
| `4` | LLM evaluator setup failed. | `missing_dependency`, `credentials`, `provider_unreachable`, `unknown_model`, `model_unsupported` |
| `130` | Interrupted. | `interrupted` |

## Examples

```bash
neosloc .                                   # text report for the current repository
neosloc --json ~/src/a ~/src/b > report.json
neosloc --schema > neosloc.schema.json      # the shape of every --json document
neosloc -q --json . | jq '.dimensions[] | {key, level}'
neosloc --log-level debug --log-format json . 2> timings.jsonl
neosloc -v --only interface,stability .     # all evidence, two dimensions
neosloc --salary 90000 --overhead 1.8 .     # value in your own cost terms
neosloc --agentic --scope both --transcripts runs/ .
neosloc --review --review-model openrouter:google/gemini-3.8-flash,openrouter:openai/gpt-5.6-luna .
```
