"""Text and JSON renderers."""
from __future__ import annotations

import json

from .model import Report

BAR = "■"
EMPTY = "□"


def to_json(report: Report) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=False)


def to_text(report: Report, verbose: bool = False) -> str:
    out = []
    inv = report.inventory
    out.append("neosloc integrability report: %s" % report.target)
    out.append("")
    out.append("Inventory: %d files, %d source files, ~%s source tokens%s"
               % (inv["files"], inv["source_files"], _k(inv["source_tokens"]),
                  ", git history" if inv["git"] else ", no git history"))
    langs = inv.get("languages") or {}
    if langs:
        total = float(sum(langs.values())) or 1.0
        out.append("Languages: " + ", ".join(
            "%s %d%%" % (k, round(100 * v / total)) for k, v in list(langs.items())[:6]))
    out.append("")

    width = max(len(d.title) for d in report.dimensions)
    for d in report.dimensions:
        bar = BAR * d.level + EMPTY * (4 - d.level)
        out.append("%-*s  %s  %d %-9s  %s" % (width, d.title, bar, d.level, d.level_name, d.rationale))
        evidence = d.evidence if verbose else d.evidence[:4]
        for e in evidence:
            where = " (%s)" % e.path if e.path else ""
            detail = ": " + e.detail if e.detail else ""
            out.append("%s    + %s%s%s" % (" " * width, e.signal, detail, where))
        if not verbose and len(d.evidence) > 4:
            out.append("%s    + ... %d more (use -v)" % (" " * width, len(d.evidence) - 4))
        for g in d.gaps:
            out.append("%s    - %s" % (" " * width, g))
        out.append("")

    if report.not_implemented:
        out.append("Not yet assessed: " + ", ".join(report.not_implemented))
        out.append("")

    est = report.estimate
    a = est["assumptions"]
    out.append("Integrability index (0-4, assessed dimensions):  %.2f" % est["integrability_index"])
    out.append("Retrofit effort to level %d (agent-assisted):     %.1f person-days"
               % (a["target_level"], est["retrofit_person_days"]))
    out.append("Wrappability:                                     %s" % est["wrappability"])
    breakdown = ", ".join("%s %.1f" % (k, v) for k, v in est["retrofit_by_dimension"].items() if v)
    if breakdown:
        out.append("  by dimension: " + breakdown)
    out.append("  (size factor %.2f, legibility multiplier %.2f; heuristic, see neosloc/estimate.py)"
               % (a["size_factor"], a["legibility_multiplier"]))
    return "\n".join(out)


def _k(n: int) -> str:
    if n >= 1_000_000:
        return "%.1fM" % (n / 1e6)
    if n >= 1000:
        return "%dk" % round(n / 1000.0)
    return str(n)
