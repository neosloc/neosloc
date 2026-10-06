"""Command-line entry point: `neosloc [--json] [-v] PATH...`."""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import __version__
from .detectors import DIMENSIONS
from .estimate import estimate
from .model import Report
from .repo import Repo, estimate_tokens
from .value import SLOCCOUNT_OVERHEAD, SLOCCOUNT_SALARY, value
from .report import to_text


def analyze(path: str, only: Optional[List[str]] = None, salary: float = SLOCCOUNT_SALARY,
            overhead: float = SLOCCOUNT_OVERHEAD, with_value: bool = True) -> Report:
    repo = Repo(path)
    ctx: dict = {}
    results, skipped = [], []
    for key, title, fn in DIMENSIONS:
        if only and key not in only:
            continue
        if fn is None:
            skipped.append(key)
            continue
        results.append(fn(repo, ctx))

    leg = next((d for d in results if d.key == "legibility"), None)
    langs = leg.metrics.get("languages", {}) if leg else {}
    src_tokens = ctx.get("source_tokens")
    if src_tokens is None:  # legibility wasn't run (--only)
        src_tokens = sum(estimate_tokens(repo.read(f)) for f in repo.source_files(include_tests=False))
    inventory = {
        "files": len(repo.files),
        "source_files": len(repo.source_files(include_tests=False)),
        "source_tokens": src_tokens,
        "languages": langs,
        "git": repo.is_git,
    }
    report = Report(repo.root, inventory, results, estimate(results, src_tokens), skipped)
    if with_value:
        report.value = value(repo, results, salary, overhead)
    return report


def _specs(value: Optional[str], default: str) -> List[str]:
    return [v.strip() for v in (value or default).split(",") if v.strip()]


def run_evaluators(path: str, report: Report, args) -> None:
    """Attach LLM evaluations (probe, judge, review) to a static report."""
    from .agentic import DEFAULT_EFFORT, DEFAULT_MODEL, Budget, Judge, Probe, make_backend, panel, select
    from .agentic.review import review_all
    from .detectors.interface import _count_routes

    repo = Repo(path)
    effort = args.effort or DEFAULT_EFFORT
    budget = Budget(args.max_cost)
    backends = {}

    def backend(spec):
        if spec not in backends:
            try:
                backends[spec] = make_backend(spec, effort, fallbacks=not args.no_fallbacks)
            except ValueError as e:
                raise SystemExit("neosloc: %s" % e)
        return backends[spec]

    if args.agentic or args.judge:
        try:
            tasks = select(args.tasks.split(",") if args.tasks else None)
        except ValueError as e:
            raise SystemExit("neosloc: %s" % e)
        headers = {}
        for h in args.auth_header:
            k, _, v = h.partition(":")
            headers[k.strip()] = v.strip()
        routes = sorted({f for hits in _count_routes(repo).values() for f in hits})
        probe_specs = _specs(args.probe_model, DEFAULT_MODEL)
        judge = None
        if args.judge:
            judge = Judge(repo, backend(args.judge_model or probe_specs[0]), budget)
        scopes = ["docs", "source"] if args.scope == "both" else [args.scope]
        runs = []
        for spec in probe_specs:
            probe = Probe(repo, backend(spec), budget=budget, max_turns=args.max_turns, route_files=routes,
                          base_url=args.base_url, allow_writes=args.allow_writes, auth_headers=headers,
                          judge=judge, transcripts=args.transcripts)
            runs.append(probe.run(tasks, scopes))
        report.agentic = {"runs": runs, "panel": panel(runs)}

    if args.review:
        report.review = review_all(repo, report.dimensions,
                                   [backend(s) for s in _specs(args.review_model, DEFAULT_MODEL)], budget)
    report.spend = {"usd": round(budget.spent, 4), "max_usd": budget.max_usd,
                    "unpriced_calls": budget.unpriced_calls}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="neosloc",
        description="Integrability evaluation for software repositories.")
    ap.add_argument("paths", nargs="+", help="repository directories to assess")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    ap.add_argument("-v", "--verbose", action="store_true", help="show all evidence")
    ap.add_argument("--only", help="comma-separated dimension keys to run")
    ap.add_argument("--salary", type=float, default=SLOCCOUNT_SALARY,
                    help="annual salary for cost figures (default: sloccount's %(default)s)")
    ap.add_argument("--overhead", type=float, default=SLOCCOUNT_OVERHEAD,
                    help="overhead multiplier on salary (default: %(default)s)")
    ap.add_argument("--version", action="version", version="neosloc " + __version__)
    ag = ap.add_argument_group(
        "LLM evaluators (call model APIs and cost money)",
        "Models are written provider:model, e.g. anthropic:claude-opus-5-5 or "
        "openrouter:google/gemini-3.8-flash; a comma-separated list runs a panel. "
        "Anthropic needs ANTHROPIC_API_KEY and the [agentic] extra; OpenRouter needs OPENROUTER_API_KEY.")
    ag.add_argument("--agentic", action="store_true",
                    help="probe: have a model attempt the standard integration tasks and grade the answers")
    ag.add_argument("--judge", action="store_true",
                    help="judge: have a model check each grounded probe answer against the source (implies --agentic)")
    ag.add_argument("--review", action="store_true",
                    help="review: have a model audit each static dimension level against the code")
    ag.add_argument("--scope", choices=["docs", "source", "both"], default="docs",
                    help="what the agent may read (default: %(default)s; 'both' measures the documentation gap)")
    ag.add_argument("--tasks", help="comma-separated task keys (default: all)")
    ag.add_argument("--probe-model", "--model", dest="probe_model", default=None,
                    help="probe model(s) (default: anthropic:claude-opus-5-5)")
    ag.add_argument("--judge-model", default=None, help="judge model (default: the first probe model)")
    ag.add_argument("--review-model", default=None,
                    help="review model(s) (default: anthropic:claude-opus-5-5)")
    ag.add_argument("--effort", default=None, choices=["low", "medium", "high", "xhigh", "max"],
                    help="effort level (default: medium)")
    ag.add_argument("--max-turns", type=int, default=25, help="per task (default: %(default)s)")
    ag.add_argument("--max-cost", type=float, default=5.0,
                    help="shared budget for all model calls in USD; no new task or review starts "
                         "once it is spent (default: %(default)s)")
    ag.add_argument("--base-url", help="probe a running instance over HTTP")
    ag.add_argument("--allow-writes", action="store_true",
                    help="permit POST/PUT/PATCH/DELETE against --base-url")
    ag.add_argument("--auth-header", action="append", default=[],
                    help="'Name: value' header added to every live request (repeatable)")
    ag.add_argument("--no-fallbacks", action="store_true",
                    help="don't let the API retry refused requests on a fallback model")
    ag.add_argument("--transcripts", help="directory to save per-task transcripts")
    args = ap.parse_args(argv)

    only = args.only.split(",") if args.only else None
    evaluating = args.agentic or args.judge or args.review
    if evaluating and len(args.paths) > 1:
        ap.error("--agentic/--judge/--review take a single path")
    reports = []
    status = 0
    for p in args.paths:
        try:
            report = analyze(p, only, args.salary, args.overhead)
            if evaluating:
                run_evaluators(p, report, args)
            reports.append(report)
        except NotADirectoryError:
            print("neosloc: not a directory: %s" % p, file=sys.stderr)
            status = 2

    if args.json:
        import json
        payload = [r.to_dict() for r in reports]
        print(json.dumps(payload[0] if len(payload) == 1 else payload, indent=2))
    else:
        print(("\n\n" + "=" * 72 + "\n\n").join(to_text(r, args.verbose) for r in reports))
    return status
