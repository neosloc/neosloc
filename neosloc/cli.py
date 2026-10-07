"""Command-line entry point: `neosloc [options] PATH...`.

Reports go to stdout (text, or JSON with --json); diagnostics go to stderr
through the `neosloc` logger. With --json every outcome, including errors, is
a JSON document on stdout that validates against `neosloc --schema`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

from . import __version__
from .assess import assess, dimension_keys, surfaces_summary
from .errors import (EXIT_INTERRUPTED, EXIT_OK, EXIT_PATH, InternalError, NeoslocError, PathError,
                     UsageError)
from .estimate import estimate
from .log import LEVELS, configure, logger
from .model import Report
from .repo import Repo
from .report import to_text
from .schema import SCHEMA_VERSION, dumps as schema_dumps
from .makebuy import DEFAULT_MODEL as MAKE_MODEL, make_or_buy
from .value import SLOCCOUNT_OVERHEAD, SLOCCOUNT_SALARY, value


def analyze(path: str, only: Optional[List[str]] = None, salary: float = SLOCCOUNT_SALARY,
            overhead: float = SLOCCOUNT_OVERHEAD, with_value: bool = True, buy_price: float = 0.0,
            horizon: float = 3.0, make_model: Optional[str] = None) -> Report:
    started = time.time()
    try:
        repo = Repo(path)
    except (NotADirectoryError, FileNotFoundError):
        raise PathError("not_a_directory", "not a directory: %s" % path, {"path": path})
    logger.debug("inventory: %d files", len(repo.files), extra={"files": len(repo.files), "git": repo.is_git})
    results, surfaces, facts = assess(repo, only)
    leg = facts.legibility()
    inventory = {
        "files": len(repo.files),
        "source_files": leg["source_files"],
        "source_tokens": leg["source_tokens"],
        "languages": leg["languages"],
        "git": repo.is_git,
    }
    report = Report(repo.root, inventory, results, estimate(results, leg["source_tokens"]), [])
    report.surfaces = surfaces_summary(surfaces)
    if with_value:
        report.value = value(repo, results, salary, overhead)
        report.make_or_buy = make_or_buy(results, leg, report.value, report.estimate, buy_price, horizon,
                                         make_model or MAKE_MODEL)
    logger.debug("assessed %s in %.2fs", repo.root, time.time() - started,
                 extra={"target": repo.root, "seconds": round(time.time() - started, 3)})
    return report


def _specs(value: Optional[str], default: str) -> List[str]:
    return [v.strip() for v in (value or default).split(",") if v.strip()]


def run_evaluators(path: str, report: Report, args) -> None:
    """Attach LLM evaluations (probe, judge, review) to a static report."""
    from .agentic import DEFAULT_EFFORT, DEFAULT_MODEL, Budget, Judge, Probe, make_backend, panel, select
    from .agentic.review import review_all
    from .facts import Facts

    repo = Repo(path)
    effort = args.effort or DEFAULT_EFFORT
    budget = Budget(args.max_cost)
    backends = {}

    def backend(spec):
        if spec not in backends:
            backends[spec] = make_backend(spec, effort, fallbacks=not args.no_fallbacks)
        return backends[spec]

    if args.agentic or args.judge:
        try:
            tasks = select(args.tasks.split(",") if args.tasks else None)
        except ValueError as e:
            raise UsageError("unknown_task", str(e), {"tasks": args.tasks})
        headers = {}
        for h in args.auth_header:
            k, _, v = h.partition(":")
            headers[k.strip()] = v.strip()
        routes = Facts(repo).route_files()
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


class _Parser(argparse.ArgumentParser):
    """argparse that raises UsageError instead of printing and exiting."""

    def error(self, message):
        raise UsageError("usage", message, {"usage": self.format_usage().strip()})


def build_parser() -> argparse.ArgumentParser:
    ap = _Parser(
        prog="neosloc",
        description="Integrability evaluation for software repositories.",
        epilog="Exit status: 0 ok, 1 internal error, 2 usage error, 3 a path could not be assessed, "
               "4 LLM evaluator setup error (credentials, provider, model, SDK), 130 interrupted. "
               "With --json, errors are JSON on stdout too; `neosloc --schema` describes every shape.")
    ap.add_argument("paths", nargs="*", help="repository directories to assess")
    out = ap.add_argument_group("output")
    out.add_argument("--json", action="store_true", help="emit JSON (reports and errors) instead of text")
    out.add_argument("--schema", action="store_true", help="print the JSON Schema of --json output and exit")
    out.add_argument("-v", "--verbose", action="store_true", help="show all evidence in the text report")
    out.add_argument("--only", help="comma-separated dimension keys to run (%s)" % ", ".join(dimension_keys()))
    out.add_argument("--salary", type=float, default=SLOCCOUNT_SALARY,
                     help="annual salary for cost figures (default: sloccount's %(default)s)")
    out.add_argument("--overhead", type=float, default=SLOCCOUNT_OVERHEAD,
                     help="overhead multiplier on salary (default: %(default)s)")
    out.add_argument("--buy-price", type=float, default=0.0, metavar="USD",
                     help="price per year of buying/adopting the product, for make-or-buy (default: 0)")
    out.add_argument("--horizon", type=float, default=3.0, metavar="YEARS",
                     help="make-or-buy horizon in years (default: %(default)s)")
    out.add_argument("--make-model", default=None, metavar="MODEL",
                     help="model whose prices cost the 'make' tokens (default: %s)" % MAKE_MODEL)
    out.add_argument("--version", action="version", version="neosloc " + __version__)
    lg = ap.add_argument_group("diagnostics (stderr)")
    lg.add_argument("--log-level", choices=list(LEVELS), default=None,
                    help="debug: detector timings; info (default): evaluator progress; warning; error. "
                         "Also NEOSLOC_LOG_LEVEL.")
    lg.add_argument("-q", "--quiet", action="store_true", help="only errors on stderr (same as --log-level error)")
    lg.add_argument("--log-format", choices=["text", "json"], default="text",
                    help="text (default) or one JSON object per line")
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
    return ap


def _error_doc(err: NeoslocError, target: Optional[str] = None) -> Dict[str, Any]:
    doc: Dict[str, Any] = {"schema_version": SCHEMA_VERSION, "error": err.to_dict()}
    if target is not None:
        doc["target"] = target
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    want_json = "--json" in argv
    try:
        return _main(argv)
    except NeoslocError as e:
        err = e
    except KeyboardInterrupt:
        err = NeoslocError("interrupted", "interrupted")
        err.exit_status = EXIT_INTERRUPTED
    except Exception as e:  # a bug: report it in the same shape, with the traceback at debug level
        logger.debug("internal error", exc_info=True)
        err = InternalError("internal", "%s: %s" % (type(e).__name__, e), {"type": type(e).__name__})
    if want_json:
        target = err.details.get("path") if isinstance(err, PathError) else None
        print(json.dumps(_error_doc(err, target), indent=2))
    if not logger.handlers:  # failed before logging was configured
        configure("error")
    logger.error(err.message, extra={"code": err.code, "exit_status": err.exit_status})
    return err.exit_status


def _main(argv: List[str]) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    level = "error" if args.quiet else (args.log_level or os.environ.get("NEOSLOC_LOG_LEVEL", "info").lower())
    if level not in LEVELS:
        raise UsageError("usage", "NEOSLOC_LOG_LEVEL must be one of %s" % ", ".join(LEVELS))
    configure(level, args.log_format)

    if args.schema:
        print(schema_dumps())
        return EXIT_OK
    if not args.paths:
        raise UsageError("usage", "the following arguments are required: paths", {"usage": ap.format_usage().strip()})
    only = [k.strip() for k in args.only.split(",")] if args.only else None
    if only:
        unknown = [k for k in only if k not in dimension_keys()]
        if unknown:
            raise UsageError("unknown_dimension", "unknown dimension(s): %s" % ", ".join(unknown),
                             {"unknown": unknown, "known": dimension_keys()})
    evaluating = args.agentic or args.judge or args.review
    if evaluating and len(args.paths) > 1:
        raise UsageError("usage", "--agentic/--judge/--review take a single path")

    results: List[Any] = []   # Report or (path, PathError)
    for p in args.paths:
        try:
            report = analyze(p, only, args.salary, args.overhead, buy_price=args.buy_price,
                             horizon=args.horizon, make_model=args.make_model)
        except PathError as e:
            if len(args.paths) == 1:
                raise
            logger.error(e.message, extra={"code": e.code, "target": p})
            results.append((p, e))
            continue
        if evaluating:
            run_evaluators(p, report, args)
        results.append(report)

    failed = [r for r in results if isinstance(r, tuple)]
    if args.json:
        docs = [_error_doc(r[1], r[0]) if isinstance(r, tuple) else r.to_dict() for r in results]
        print(json.dumps(docs[0] if len(docs) == 1 else docs, indent=2))
    else:
        texts = [to_text(r, args.verbose) for r in results if not isinstance(r, tuple)]
        if texts:
            print(("\n\n" + "=" * 72 + "\n\n").join(texts))
    return EXIT_PATH if failed else EXIT_OK
