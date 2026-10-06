"""Command-line entry point: `neosloc [--json] [-v] PATH...`."""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import __version__
from .detectors import DIMENSIONS
from .estimate import estimate
from .model import Report
from .repo import Repo
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
    src_tokens = ctx.get("source_tokens", 0)
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


def run_agentic(path: str, args) -> dict:
    from .agentic import DEFAULT_EFFORT, DEFAULT_MODEL, Probe, make_client, select
    from .detectors.interface import _count_routes

    repo = Repo(path)
    try:
        tasks = select(args.tasks.split(",") if args.tasks else None)
    except ValueError as e:
        raise SystemExit("neosloc: %s" % e)
    headers = {}
    for h in args.auth_header:
        k, _, v = h.partition(":")
        headers[k.strip()] = v.strip()
    routes = sorted({f for hits in _count_routes(repo).values() for f in hits})
    probe = Probe(repo, make_client(), model=args.model or DEFAULT_MODEL,
                  effort=args.effort or DEFAULT_EFFORT, max_turns=args.max_turns,
                  max_cost=args.max_cost, route_files=routes, base_url=args.base_url,
                  allow_writes=args.allow_writes, auth_headers=headers,
                  fallbacks=not args.no_fallbacks, transcripts=args.transcripts)
    scopes = ["docs", "source"] if args.scope == "both" else [args.scope]
    return probe.run(tasks, scopes)


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
    ag = ap.add_argument_group("agentic mode (calls the Claude API; costs money)")
    ag.add_argument("--agentic", action="store_true",
                    help="have a model attempt the standard integration tasks and grade the answers")
    ag.add_argument("--scope", choices=["docs", "source", "both"], default="docs",
                    help="what the agent may read (default: %(default)s; 'both' measures the documentation gap)")
    ag.add_argument("--tasks", help="comma-separated task keys (default: all)")
    ag.add_argument("--model", default=None, help="model id (default: claude-opus-5-5)")
    ag.add_argument("--effort", default=None, choices=["low", "medium", "high", "xhigh", "max"],
                    help="effort level (default: medium)")
    ag.add_argument("--max-turns", type=int, default=25, help="per task (default: %(default)s)")
    ag.add_argument("--max-cost", type=float, default=5.0,
                    help="stop starting tasks once this many USD are spent (default: %(default)s)")
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
    if args.agentic and len(args.paths) > 1:
        ap.error("--agentic takes a single path")
    reports = []
    status = 0
    for p in args.paths:
        try:
            report = analyze(p, only, args.salary, args.overhead)
            if args.agentic:
                report.agentic = run_agentic(p, args)
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
