"""Surfaces, ladders and the n/a rule, on small fixture repositories."""
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest

from neosloc.assess import assess
from neosloc.cli import analyze
from neosloc.facts import Facts, cycles
from neosloc.ladder import SPECS, detect_surfaces
from neosloc.repo import Repo
from neosloc.specs import openapi_operations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OPENAPI_V1 = textwrap.dedent("""\
    openapi: 3.0.0
    info:
      title: t
      version: 1.0.0
    paths:
      /v1/items:
        get:
          summary: list
        post:
          summary: create
      /v1/items/{id}:
        delete:
          summary: remove
    components: {}
""")

PYPROJECT_CLI = textwrap.dedent("""\
    [project]
    name = "tool"
    version = "1.0.0"
    dependencies = []

    [project.scripts]
    tool = "tool.cli:main"
""")

CLI = textwrap.dedent("""\
    import argparse
    import sys


    def main():
        ap = argparse.ArgumentParser()
        ap.add_argument("path", help="what to read")
        ap.add_argument("--json", action="store_true", help="JSON output")
        args = ap.parse_args()
        if not args.path:
            print("error: no path", file=sys.stderr)
            sys.exit(2)
        print("ok")
""")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(textwrap.dedent(text))

    def git(self, *args):
        subprocess.run(["git", "-C", self.dir, *args], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def commit(self, msg, tag=None):
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)
        if tag:
            self.git("tag", tag)

    def results(self):
        dims, surfaces, _ = assess(Repo(self.dir))
        return {d.key: d for d in dims}, surfaces

    def dim(self, key):
        return self.results()[0][key]

    def surface_level(self, key, surface):
        return self.dim(key).surfaces[surface]["level"]

    def first_missing(self, key, surface):
        return self.dim(key).surfaces[surface]["first_missing"]

    def cli_tool(self):
        self.write("pyproject.toml", PYPROJECT_CLI)
        self.write("tool/__init__.py", "")
        self.write("tool/cli.py", CLI)

    def fastapi_service(self):
        self.write("app/__init__.py", "")
        self.write("app/main.py", """\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/v1/items")
            def items() -> list:
                return []
        """)


# ---------------------------------------------------------------------------


class Surfaces(Fixture):
    def kinds(self):
        return detect_surfaces(Facts(Repo(self.dir))).kinds

    def test_service(self):
        self.fastapi_service()
        self.assertEqual(self.kinds(), ["service"])

    def test_cli_and_library(self):
        self.cli_tool()
        self.assertEqual(self.kinds(), ["cli", "library"])

    def test_entry_point_without_arg_parsing_is_not_a_cli(self):
        self.cli_tool()
        self.write("tool/cli.py", "def main():\n    print('hi')\n")
        self.assertNotIn("cli", self.kinds())

    def test_go_main_only_is_cli_not_library(self):
        self.write("go.mod", "module example.com/x\n")
        self.write("main.go", "// Copyright\npackage main\nimport \"flag\"\nfunc main() { flag.Parse() }\n")
        self.write("internal/run/run.go", "package run\nfunc Run() {}\n")
        self.assertEqual(self.kinds(), ["cli"])

    def test_typed_npm_library(self):
        self.write("package.json", '{"name": "x", "main": "dist/index.js", "types": "dist/index.d.ts"}')
        self.write("src/index.ts", "export const f = (a: number): number => a;\n")
        self.assertEqual(self.kinds(), ["library"])

    def test_frontend_without_a_framework(self):
        self.write("package.json", '{"name": "x", "private": true, "devDependencies": {"browserify": "17"}}')
        self.write("index.html", "<html></html>")
        self.write("src/index.js", "L.map('map')\n")
        self.assertEqual(self.kinds(), ["frontend"])

    def test_web_app_with_main_is_frontend_not_library(self):
        self.write("package.json", '{"name": "x", "main": "src/index.js", "dependencies": {"react": "18"}}')
        self.write("src/index.js", "document.body.innerHTML = '';\n")
        self.write("index.html", "<html></html>")
        self.assertEqual(self.kinds(), ["frontend"])

    def test_properties(self):
        self.cli_tool()
        s = detect_surfaces(Facts(Repo(self.dir)))
        self.assertEqual((bool(s.long_running), bool(s.owns_data), bool(s.uses_credentials)), (False, False, False))
        self.write("tool/watch.py", "import argparse\nap = argparse.ArgumentParser()\nap.add_argument('--watch')\n")
        self.write("tool/store.py", "import sqlite3\ndb = sqlite3.connect('x.db')\n")
        self.write("tool/auth.py", "import os\nKEY = os.environ['TOOL_API_KEY']\n")
        s = detect_surfaces(Facts(Repo(self.dir)))
        self.assertEqual((bool(s.long_running), bool(s.owns_data), bool(s.uses_credentials)), (True, True, True))


class Applicability(Fixture):
    def test_batch_cli_and_library(self):
        self.cli_tool()
        dims, _ = self.results()
        na = sorted(k for k, d in dims.items() if d.level is None)
        self.assertEqual(na, ["events", "identity", "portability"])
        self.assertIn("long-running", dims["events"].rationale)

    def test_nothing_detected(self):
        self.write("notes.txt", "hello")
        dims, surfaces = self.results()
        self.assertEqual(surfaces.kinds, [])
        self.assertEqual(dims["interface"].level, 0)  # never n/a
        self.assertEqual(dims["interface"].best_surface, "none")
        self.assertEqual(dims["legibility"].level, 0)
        self.assertEqual(dims["extensibility"].level, 0)
        for key in ("stability", "events", "identity", "portability", "ergonomics", "embeddability", "observability"):
            self.assertIsNone(dims[key].level, key)

    def test_frontend_only(self):
        self.write("package.json", '{"name": "x", "private": true, "dependencies": {"vue": "3"}}')
        self.write("index.html", "<html></html>")
        self.write("src/main.js", "createApp(App).mount('#app')\n")
        dims, _ = self.results()
        self.assertEqual(dims["interface"].level, 0)
        self.assertEqual(dims["interface"].best_surface, "frontend")
        self.assertIsNone(dims["ergonomics"].level)

    def test_estimate_and_index_skip_na(self):
        self.cli_tool()
        report = analyze(self.dir, with_value=False)
        est = report.estimate
        self.assertEqual(est["assessed_dimensions"], 7)
        self.assertEqual(sorted(est["not_applicable"]), ["events", "identity", "portability"])
        self.assertNotIn("events", est["retrofit_by_dimension"])
        levels = [d.level for d in report.dimensions if d.level is not None]
        self.assertAlmostEqual(est["integrability_index"], round(sum(levels) / 7.0, 2))


class Ladders(Fixture):
    def test_levels_are_cumulative(self):
        """A met higher requirement doesn't count past an unmet lower one."""
        self.cli_tool()
        self.write("tool/schema.py", "SCHEMA = {'$schema': 'https://json-schema.org/draft/2020-12/schema'}\n")
        iface = self.dim("interface").surfaces["cli"]
        met = {r["id"]: r["met"] for r in iface["requirements"]}
        self.assertTrue(met["output-schema"])           # L4 evidence exists...
        self.assertFalse(met["machine-output"])         # ...but exit statuses aren't documented (L3)
        self.assertEqual(iface["level"], 2)
        self.assertEqual(iface["first_missing"], "machine-output")

    def test_best_surface_wins(self):
        self.cli_tool()
        self.write("tool/py.typed", "")
        self.write("tool/__init__.py", "__all__ = ['main']\nfrom .cli import main\n")
        d = self.dim("interface")
        self.assertEqual((d.surfaces["cli"]["level"], d.surfaces["library"]["level"]), (2, 3))
        self.assertEqual((d.level, d.best_surface), (3, "library"))
        self.assertTrue(any(g.startswith("[cli] L3") for g in d.gaps))

    def test_every_spec_has_increasing_ladders(self):
        for spec in SPECS:
            for surface, reqs in spec.ladders.items():
                levels = sorted({r.level for r in reqs})
                self.assertEqual(levels, list(range(1, len(levels) + 1)), (spec.key, surface))
                self.assertEqual(len({r.id for r in reqs}), len(reqs), (spec.key, surface))


class Interface(Fixture):
    def test_service_generated_contract_and_second_surface(self):
        self.fastapi_service()
        self.assertEqual(self.surface_level("interface", "service"), 3)
        self.write("app/mcp.py", "from mcp.server.fastmcp import FastMCP\nm = FastMCP('x')\n")
        self.assertEqual(self.surface_level("interface", "service"), 4)

    def test_mcp_client_is_not_a_surface(self):
        self.fastapi_service()
        self.write("app/mcp.py", "from mcp import ClientSession\n")
        self.assertEqual(self.surface_level("interface", "service"), 3)

    def test_spec_coverage(self):
        self.write("api/openapi.yaml", OPENAPI_V1)
        self.write("server.js", "".join("app.get('/r%d', h)\n" % i for i in range(10)))
        self.assertEqual(self.first_missing("interface", "service"), "coverage")

    def test_cli_ladder(self):
        self.cli_tool()
        self.assertEqual(self.surface_level("interface", "cli"), 2)
        self.write("README.md", "# tool\n\nExit status: 0 ok, 2 usage error, 3 bad path.\n")
        self.assertEqual(self.surface_level("interface", "cli"), 3)
        self.write("tool/schema.py", "S = {'$schema': 'https://json-schema.org/draft/2020-12/schema'}\n")
        self.assertEqual(self.surface_level("interface", "cli"), 4)

    def test_cli_help_coverage(self):
        self.cli_tool()
        self.write("tool/cli.py", CLI.replace('help="JSON output"', "") + "\n".join(
            "    ap.add_argument('--o%d')" % i for i in range(5)) + "\n")
        self.assertEqual(self.first_missing("interface", "cli"), "help")

    def test_prompts_need_a_guard(self):
        self.cli_tool()
        self.write("tool/ask.py", "def ask():\n    return input('Name? ')\n")
        self.assertEqual(self.first_missing("interface", "cli"), "non-interactive")
        self.write("tool/ask.py", "import sys\ndef ask():\n    return input('Name? ') if sys.stdin.isatty() else ''\n")
        self.assertNotEqual(self.first_missing("interface", "cli"), "non-interactive")

    def test_npm_entry_point_delimits_public_api(self):
        self.write("packages/core/package.json", '{"name": "@x/core", "main": "dist/index.js", "types": "dist/index.d.ts"}')
        self.write("packages/core/src/index.ts", "export const f = (a: number): number => a;\n")
        self.assertEqual(self.surface_level("interface", "library"), 3)

    def test_library_ladder(self):
        self.cli_tool()
        self.assertEqual(self.surface_level("interface", "library"), 1)
        self.write("tool/__init__.py", "__all__ = ['main']\n")
        self.assertEqual(self.surface_level("interface", "library"), 2)
        self.write("tool/py.typed", "")
        self.assertEqual(self.surface_level("interface", "library"), 3)
        self.write("docs/conf.py", "extensions = ['sphinx.ext.autodoc']\n")
        self.assertEqual(self.surface_level("interface", "library"), 4)


class ProtocolServers(Fixture):
    """Standard wire protocols are contracts (geomqtt: RESP in, MQTT out)."""

    def server(self, deps, listener=True):
        self.write("Cargo.toml", "[package]\nname = \"srv\"\n\n[dependencies]\n" + "".join('%s = "1"\n' % d for d in deps))
        self.write("src/main.rs", "async fn run() {\n    let l = %s;\n}\n"
                   % ("TcpListener::bind(addr).await?" if listener else "connect(addr).await?"))

    def test_protocols_are_a_contract(self):
        self.server(["redis-protocol", "mqttbytes"])
        d = self.dim("interface")
        self.assertEqual(self.results()[1].kinds, ["service"])
        self.assertEqual(d.surfaces["service"]["first_missing"], "coverage")  # L2 met, app layer unspecified
        self.assertIn("isn't specified", next(r["note"] for r in d.surfaces["service"]["requirements"] if r["id"] == "coverage"))

    def test_specified_application_layer_and_second_transport(self):
        self.server(["redis-protocol", "mqttbytes"])
        self.write("PROTOCOL.md", "# Protocol\n\nTopics: geo/<set>/<z>/<x>/<y>, JSON payloads with an op field.\n")
        self.assertEqual(self.surface_level("interface", "service"), 4)  # RESP + MQTT are two transports

    def test_single_protocol_needs_a_second_surface(self):
        self.server(["redis-protocol"])
        self.write("PROTOCOL.md", "# Protocol\n")
        self.assertEqual(self.surface_level("interface", "service"), 3)

    def test_client_libraries_are_not_servers(self):
        self.server(["fred", "rumqttc"], listener=False)
        self.assertNotIn("service", self.results()[1].kinds)

    def test_codec_without_listener_is_not_a_server(self):
        self.server(["redis-protocol"], listener=False)
        self.assertNotIn("service", self.results()[1].kinds)

    def test_bare_websocket_is_a_surface_not_a_contract(self):
        self.write("src/main.rs", "fn run() { let ws = tokio_tungstenite::accept_async(stream); }\n")
        self.write("Cargo.toml", "[package]\nname = \"srv\"\n")
        self.assertEqual(self.surface_level("interface", "service"), 1)

    def test_benchmarks_are_not_product_code(self):
        self.write("bench/__main__.py", "import argparse\nap = argparse.ArgumentParser()\n")
        self.assertEqual(Repo(self.dir).source_files(include_tests=False), [])


class Stability(Fixture):
    def setUp(self):
        super().setUp()
        self.cli_tool()
        self.git("init", "-q")

    def test_ladder(self):
        self.commit("one", "v1.0.0")
        self.assertEqual(self.dim("stability").level, 1)
        self.write("CHANGELOG.md", "# Changelog\n\n## 1.1.0\n\n- **Breaking:** renamed --out.\n")
        self.assertEqual(self.dim("stability").level, 2)
        self.write("tool/old.py", "import warnings\nwarnings.warn('use --format', DeprecationWarning)\n")
        self.commit("two", "v1.1.0")
        self.assertEqual(self.dim("stability").level, 4)  # two tags, nothing removed

    def test_removed_option_without_deprecation(self):
        self.write("CHANGELOG.md", "## 1.0.0\n\n- breaking: none yet\n")
        self.write("tool/old.py", "import warnings\nwarnings.warn('x', DeprecationWarning)\n")
        self.write("tool/cli.py", CLI.replace('ap.add_argument("--json"', 'ap.add_argument("--legacy", help="x")\n'
                                                                         '        ap.add_argument("--json"'))
        self.commit("one", "v1.0.0")
        self.write("tool/cli.py", CLI)
        self.commit("drop --legacy", "v2.0.0")
        d = self.dim("stability")
        self.assertEqual(d.level, 3)
        note = next(r["note"] for r in d.surfaces["all"]["requirements"] if r["id"] == "clean-history")
        self.assertIn("option --legacy", note)

    def test_removed_operation(self):
        self.write("api/openapi.yaml", OPENAPI_V1)
        self.commit("one", "v1.0.0")
        self.write("api/openapi.yaml", OPENAPI_V1.replace("    delete:\n      summary: remove\n", "    get:\n      summary: x\n"))
        self.commit("two", "v1.1.0")
        note = next(r["note"] for r in self.dim("stability").surfaces["all"]["requirements"] if r["id"] == "clean-history")
        self.assertIn("op DELETE /v1/items/{id}", note)


class Events(Fixture):
    def test_inbound_webhooks_only(self):
        self.fastapi_service()
        self.write("app/hooks.py", "def stripe_webhook(request):\n    return verify(request)\n")
        self.assertEqual(self.dim("events").level, 0)

    def test_outbound_and_stream_is_three(self):
        self.fastapi_service()
        self.write("app/hooks.py", "def deliver_webhook(sub):\n    post(sub.url)\n")
        self.write("app/stream.py", "from sse_starlette import EventSourceResponse\n")
        self.assertEqual(self.dim("events").level, 3)
        self.write("asyncapi.yaml", "asyncapi: 2.6.0\n")
        self.assertEqual(self.dim("events").level, 4)

    def test_long_running_cli(self):
        self.cli_tool()
        self.write("tool/cli.py", CLI.replace('help="JSON output")', 'help="JSON output")\n        ap.add_argument("--watch", help="w")\n'
                                              '        ap.add_argument("--jsonl", help="NDJSON events")'))
        d = self.dim("events")
        self.assertEqual(list(d.surfaces), ["cli"])
        self.assertEqual(d.surfaces["cli"]["level"], 2)


class Identity(Fixture):
    def test_cli_credentials(self):
        self.cli_tool()
        self.write("tool/auth.py", "import os\nKEY = os.environ.get('TOOL_API_KEY')\n")
        self.write("tool/cli.py", CLI.replace('help="JSON output")', 'help="JSON output")\n        ap.add_argument("--token", help="t")'))
        self.assertEqual(self.surface_level("identity", "cli"), 1)
        self.assertEqual(self.first_missing("identity", "cli"), "credentials-off-cli")
        self.write("tool/cli.py", CLI)
        self.write("README.md", "Set TOOL_API_KEY.\n")
        self.assertEqual(self.surface_level("identity", "cli"), 3)

    def test_logging_a_secret(self):
        self.cli_tool()
        self.write("tool/auth.py", "import os\napi_key = os.environ.get('TOOL_API_KEY')\nprint('using', api_key)\n")
        self.write("README.md", "Set TOOL_API_KEY.\n")
        self.assertEqual(self.first_missing("identity", "cli"), "secrets-not-logged")

    def test_service(self):
        self.fastapi_service()
        self.write("app/auth.py", "from fastapi.security import HTTPBearer\nimport authlib\nSecurity(dep, scopes=['r'])\n")
        self.assertEqual(self.dim("identity").level, 3)


class Portability(Fixture):
    def test_ladder(self):
        self.fastapi_service()
        self.assertIsNone(self.dim("portability").level)
        self.write("app/migrations/0001_initial.py", "x = 1\n")
        self.write("app/models.py", "from django.db import models\nclass Item(models.Model):\n    pass\n")
        self.assertEqual(self.dim("portability").level, 1)
        self.write("app/export.py", "import csv\ndef export_items(out):\n    csv.writer(out)\n\ndef import_items(f):\n    pass\n")
        self.assertEqual(self.dim("portability").level, 3)

    def test_json_dumps_is_not_an_export(self):
        self.fastapi_service()
        self.write("app/migrations/0001_initial.py", "x = 1\n")
        self.write("app/serial.py", "import json\nclass M:\n    def dump(self):\n        return json.dumps(self.__dict__)\n")
        self.assertEqual(self.dim("portability").level, 1)


class Ergonomics(Fixture):
    def test_cli_ladder(self):
        self.cli_tool()
        self.write("tool/cli.py", CLI.replace('print("error: no path", file=sys.stderr)', 'print("error: no path")'))
        self.assertEqual(self.surface_level("ergonomics", "cli"), 1)  # errors on stdout
        self.write("tool/cli.py", CLI)
        self.assertEqual(self.surface_level("ergonomics", "cli"), 2)
        self.write("README.md", "Exit status: 0 ok, 2 usage, 3 path.\n")
        self.write("tool/errors.py", "def doc(e):\n    return {'error': {'code': e}}\n")
        self.assertEqual(self.surface_level("ergonomics", "cli"), 3)

    def test_library_must_not_exit(self):
        self.cli_tool()
        self.write("tool/core.py", "import sys\nclass ToolError(Exception):\n    pass\ndef f():\n    sys.exit(1)\n")
        self.assertEqual(self.first_missing("ergonomics", "library"), "typed-exceptions")
        self.write("tool/core.py", "class ToolError(Exception):\n    pass\ndef f(x):\n    raise ValueError('x must be positive')\n")
        self.assertEqual(self.surface_level("ergonomics", "library"), 2)


class ServiceErgonomics(Fixture):
    def test_framework_json_errors(self):
        self.fastapi_service()
        self.assertEqual(self.surface_level("ergonomics", "service"), 1)


class Embeddability(Fixture):
    def test_cli_ladder(self):
        self.cli_tool()
        self.assertEqual(self.surface_level("embeddability", "cli"), 2)
        self.write(".github/workflows/release.yml", "steps:\n  - uses: pypa/gh-action-pypi-publish@release/v1\n")
        self.write(".github/workflows/ci.yml", "steps:\n  - run: tool --json .\n")
        self.assertEqual(self.surface_level("embeddability", "cli"), 3)
        self.write("Dockerfile", "FROM python:3.12\n")
        self.assertEqual(self.surface_level("embeddability", "cli"), 4)

    def test_service_ladder(self):
        self.fastapi_service()
        self.write("README.md", "Run:\n\n```\nuvicorn app.main:app\n```\n")
        self.write("app/settings.py", "import os\nDB = os.environ['DB']\n")
        self.write(".env.example", "DB=x\n")
        self.write("Dockerfile", "FROM python\n")
        self.assertEqual(self.surface_level("embeddability", "service"), 3)


class Extensibility(Fixture):
    def test_ladder(self):
        self.cli_tool()
        self.assertEqual(self.dim("extensibility").level, 0)
        self.write("tool/registry.py", "RULES = []\n\ndef register(rule):\n    RULES.append(rule)\n    return rule\n")
        self.assertEqual(self.dim("extensibility").level, 1)
        self.write("docs/extending.md", "Decorate your rule with `@register(...)`.\n")
        self.assertEqual(self.dim("extensibility").level, 2)
        self.write("tool/plugins.py", "from importlib import metadata\nfor ep in metadata.entry_points(group='tool.rules'):\n    ep.load()\n")
        self.assertEqual(self.dim("extensibility").level, 3)

    def test_method_named_entry_points_is_not_discovery(self):
        self.write("tool/x.py", "def run(f):\n    return f.entry_points()\n")
        self.assertNotIn("out-of-tree", [r["id"] for r in self.dim("extensibility").surfaces["all"]["requirements"] if r["met"]])


class Observability(Fixture):
    def test_service(self):
        self.fastapi_service()
        self.write("app/ops.py", "@app.get('/healthz')\ndef h(): pass\nimport structlog\nfrom prometheus_client import Counter\n"
                   "from opentelemetry import trace\n")
        self.assertEqual(self.dim("observability").level, 4)

    def test_cli(self):
        self.cli_tool()
        self.write("tool/log.py", "import logging\nlog = logging.getLogger(__name__)\n")
        self.assertEqual(self.surface_level("observability", "cli"), 1)
        self.write("tool/cli.py", CLI.replace('help="JSON output")', 'help="JSON output")\n        ap.add_argument("-q", "--quiet", help="q")\n'
                                              '        ap.add_argument("--log-format", help="text or json")'))
        self.assertEqual(self.surface_level("observability", "cli"), 3)

    def test_library_must_not_print(self):
        self.cli_tool()
        self.write("tool/core.py", "import logging\nlog = logging.getLogger(__name__)\ndef f():\n    print('x')\n")
        self.assertEqual(self.first_missing("observability", "library"), "standard-logger")


class Legibility(Fixture):
    def test_lockfile_exemption(self):
        self.cli_tool()  # zero dependencies and a library: exempt
        self.write("README.md", "# x\n")
        self.write("tests/test_x.py", "def test_x():\n    assert True\n")
        self.write(".github/workflows/ci.yml", "x: 1\n")
        self.assertGreaterEqual(self.dim("legibility").level, 2)

    def test_service_needs_lockfile(self):
        self.fastapi_service()
        self.write("pyproject.toml", '[project]\nname = "svc"\ndependencies = ["fastapi"]\n')
        self.write("README.md", "# x\n")
        self.write("tests/test_x.py", "def test_x():\n    assert True\n")
        self.write(".github/workflows/ci.yml", "x: 1\n")
        self.assertEqual(self.first_missing("legibility", "all"), "ci-pinned")
        self.write("uv.lock", "")
        self.assertNotEqual(self.first_missing("legibility", "all"), "ci-pinned")

    def test_import_cycle_and_lazy_import(self):
        self.write("app/a.py", "from app import b\n")
        self.write("app/b.py", "from app import a\n")
        self.write("app/__init__.py", "")
        self.assertEqual(Facts(Repo(self.dir)).legibility()["import_cycles"], 1)
        self.write("app/b.py", "def f():\n    from app import a\n")
        self.assertEqual(Facts(Repo(self.dir)).legibility()["import_cycles"], 0)


class Helpers(unittest.TestCase):
    def test_cycles(self):
        self.assertEqual(cycles({("a", "b"), ("b", "a"), ("b", "c")}), [["a", "b"]])
        self.assertEqual(cycles({("a", "b"), ("b", "c")}), [])

    def test_openapi_parsing(self):
        self.assertEqual(openapi_operations(OPENAPI_V1, "api.yaml"),
                         {"GET /v1/items", "POST /v1/items", "DELETE /v1/items/{id}"})
        doc = {"openapi": "3.1.0", "paths": {"/a": {"get": {}, "parameters": []}}}
        self.assertEqual(openapi_operations(json.dumps(doc), "api.json"), {"GET /a"})
        self.assertIsNone(openapi_operations("{nope", "api.json"))


class Classification(Fixture):
    def test_generated_examples_vendored_excluded(self):
        self.write("app/main.py", "x = 1\n")
        self.write("static/bundle.js", "var a=1;" * 5000)
        self.write("lib/gen.go", "// Code generated by protoc. DO NOT EDIT.\npackage x\n")
        self.write("examples/demo.py", "print(1)\n")
        self.write("web/libs/leaflet.js", "x = 1\n")
        self.write("app/specs/models.py", "y = 2\n")
        self.assertEqual(sorted(Repo(self.dir).source_files(include_tests=False)), ["app/main.py", "app/specs/models.py"])


class Value(Fixture):
    def test_value_model(self):
        self.git("init", "-q")
        self.write("app/core.py", "\n".join("x%d = %d  # c" % (i, i) for i in range(500)) + "\n# only comment\n")
        self.commit("initial")
        with open(os.path.join(self.dir, "app/core.py"), "a") as fh:
            fh.write("y = 1\n")
        self.commit("fix crash on empty input")
        v = analyze(self.dir).value
        self.assertAlmostEqual(v["ksloc"], 0.501, places=2)
        self.assertEqual((v["history"]["commits"], v["history"]["fix_commits"]), (2, 1))
        self.assertEqual(v["capture"]["capture"], 0.0)
        self.assertEqual(v["agent_factor"], 0.55)
        self.assertAlmostEqual(v["knowledge_pm"], 0.03, places=2)

    def test_tests_and_docs_reduce_reproduction_cost(self):
        self.write("app/core.py", "def f(a: int) -> int:\n    return a\n" * 50)
        bare = analyze(self.dir).value["agent_factor"]
        self.write("tests/test_core.py", "def test_f() -> None:\n    assert f(1) == 1\n" * 50)
        self.write("README.md", "# Core\n" + "Explains f in detail.\n" * 200)
        self.assertLess(analyze(self.dir).value["agent_factor"], bare)


class SelfScan(unittest.TestCase):
    """neosloc on itself: the properties the criteria were revised for."""

    @classmethod
    def setUpClass(cls):
        dims, cls.surfaces, _ = assess(Repo(ROOT))
        cls.d = {d.key: d for d in dims}

    def test_surfaces(self):
        self.assertEqual(self.surfaces.kinds, ["cli", "library"])

    def test_batch_cli_dimensions_are_na(self):
        self.assertIsNone(self.d["events"].level)
        self.assertIsNone(self.d["portability"].level)

    def test_cli_qualities_count(self):
        self.assertEqual(self.d["interface"].surfaces["cli"]["level"], 4)       # --json + exit statuses + schema
        self.assertGreaterEqual(self.d["ergonomics"].surfaces["cli"]["level"], 3)
        self.assertGreaterEqual(self.d["observability"].surfaces["cli"]["level"], 3)

    def test_known_gaps_are_reported(self):
        self.assertEqual(self.d["identity"].surfaces["cli"]["first_missing"], "credentials-off-cli")  # --auth-header
        self.assertEqual(self.d["extensibility"].level, 2)  # documented, but in-tree only

    def test_own_vocabulary_is_not_evidence(self):
        for key in ("stability", "extensibility"):
            for res in self.d[key].surfaces.values():
                for r in res["requirements"]:
                    for e in r["evidence"]:
                        self.assertNotIn(e["path"], ("neosloc/facts.py", "neosloc/criteria.py", "neosloc/specs.py"),
                                         (key, r["id"]))


if __name__ == "__main__":
    unittest.main()
