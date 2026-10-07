"""MkDocs hook: render reference material from the code so the docs can't drift.

    <!-- neosloc:ladder events -->    a dimension's question and requirement ladders, per surface
    <!-- neosloc:cli -->              `neosloc --help`
    <!-- neosloc:tasks -->            the agentic task suite
    <!-- neosloc:schema -->           `neosloc --schema`
    <!-- neosloc:errors -->           error codes and exit statuses
"""
import io
import os
import re
import sys
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MARK = re.compile(r"<!-- neosloc:(\w+)(?: (\w+))? -->")


def _ladder(key):
    from neosloc.assess import SPECS
    from neosloc.ladder import UNIVERSAL
    spec = next(sp for sp in SPECS if sp.key == key)
    surfaces = [k for k in ("service", "cli", "library", "desktop", "frontend", UNIVERSAL) if k in spec.ladders]
    out = ["*%s*" % spec.question, ""]
    if surfaces == [UNIVERSAL]:
        out += ["| Level | Requirement |", "|---|---|"]
        out += ["| %d | %s |" % (r.level, r.text) for r in sorted(spec.ladders[UNIVERSAL], key=lambda r: r.level)]
        return "\n".join(out)
    out += ["| Level | " + " | ".join(surfaces) + " |", "|---|" + "---|" * len(surfaces)]
    for lvl in range(1, 5):
        cells = []
        for k in surfaces:
            reqs = [r.text for r in spec.ladders[k] if r.level == lvl]
            cells.append(" ".join(reqs) if reqs else "—")
        if any(c != "—" for c in cells):
            out.append("| %d | %s |" % (lvl, " | ".join(cells)))
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
        if kind == "ladder":
            return _ladder(arg)
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


def on_post_build(config, **kwargs):
    """Publish the JSON Schema at its $id, so validators can fetch it by URL."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from neosloc.schema import SCHEMA_ID, dumps
    out = os.path.join(config["site_dir"], "schema", SCHEMA_ID.rsplit("/", 1)[-1])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        fh.write(dumps())
