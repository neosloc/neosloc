"""Dimension 5 - Data portability.

Can the data get in and out in bulk, in open formats, with a known schema?
Data outlives code: when the code is cheap to replace, a system whose data is
trapped is the expensive part.
"""
from __future__ import annotations

from ..model import DimensionResult
from .base import Context, register
from .signals import Signal, level_from, score_signals

SIGNALS = [
    Signal("export", "code",
           r"""(def|function|func|fn)\s+\w*(export|dump|backup)\w*\s*\(|['"`]/[\w/{}:<>.-]*\b(export|dump|backup)\b"""
           r"""|add_parser\(\s*['"](export|dump|backup)""",
           1.0, "Provide a bulk export (API endpoint or command) of all user data."),
    Signal("import", "code",
           r"""(def|function|func|fn)\s+\w*(import_|restore|bulk_load)\w*\s*\(|['"`]/[\w/{}:<>.-]*\b(import|restore)\b"""
           r"""|add_parser\(\s*['"](import|restore|load)""",
           0.5, "Provide a bulk import so data can be migrated in."),
    Signal("open-formats", "code",
           r"csv\.writer|DictWriter|to_csv\(|json\.dump|ndjson|jsonl|parquet|pyarrow|geojson|"
           r"icalendar|\.ics\b|vcard|json-ld|rdflib|datapackage|frictionless|xlsx|openpyxl", 0.5),
    Signal("schema-in-repo", "path",
           r"(^|/)(migrations/|alembic/|db/migrate/|prisma/schema\.prisma$|schema\.sql$|"
           r"[\w-]*\.sql$|flyway|liquibase|ent/schema/|models\.py$|models/)", 1.0,
           "Keep the data schema (migrations/DDL) in the repo so the data model is explicit."),
    Signal("bulk-api", "routes", r"""['"`][^'"`]*\b(bulk|batch)\b""", 0.5),
    Signal("documented-export", "docs", r"\bexport(ing)?\b.{0,40}\b(data|csv|json|backup)", 0.5),
]
WHY = {
    0: "Data is only reachable through the UI or the raw database.",
    1: "The data model is visible but there is no supported way to move data.",
    2: "Some import/export exists.",
    3: "Bulk export in open formats with an explicit schema.",
    4: "Round-trip (export and import) in open formats, schema explicit and documented.",
}


@register("portability", "Data portability")
def detect(repo, ctx: Context) -> DimensionResult:
    score, ev, found, gaps = score_signals(repo, ctx, SIGNALS)
    level = level_from(score, (0.5, 1.5, 2.5, 3.5))
    if "export" not in found:
        level = min(level, 2)
    return DimensionResult("portability", "Data portability", level, WHY[level], ev,
                           metrics={"score": round(score, 2), "signals": sorted(found)},
                           gaps=gaps if level < 4 else [])
