# JSON report

`neosloc --json PATH` prints one report object; with several paths, a list of them. The
format follows the [changelog](changelog.md): breaking changes are called out there.

```json
{
  "target": "/abs/path/to/repo",
  "inventory": {"files": 61, "source_files": 22, "source_tokens": 26412,
                "languages": {"python": 26412}, "git": true},
  "dimensions": [
    {
      "key": "interface", "title": "Interface surface",
      "level": 3, "level_name": "solid",
      "rationale": "The framework generates a contract from code, so it tracks the implementation.",
      "evidence": [{"signal": "generated-spec", "detail": "FastAPI (auto OpenAPI)", "path": "app/main.py", "weight": 2}],
      "gaps": ["Check the generated spec into the repo so changes are reviewable and diffable."],
      "metrics": {"route_declarations": 15, "spec_operations": 0, "spec_coverage": null, "surfaces": 1}
    }
  ],
  "estimate": {
    "integrability_index": 1.8, "retrofit_person_days": 7.5,
    "retrofit_by_dimension": {"interface": 0.0, "stability": 0.4},
    "wrappability": "moderate retrofit",
    "assumptions": {"target_level": 3, "size_factor": 0.5, "legibility_multiplier": 0.75, "reference_tokens": 250000}
  },
  "value": {
    "ksloc": 2.1, "classic": {"person_months": 5.1, "schedule_months": 4.7, "cost": 57616},
    "capture": {"tests": 0.42, "contract": 0.75, "docs": 1.0, "capture": 0.65},
    "agent_factor": 0.26, "reproduce_pm": 1.33, "history": {"commits": 20, "fix_commits": 2, "authors": 1,
    "age_months": 1.2, "months_since_last": 0.3}, "knowledge_pm": 0.14, "rediscover_pm": 0.05,
    "replacement_pm": 1.38, "leverage": 0.97, "obsolescence": 1.0, "value_pm": 1.34, "value_cost": 15081,
    "knowledge_at_risk": 0.04, "assumptions": {"salary": 56286, "overhead": 2.4, "cost_per_pm": 11257}
  },
  "not_implemented": [],
  "agentic": null,
  "review": null,
  "spend": null
}
```

## `agentic`

Present with `--agentic` or `--judge`:

```json
{
  "runs": [{
    "model": "anthropic:claude-opus-5-5", "effort": "medium", "judge": null, "scopes": ["docs"],
    "summary": {"docs": {"tasks": 8, "succeeded": 5, "success_rate": 0.62, "level": 2,
                         "tokens": 412000, "tokens_per_success": 82400, "cost_usd": 1.84,
                         "by_dimension": {"identity": true, "interface": false}}},
    "documentation_gap": 0.25,
    "tasks": [{
      "task": "list", "dimension": "interface", "scope": "docs", "model": "anthropic:claude-opus-5-5",
      "outcome": "ungrounded", "success": false, "problems": ["GET /items/all is not a declared route"],
      "answer": {"feasible": true, "summary": "...", "steps": [], "evidence": [], "confidence": 0.7},
      "grounded_steps": 0, "checked_steps": 1, "judge": null,
      "turns": 7, "tool_calls": 9, "tool_errors": 0, "http_calls": 0, "seconds": 41.2,
      "input_tokens": 3100, "output_tokens": 2200, "cache_read_input_tokens": 41000,
      "cache_creation_input_tokens": 9000, "cost_usd": 0.21
    }]
  }],
  "panel": {"models": ["…", "…"], "agreement": 0.75, "success_share": {"docs/list": 0.5}}
}
```

`documentation_gap` appears only with `--scope both`; `panel` is `null` for a single probe
model; `cost_usd` is `null` when a model's price is unknown.

## `review`

```json
{
  "models": ["openrouter:google/gemini-3.8-flash"],
  "dimensions": {
    "events": {"static": 1, "consensus": 0, "spread": 0, "reviews": [
      {"level": 0, "rationale": "...", "false_positives": ["inbound-webhooks"], "missed_evidence": [],
       "model": "openrouter:google/gemini-3.8-flash", "turns": 4, "cost_usd": 0.004}]}
  },
  "reviewed_index": 1.7,
  "disagreements": ["events"]
}
```

## `spend`

`{"usd": 1.92, "max_usd": 5.0, "unpriced_calls": 0}`: the total across all roles.
