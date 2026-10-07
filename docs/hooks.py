"""MkDocs hook: render reference material from the code so the docs can't drift.

    <!-- neosloc:signals events -->   the signal table and level texts of a detector
    <!-- neosloc:cli -->              `neosloc --help`
    <!-- neosloc:tasks -->            the agentic task suite
    <!-- neosloc:schema -->           `neosloc --schema`
    <!-- neosloc:errors -->           error codes and exit statuses
"""
import importlib
import io
import os
import re
import sys
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MARK = re.compile(r"<!-- neosloc:(\w+)(?: (\w+))? -->")


def _signals(name):
    mod = importlib.import_module("neosloc.detectors." + name)
    out = ["| Signal | Looks in | Points | Gap reported when missing |", "|---|---|---|---|"]
    for s in mod.SIGNALS:
        out.append("| `%s` | %s | %s%s | %s |" % (s.name, s.where, s.points,
                                                  " (group `%s`)" % s.group if s.group else "", s.gap or ""))
    out += ["", "| Level | Meaning |", "|---|---|"]
    out += ["| %d | %s |" % (k, v) for k, v in mod.WHY.items()]
    return "\n".join(out)


def _cli():
    from neosloc.cli import main
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            main(["--help"])
        except SystemExit:
            pass
    return "```text\n" + buf.getvalue().rstrip() + "\n```"


def _tasks():
    from neosloc.agentic.tasks import TASKS
    rows = ["| Task | Probes | What the agent is asked |", "|---|---|---|"]
    rows += ["| `%s` | %s | %s |" % (t.key, t.dimension, t.prompt) for t in TASKS]
    return "\n".join(rows)


def _schema():
    from neosloc.schema import dumps
    return "```json\n" + dumps() + "\n```"


def _errors():
    from neosloc.schema import ERROR_CODES
    rows = ["| `code` | Meaning |", "|---|---|"]
    rows += ["| `%s` | %s |" % (k, v) for k, v in ERROR_CODES.items()]
    return "\n".join(rows)


def on_page_markdown(markdown, **kwargs):
    # MkDocs resets sys.path after loading hooks, so make the package importable here.
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

    def render(m):
        kind, arg = m.group(1), m.group(2)
        if kind == "signals":
            return _signals(arg)
        if kind == "cli":
            return _cli()
        if kind == "tasks":
            return _tasks()
        if kind == "schema":
            return _schema()
        if kind == "errors":
            return _errors()
        raise ValueError("unknown neosloc marker %r" % kind)
    return MARK.sub(render, markdown)
