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
    if report.value:
        out.append("")
        out.extend(_value_lines(report.value))
    if report.agentic:
        out.append("")
        out.extend(_agentic_lines(report.agentic, {d.key: d.level for d in report.dimensions}))
    return "\n".join(out)


def _money(n: float) -> str:
    return "$" + _k(int(n))


def _value_lines(v) -> list:
    c, h, cap = v["classic"], v["history"], v["capture"]
    return [
        "Value (neoCOCOMO, cost approach; see neosloc/value.py)",
        "  Classic COCOMO (sloccount):    %.1f KSLOC -> %.1f person-months, %.1f months, %s"
        % (v["ksloc"], c["person_months"], c["schedule_months"], _money(c["cost"])),
        "  Behaviour captured:            %d%% (tests %.2f, contract %.2f, docs %.2f)"
        % (round(cap["capture"] * 100), cap["tests"], cap["contract"], cap["docs"]),
        "  Reproduce with agents:         x%.2f of classic -> %.1f PM" % (v["agent_factor"], v["reproduce_pm"]),
        "  Rediscover uncaptured history: %d fix / %d commits, %d authors -> %.1f PM knowledge, %.1f PM uncaptured"
        % (h["fix_commits"], h["commits"], h["authors"], v["knowledge_pm"], v["rediscover_pm"]),
        "  Replacement cost new:          %.1f PM" % v["replacement_pm"],
        "  x leverage %.2f (integrability) x obsolescence %.2f (staleness, legibility)"
        % (v["leverage"], v["obsolescence"]),
        "  Value:                         %.1f PM ~ %s  (at %s per PM)"
        % (v["value_pm"], _money(v["value_cost"]), _money(v["assumptions"]["cost_per_pm"])),
        "  Knowledge at risk:             %d%% of replacement cost lives only in code and history"
        % round(v["knowledge_at_risk"] * 100),
    ]


def _agentic_lines(a, static_levels) -> list:
    out = ["Agentic probe (%s, effort %s, scope %s)" % (a["model"], a["effort"], ", ".join(a["scopes"]))]
    for scope, s in a["summary"].items():
        out.append("  %-7s success %d/%d (%d%%), level %d, %s tokens, ~$%.2f"
                   % (scope, s["succeeded"], s["tasks"], round(100 * s["success_rate"]), s["level"],
                      _k(s["tokens"]), s["cost_usd"]))
    for t in a["tasks"]:
        mark = "ok " if t["success"] else "-- "
        static = static_levels.get(t["dimension"])
        out.append("  %s[%s] %-9s %-12s %-26s (%d turns, %d tool calls, %s tok)%s"
                   % (mark, t["scope"], t["task"], t["outcome"],
                      "%s static %s" % (t["dimension"], "-" if static is None else static),
                      t["turns"], t["tool_calls"],
                      _k(t["input_tokens"] + t["output_tokens"]),
                      "" if t["success"] else ": " + "; ".join(t["problems"][:2])))
    if "documentation_gap" in a:
        out.append("  Documentation gap: %+d%% success when the agent may read source"
                   % round(100 * a["documentation_gap"]))
    return out


def _k(n: int) -> str:
    if n >= 1_000_000:
        return "%.1fM" % (n / 1e6)
    if n >= 1000:
        return "%dk" % round(n / 1000.0)
    return str(n)
