# JSON output

With `--json`, everything neosloc prints on stdout is one JSON document, **including
errors**. Diagnostics stay on stderr. The shapes are specified by a JSON Schema (draft
2020-12) that ships with the package:

```bash
neosloc --schema > neosloc.schema.json
```

## Documents

| Invocation | stdout |
|---|---|
| `neosloc --json PATH` | a **report** |
| `neosloc --json PATH1 PATH2 …` | a list of **reports**, with an **error** in place of each path that couldn't be assessed |
| any failure before reports exist | an **error** |

Every document has `schema_version` (currently `1`). It changes only when a field is
removed or changes meaning; new optional fields are added without a bump.

Validate output in a pipeline:

```bash
neosloc --json . > report.json
neosloc --schema > schema.json
python -m jsonschema --instance report.json schema.json      # or any draft 2020-12 validator
```

## Report

| Field | Content |
|---|---|
| `target` | Absolute path of the repository. |
| `inventory` | `files`, `source_files`, `source_tokens`, `languages` (tokens per language), `git`. |
| `dimensions[]` | `key`, `title`, `level` (0–4), `level_name`, `rationale`, `evidence[]` (`signal`, `detail`, `path`, `weight`), `gaps[]`, `metrics` (detector-specific). |
| `estimate` | `integrability_index`, `retrofit_person_days`, `retrofit_by_dimension`, `wrappability`, `assumptions`. See [Retrofit effort](estimate.md). |
| `value` | neoCOCOMO figures: `classic`, `capture`, `agent_factor`, `history`, `knowledge_at_risk`, `value_pm`, `value_cost`, `assumptions`. See [Value](value.md). |
| `agentic` | With `--agentic`/`--judge`: `runs[]` (one per probe model; per-scope `summary`, per-task records, `documentation_gap`) and `panel`. Otherwise `null`. |
| `review` | With `--review`: per-dimension reviews, `consensus`, `spread`, `reviewed_index`, `disagreements`. Otherwise `null`. |
| `spend` | With any evaluator: `usd`, `max_usd`, `unpriced_calls`. Otherwise `null`. |

Per-task records in `agentic.runs[].tasks[]` carry `outcome` (see
[LLM evaluators](evaluators.md#probe)), the submitted `answer`, the judge's verdict,
`problems`, and turn, token, time and cost counters.

## Errors

```json
{
  "schema_version": 1,
  "target": "/path/that/failed",
  "error": {
    "code": "not_a_directory",
    "message": "not a directory: /path/that/failed",
    "exit_status": 3,
    "details": {"path": "/path/that/failed"}
  }
}
```

`target` is present when the error concerns one path. Branch on `code`, not on `message`:
codes are part of the contract, messages are for humans.

<!-- neosloc:errors -->

Exit statuses: `0` ok · `1` internal error · `2` usage · `3` a path couldn't be assessed ·
`4` LLM evaluator setup · `130` interrupted. With several paths, exit status 3 means at
least one failed; the others still have their reports.

## The schema

Generated from `neosloc/schema.py`; identical to `neosloc --schema`.

<!-- neosloc:schema -->
