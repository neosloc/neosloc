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

    surf = report.surfaces or {}
    if surf:
        props = [name for name, key in (("long-running", "long_running"), ("owns data", "owns_data"),
                                         ("uses credentials", "uses_credentials")) if surf.get(key)]
        out.append("Surfaces: %s%s" % (", ".join(surf.get("kinds") or []) or "none detected",
                                       " (%s)" % ", ".join(props) if props else ""))
        out.append("")

    width = max([len(d.title) for d in report.dimensions] or [0])
    for d in report.dimensions:
        if d.level is None:
            out.append("%-*s  %s  %-11s  %s" % (width, d.title, "    ", "n/a", d.rationale))
            out.append("")
            continue
        bar = BAR * d.level + EMPTY * (4 - d.level)
        out.append("%-*s  %s  %d %-9s  %s" % (width, d.title, bar, d.level, d.level_name, d.rationale))
        evidence = d.evidence if verbose else d.evidence[-3:]
        for e in evidence:
            where = " (%s)" % e.path if e.path else ""
            detail = ": " + e.detail if e.detail else ""
            out.append("%s    + %s%s%s" % (" " * width, e.signal, detail, where))
        for g in d.gaps:
            out.append("%s    - next: %s" % (" " * width, g))
        if verbose:
            for name, res in d.surfaces.items():
                out.append("%s    %s ladder (level %d):" % (" " * width, name, res["level"]))
                for r in res["requirements"]:
                    mark = "x" if r["met"] else " "
                    note = "" if r["met"] or not r["note"] else " -- " + r["note"]
                    out.append("%s      [%s] L%d %s%s" % (" " * width, mark, r["level"], r["text"], note))
        out.append("")

    if report.not_implemented:
        out.append("Not yet assessed: " + ", ".join(report.not_implemented))
        out.append("")

    est = report.estimate
    a = est["assumptions"]
    out.append("Integrability index (0-4, %d applicable dimensions):  %.2f"
               % (est.get("assessed_dimensions", len(report.dimensions)), est["integrability_index"]))
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
    if report.make_or_buy:
        out.append("")
        out.extend(_make_buy_lines(report.make_or_buy))
    if report.agentic:
        out.append("")
        out.extend(_agentic_lines(report.agentic, {d.key: d.level for d in report.dimensions}))
    if report.review:
        out.append("")
        out.extend(_review_lines(report.review))
    if report.spend:
        out.append("")
        out.append("Model spend: $%.2f of $%.2f budget%s" % (
            report.spend["usd"], report.spend["max_usd"],
            "; %d call(s) could not be priced" % report.spend["unpriced_calls"]
            if report.spend["unpriced_calls"] else ""))
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


def _usd(x) -> str:
    return "?" if x is None else ("$%.0f" % x if x < 1000 else "$" + _k(int(x)))


def _make_buy_lines(m) -> list:
    mk, by, h = m["make"], m["buy"], m["horizon_years"]
    t = mk["tokens"]
    verdict = {"make": "MAKE: rebuilding with agents is cheaper", "buy": "BUY: adopting this is cheaper",
               "toss-up": "TOSS-UP: within 1.5x either way"}[m["verdict"]]
    be = m["break_even_price_per_year"]
    if be is None:
        be_line = ""
    elif be <= 0:
        be_line = "make wins even if buying is free"
    else:
        be_line = "buying wins below %s/year" % _usd(be)
    return [
        "Make or buy (over %g years; see neosloc/makebuy.py)" % h,
        "  Make with agents:  %s output + %s input tokens (%d%% cached) on %s = %s;"
        % (_k(t["output"]), _k(t["input"]), round(100 * t["cached_input"] / max(t["input"], 1)), mk["model"],
           _usd(mk["model_cost"])),
        "                     %.1f agent-hours, %.1f human days (%.1f steering + %.1f rediscovering history), "
        "~%.1f calendar days" % (mk["agent_hours"], mk["human_days"], mk["review_days"], mk["rediscover_days"],
                                 mk["calendar_days"]),
        "                     build %s, then %s/year to maintain -> %s"
        % (_usd(mk["build_cost"]), _usd(mk["yearly_cost"]), _usd(mk["total_cost"])),
        "  Buy (adopt this):  %.1f integration days, %s/year price, %.1f upgrade days/year -> %s"
        % (by["integration_days"], _usd(by["price_per_year"]), by["upgrade_days_per_year"], _usd(by["total_cost"])),
        "  Verdict:           %s (make/buy = %.2f)%s" % (verdict, m["make_buy_ratio"], "; " + be_line if be_line else ""),
    ]


def _agentic_lines(a, static_levels) -> list:
    out = []
    for run in a["runs"]:
        head = "Agentic probe (%s, effort %s, scope %s%s)" % (
            run["model"], run["effort"], ", ".join(run["scopes"]),
            ", judge " + run["judge"] if run.get("judge") else "")
        out.append(head)
        for scope, s in run["summary"].items():
            cost = "?" if s["cost_usd"] is None else "%.2f" % s["cost_usd"]
            out.append("  %-7s success %d/%d (%d%%), level %d, %s tokens, ~$%s"
                       % (scope, s["succeeded"], s["tasks"], round(100 * s["success_rate"]), s["level"],
                          _k(s["tokens"]), cost))
        for t in run["tasks"]:
            mark = "ok " if t["success"] else "-- "
            static = static_levels.get(t["dimension"], "-")
            out.append("  %s[%s] %-9s %-12s %-26s (%d turns, %d tool calls, %s tok)%s"
                       % (mark, t["scope"], t["task"], t["outcome"],
                          "%s static %s" % (t["dimension"], "n/a" if static is None else static),
                          t["turns"], t["tool_calls"], _k(t["input_tokens"] + t["output_tokens"]),
                          "" if t["success"] else ": " + "; ".join(t["problems"][:2])))
        if "documentation_gap" in run:
            out.append("  Documentation gap: %+d%% success when the agent may read source"
                       % round(100 * run["documentation_gap"]))
        out.append("")
    p = a.get("panel")
    if p:
        out.append("Probe panel (%s): models agree on %d%% of tasks"
                   % (", ".join(p["models"]), round(100 * (p["agreement"] or 0))))
        for cell, share in sorted(p["success_share"].items()):
            out.append("  %-18s %d%% of models succeeded" % (cell, round(100 * share)))
        out.append("")
    return out[:-1] if out and out[-1] == "" else out


def _review_lines(r) -> list:
    out = ["LLM review (%s)" % ", ".join(r["models"])]
    for key, d in r["dimensions"].items():
        levels = ", ".join("-" if x.get("level") is None else str(x["level"]) for x in d["reviews"])
        mark = "  " if d["consensus"] in (None, d["static"]) else "! "
        static = "n/a" if d["static"] is None else str(d["static"])
        first = next((x for x in d["reviews"] if x.get("level") is not None), None)
        why = (first["rationale"][:110] + ("..." if len(first["rationale"]) > 110 else "")) if first else ""
        out.append("  %s%-14s static %s -> reviewed %s  [%s]  %s"
                   % (mark, key, static, "-" if d["consensus"] is None else d["consensus"], levels, why))
    if r.get("reviewed_index") is not None:
        out.append("  Reviewed integrability index: %.2f" % r["reviewed_index"])
    if r["disagreements"]:
        out.append("  Disagreements to calibrate: " + ", ".join(r["disagreements"]))
    return out


def _k(n: int) -> str:
    if n >= 1_000_000:
        return "%.1fM" % (n / 1e6)
    if n >= 1000:
        return "%dk" % round(n / 1000.0)
    return str(n)
