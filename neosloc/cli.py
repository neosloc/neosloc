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
from .report import to_text


def analyze(path: str, only: Optional[List[str]] = None) -> Report:
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
    return Report(repo.root, inventory, results, estimate(results, src_tokens), skipped)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="neosloc",
        description="Integrability evaluation for software repositories.")
    ap.add_argument("paths", nargs="+", help="repository directories to assess")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    ap.add_argument("-v", "--verbose", action="store_true", help="show all evidence")
    ap.add_argument("--only", help="comma-separated dimension keys to run")
    ap.add_argument("--version", action="version", version="neosloc " + __version__)
    args = ap.parse_args(argv)

    only = args.only.split(",") if args.only else None
    reports = []
    status = 0
    for p in args.paths:
        try:
            reports.append(analyze(p, only))
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
