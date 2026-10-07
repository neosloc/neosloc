"""JSON Schema of `neosloc --json` output (`neosloc --schema` prints it).

The schema is strict: objects with a fixed shape forbid unknown properties, so
a change to the output that isn't reflected here fails the tests. Only
per-detector `metrics` are open. `schema_version` changes when a field is
removed or changes meaning; adding optional fields doesn't change it.
"""
from __future__ import annotations

import json
from typing import Any, Dict

SCHEMA_VERSION = 1
SCHEMA_ID = "https://ingmmo.com/neosloc/schema/report-v%d.json" % SCHEMA_VERSION

LEVEL = {"type": "integer", "minimum": 0, "maximum": 4}
NUM = {"type": "number"}
INT = {"type": "integer", "minimum": 0}
STR = {"type": "string"}
NULLABLE_NUM = {"type": ["number", "null"]}
DIMENSION_KEYS = ["interface", "stability", "events", "identity", "portability", "ergonomics",
                  "embeddability", "extensibility", "observability", "legibility"]
TASK_OUTCOMES = ["solved", "ungrounded", "judged_wrong", "infeasible", "unverifiable", "no_submit",
                 "turn_limit", "refusal", "budget", "error", "submitted"]
ERROR_CODES = {
    "usage": "The command line is invalid (exit 2).",
    "unknown_dimension": "--only names a dimension that doesn't exist (exit 2).",
    "unknown_task": "--tasks names a task that doesn't exist (exit 2).",
    "bad_model_spec": "A model isn't written provider:model (exit 2).",
    "not_a_directory": "A path doesn't exist or isn't a directory (exit 3).",
    "missing_dependency": "An evaluator needs a package that isn't installed (exit 4).",
    "credentials": "API credentials are missing or were rejected (exit 4).",
    "provider_unreachable": "The model provider couldn't be reached (exit 4).",
    "unknown_model": "The provider has no such model (exit 4).",
    "model_unsupported": "The model can't call tools (exit 4).",
    "interrupted": "Interrupted by the user (exit 130).",
    "internal": "A bug in neosloc (exit 1); please report it with the details.",
}


def _obj(props: Dict[str, Any], required=None, open_=False) -> Dict[str, Any]:
    return {"type": "object", "properties": props,
            "required": list(props) if required is None else required,
            "additionalProperties": open_}


EVIDENCE = _obj({
    "signal": dict(STR, description="What was observed, e.g. `routes:django`, `container-image`."),
    "detail": STR,
    "path": {"type": ["string", "null"], "description": "Repository-relative file that shows it."},
    "weight": INT,
})

DIMENSION = _obj({
    "key": {"enum": DIMENSION_KEYS},
    "title": STR,
    "level": LEVEL,
    "level_name": {"enum": ["absent", "ad hoc", "partial", "solid", "exemplary"]},
    "rationale": STR,
    "evidence": {"type": "array", "items": {"$ref": "#/$defs/evidence"}},
    "gaps": {"type": "array", "items": STR, "description": "Missing practices, phrased as actions."},
    "metrics": {"type": "object", "description": "Detector-specific measurements (open-ended)."},
})

ESTIMATE = _obj({
    "integrability_index": dict(NUM, minimum=0, maximum=4, description="Mean level of assessed dimensions."),
    "retrofit_person_days": dict(NUM, minimum=0),
    "retrofit_by_dimension": {"type": "object", "additionalProperties": NUM},
    "wrappability": {"enum": ["already integrable", "cheap to wrap", "moderate retrofit", "expensive retrofit",
                              "replace or wrap externally"]},
    "assumptions": _obj({"target_level": LEVEL, "size_factor": NUM, "legibility_multiplier": NUM,
                         "reference_tokens": INT}),
})

VALUE = _obj({
    "ksloc": NUM,
    "classic": _obj({"person_months": NUM, "schedule_months": NUM, "cost": NUM}),
    "capture": _obj({"tests": NUM, "contract": NUM, "docs": NUM, "capture": NUM}),
    "agent_factor": NUM,
    "reproduce_pm": NUM,
    "history": _obj({"commits": INT, "fix_commits": INT, "authors": INT, "age_months": NUM,
                     "months_since_last": NULLABLE_NUM}),
    "knowledge_pm": NUM,
    "rediscover_pm": NUM,
    "replacement_pm": NUM,
    "leverage": NUM,
    "obsolescence": NUM,
    "value_pm": NUM,
    "value_cost": NUM,
    "knowledge_at_risk": dict(NUM, minimum=0, maximum=1),
    "assumptions": _obj({"salary": NUM, "overhead": NUM, "cost_per_pm": NUM, "floor": NUM,
                         "rediscover_share": NUM, "fix_pm": NUM, "change_pm": NUM}),
})

USAGE_FIELDS = {"input_tokens": INT, "output_tokens": INT, "cache_read_input_tokens": INT,
                "cache_creation_input_tokens": INT}

TASK = _obj(dict({
    "task": STR, "dimension": {"enum": DIMENSION_KEYS}, "scope": {"enum": ["docs", "source"]},
    "model": STR, "outcome": {"enum": TASK_OUTCOMES}, "success": {"type": "boolean"},
    "turns": INT, "tool_calls": INT, "tool_errors": INT,
    "problems": {"type": "array", "items": STR},
    "cost_usd": NULLABLE_NUM,
    "answer": {"type": ["object", "null"], "description": "What the probe submitted (submit_result input)."},
    "grounded_steps": INT, "checked_steps": INT,
    "judge": {"type": ["object", "null"], "description": "The judge's verdict: works, reason, issues, model."},
    "seconds": NUM, "http_calls": INT,
}, **USAGE_FIELDS), required=["task", "dimension", "scope", "model", "outcome", "success", "turns",
                              "tool_calls", "tool_errors", "problems", "cost_usd"] + list(USAGE_FIELDS))

SCOPE_SUMMARY = _obj({
    "tasks": INT, "succeeded": INT, "success_rate": dict(NUM, minimum=0, maximum=1), "level": LEVEL,
    "tokens": INT, "tokens_per_success": {"type": ["integer", "null"]}, "cost_usd": NULLABLE_NUM,
    "by_dimension": {"type": "object", "additionalProperties": {"type": "boolean"}},
})

RUN = _obj({
    "model": STR, "effort": {"type": ["string", "null"]}, "judge": {"type": ["string", "null"]},
    "scopes": {"type": "array", "items": {"enum": ["docs", "source"]}},
    "summary": {"type": "object", "additionalProperties": {"$ref": "#/$defs/scope_summary"}},
    "tasks": {"type": "array", "items": {"$ref": "#/$defs/task"}},
    "documentation_gap": dict(NUM, description="Source success rate minus docs success rate (--scope both)."),
}, required=["model", "effort", "judge", "scopes", "summary", "tasks"])

AGENTIC = _obj({
    "runs": {"type": "array", "items": {"$ref": "#/$defs/run"}},
    "panel": {"oneOf": [{"type": "null"}, _obj({
        "models": {"type": "array", "items": STR},
        "success_share": {"type": "object", "additionalProperties": NUM},
        "agreement": NULLABLE_NUM})]},
})

REVIEW = _obj({
    "models": {"type": "array", "items": STR},
    "dimensions": {"type": "object", "additionalProperties": _obj({
        "static": LEVEL,
        "reviews": {"type": "array", "items": _obj({
            "level": {"type": ["integer", "null"], "minimum": 0, "maximum": 4},
            "rationale": STR, "false_positives": {"type": "array", "items": STR},
            "missed_evidence": {"type": "array", "items": STR}, "model": STR, "turns": INT,
            "cost_usd": NULLABLE_NUM})},
        "consensus": {"type": ["integer", "null"]},
        "spread": {"type": ["integer", "null"]}})},
    "reviewed_index": NULLABLE_NUM,
    "disagreements": {"type": "array", "items": STR},
})

REPORT = _obj({
    "schema_version": {"const": SCHEMA_VERSION},
    "target": dict(STR, description="Absolute path of the assessed repository."),
    "inventory": _obj({"files": INT, "source_files": INT, "source_tokens": INT,
                       "languages": {"type": "object", "additionalProperties": INT}, "git": {"type": "boolean"}}),
    "dimensions": {"type": "array", "items": {"$ref": "#/$defs/dimension"}},
    "estimate": {"$ref": "#/$defs/estimate"},
    "not_implemented": {"type": "array", "items": STR},
    "value": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/value"}]},
    "agentic": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/agentic"}],
                "description": "Present with --agentic or --judge."},
    "review": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/review"}], "description": "Present with --review."},
    "spend": {"oneOf": [{"type": "null"}, _obj({"usd": NUM, "max_usd": NUM, "unpriced_calls": INT})],
              "description": "Total model spend; present when an LLM evaluator ran."},
})

ERROR = _obj({
    "schema_version": {"const": SCHEMA_VERSION},
    "target": dict(STR, description="The path the error is about, when there is one."),
    "error": _obj({
        "code": {"enum": list(ERROR_CODES)},
        "message": STR,
        "exit_status": {"enum": [1, 2, 3, 4, 130]},
        "details": {"type": "object"},
    }),
}, required=["schema_version", "error"])


def schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "neosloc --json output",
        "description": "One report for one path; a list of reports and errors for several paths; or an error.",
        "oneOf": [
            {"$ref": "#/$defs/report"},
            {"type": "array", "items": {"oneOf": [{"$ref": "#/$defs/report"}, {"$ref": "#/$defs/error"}]}},
            {"$ref": "#/$defs/error"},
        ],
        "$defs": {"report": REPORT, "error": ERROR, "dimension": DIMENSION, "evidence": EVIDENCE,
                  "estimate": ESTIMATE, "value": VALUE, "agentic": AGENTIC, "run": RUN, "task": TASK,
                  "scope_summary": SCOPE_SUMMARY, "review": REVIEW},
    }


def dumps() -> str:
    return json.dumps(schema(), indent=2)
