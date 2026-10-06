import http.server
import json
import os
import shutil
import tempfile
import threading
import unittest
from types import SimpleNamespace as NS

from neosloc.agentic.grader import Grader, normalize_path
from neosloc.agentic.runner import Probe, cost_usd, level_from_rate
from neosloc.agentic.tasks import TASKS, select
from neosloc.agentic.workspace import ToolError, Workspace
from neosloc.repo import Repo


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def service(root):
    write(root, "README.md", "# Items\nRun `itemctl serve --port 8000`. Set ITEMS_DB.\n")
    write(root, "pyproject.toml", '[project]\nname = "items"\n[project.scripts]\nitemctl = "items.cli:main"\n')
    write(root, "items/__init__.py", "")
    write(root, "items/api.py",
          "import os\nfrom fastapi import FastAPI\napp = FastAPI()\nDB = os.environ['ITEMS_DB']\n\n"
          "@app.get('/v1/items')\ndef list_items():\n    return []\n\n"
          "@app.post('/v1/items/{item_id}/tags')\ndef tag(item_id: int):\n    return {}\n")
    write(root, "items/cli.py",
          "import argparse\ndef main():\n    p = argparse.ArgumentParser()\n    p.add_argument('--port')\n")
    write(root, "items/hooks.py", "def register_hook(name, fn):\n    pass\n")


def tool_use(id_, name, inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


def response(blocks, stop="tool_use", usage=(100, 20)):
    return NS(content=blocks, stop_reason=stop,
              usage=NS(input_tokens=usage[0], output_tokens=usage[1],
                       cache_read_input_tokens=0, cache_creation_input_tokens=0))


class FakeClient:
    """Replays scripted responses and records every request."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.beta = NS(messages=NS(create=self._create))
        self.messages = NS(create=self._create)

    def _create(self, **kw):
        self.requests.append(kw)
        if not self.script:
            raise AssertionError("unexpected extra request")
        return self.script.pop(0)


def answer(feasible=True, steps=(), evidence=()):
    return {"feasible": feasible, "summary": "s", "steps": list(steps), "evidence": list(evidence),
            "confidence": 0.8}


def step(kind, **kw):
    base = {"kind": kind, "description": "d", "method": None, "path": None, "command": None,
            "symbol": None, "env_vars": []}
    base.update(kw)
    return base


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        service(self.dir)
        self.repo = Repo(self.dir)
        self.grader = Grader(self.repo, ["items/api.py"])

    def tearDown(self):
        shutil.rmtree(self.dir)


class Paths(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_path("https://x.io/v1/items/42?x=1"), "/v1/items/{}")
        self.assertEqual(normalize_path("/v1/items/<int:pk>/tags"), "/v1/items/{}/tags")
        self.assertEqual(normalize_path("/v1/items/:id"), "/v1/items/{}")


class Grading(Base):
    def test_declared_route_is_grounded(self):
        g = self.grader.grade(answer(steps=[step("http", method="POST", path="/v1/items/7/tags")]))
        self.assertEqual((g.grounded, g.checked), (1, 1))

    def test_mounted_prefix_still_matches(self):
        g = self.grader.grade(answer(steps=[step("http", method="GET", path="/api/v1/items")]))
        self.assertEqual(g.grounded, 1)

    def test_invented_route_fails(self):
        g = self.grader.grade(answer(steps=[step("http", method="GET", path="/v1/widgets")]))
        self.assertEqual(g.grounded, 0)
        self.assertIn("not a declared route", g.problems[0])

    def test_cli_and_flags(self):
        ok = self.grader.grade(answer(steps=[step("cli", command="itemctl serve --port 9000")]))
        bad_flag = self.grader.grade(answer(steps=[step("cli", command="itemctl serve --listen 9000")]))
        bad_prog = self.grader.grade(answer(steps=[step("cli", command="widgetctl serve")]))
        self.assertEqual((ok.grounded, bad_flag.grounded, bad_prog.grounded), (1, 0, 0))

    def test_env_vars(self):
        ok = self.grader.grade(answer(steps=[step("config", env_vars=["ITEMS_DB"])]))
        bad = self.grader.grade(answer(steps=[step("config", env_vars=["ITEMS_DATABASE_URL"])]))
        self.assertEqual((ok.grounded, bad.grounded), (1, 0))

    def test_library_symbol(self):
        ok = self.grader.grade(answer(steps=[step("library", symbol="items.hooks.register_hook")]))
        bad = self.grader.grade(answer(steps=[step("library", symbol="items.hooks.add_plugin")]))
        self.assertEqual((ok.grounded, bad.grounded), (1, 0))

    def test_live_requires_exercise(self):
        from neosloc.agentic.workspace import HttpCall
        a = answer(steps=[step("http", method="GET", path="/v1/items")])
        self.assertEqual(self.grader.grade(a, live=[]).grounded, 0)
        self.assertEqual(self.grader.grade(a, live=[HttpCall("GET", "/v1/items", 200)]).grounded, 1)


class Scope(Base):
    def test_docs_scope_hides_implementation(self):
        ws = Workspace(self.repo, "docs")
        self.assertIn("README.md", ws.visible)
        self.assertNotIn("items/api.py", ws.visible)
        with self.assertRaises(ToolError):
            ws.run("read_file", {"path": "items/api.py", "start_line": None})

    def test_source_scope_and_search(self):
        ws = Workspace(self.repo, "source")
        out = ws.run("search", {"regex": r"@app\.get", "path_regex": None})
        self.assertIn("items/api.py:6:", out)

    def test_no_http_tool_without_base_url(self):
        names = [t["name"] for t in Workspace(self.repo, "docs").tools()]
        self.assertNotIn("http_request", names)
        self.assertEqual(names[-1], "submit_result")

    def test_strict_schemas(self):
        for tool in Workspace(self.repo, "docs", base_url="http://x").tools():
            schema = tool["input_schema"]
            self.assertTrue(tool["strict"])
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(sorted(schema["required"]), sorted(schema["properties"]))


class Loop(Base):
    def probe(self, script, **kw):
        client = FakeClient(script)
        return Probe(self.repo, client, route_files=["items/api.py"], log=lambda s: None, **kw), client

    def test_solved_task(self):
        script = [
            response([NS(type="text", text="looking"), tool_use("t1", "read_file", {"path": "README.md", "start_line": None})]),
            response([tool_use("t2", "submit_result", answer(
                steps=[step("cli", command="itemctl serve --port 8001", env_vars=["ITEMS_DB"])],
                evidence=["README.md"]))]),
        ]
        probe, client = self.probe(script)
        rec = probe.run_task(select(["run"])[0], "docs")
        self.assertEqual(rec["outcome"], "solved")
        self.assertTrue(rec["success"])
        self.assertEqual((rec["turns"], rec["tool_calls"]), (2, 2))
        self.assertEqual(rec["input_tokens"], 200)
        # The message list grows in place; [2] is the tool-result turn.
        last = client.requests[1]["messages"][2]["content"][0]
        self.assertEqual(last["tool_use_id"], "t1")
        self.assertIn("itemctl serve", last["content"])
        # Defaults: fallbacks on, effort explicit, caching on, no forced tool_choice.
        req = client.requests[0]
        self.assertEqual(req["fallbacks"], "default")
        self.assertEqual(req["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(req["output_config"], {"effort": "medium"})
        self.assertIn("cache_control", req)
        self.assertNotIn("tool_choice", req)

    def test_tool_error_is_reported_not_raised(self):
        script = [
            response([tool_use("t1", "read_file", {"path": "items/api.py", "start_line": None})]),
            response([tool_use("t2", "submit_result", answer(feasible=False))]),
        ]
        probe, client = self.probe(script)
        rec = probe.run_task(select(["export"])[0], "docs")
        self.assertEqual(rec["tool_errors"], 1)
        self.assertTrue(client.requests[1]["messages"][2]["content"][0]["is_error"])
        self.assertEqual(rec["outcome"], "infeasible")

    def test_nudge_then_no_submit(self):
        script = [response([NS(type="text", text="done")], stop="end_turn"),
                  response([NS(type="text", text="still done")], stop="end_turn")]
        probe, _ = self.probe(script)
        rec = probe.run_task(TASKS[0], "docs")
        self.assertEqual(rec["outcome"], "no_submit")

    def test_refusal(self):
        probe, _ = self.probe([response([], stop="refusal")])
        self.assertEqual(probe.run_task(TASKS[0], "docs")["outcome"], "refusal")

    def test_missing_credentials_abort_the_run(self):
        class AuthenticationError(Exception):
            pass

        client = FakeClient([])
        client.beta = NS(messages=NS(create=lambda **kw: (_ for _ in ()).throw(AuthenticationError("401"))))
        probe = Probe(self.repo, client, log=lambda s: None)
        with self.assertRaises(SystemExit):
            probe.run(TASKS, ["docs"])

    def test_turn_limit(self):
        loop = [response([tool_use("t%d" % i, "list_files", {"pattern": None})]) for i in range(3)]
        probe, _ = self.probe(loop, max_turns=3)
        self.assertEqual(probe.run_task(TASKS[0], "docs")["outcome"], "turn_limit")

    def test_budget_stops_new_tasks(self):
        expensive = response([tool_use("t1", "submit_result", answer(feasible=False))], usage=(2_000_000, 0))
        probe, client = self.probe([expensive], max_cost=1.0)
        out = probe.run(select(["auth", "list"]), ["docs"])
        self.assertEqual(len(client.requests), 1)
        self.assertEqual([t["outcome"] for t in out["tasks"]], ["infeasible", "budget"])

    def test_summary_and_gap(self):
        ok = lambda: response([tool_use("s", "submit_result", answer(
            steps=[step("http", method="GET", path="/v1/items")]))])
        bad = lambda: response([tool_use("s", "submit_result", answer(feasible=False))])
        probe, _ = self.probe([bad(), ok()])
        out = probe.run(select(["list"]), ["docs", "source"])
        self.assertEqual(out["summary"]["docs"]["success_rate"], 0.0)
        self.assertEqual(out["summary"]["source"]["success_rate"], 1.0)
        self.assertEqual(out["documentation_gap"], 1.0)

    def test_transcripts(self):
        script = [response([tool_use("s", "submit_result", answer(feasible=False))])]
        out_dir = os.path.join(self.dir, "tr")
        probe, _ = self.probe(script, transcripts=out_dir)
        probe.run_task(TASKS[0], "docs")
        with open(os.path.join(out_dir, "docs-auth.json")) as fh:
            self.assertEqual(json.load(fh)["result"]["outcome"], "infeasible")


class Live(Base):
    def setUp(self):
        super().setUp()

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                code = 200 if self.path.startswith("/v1/items") else 404
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("X-RateLimit-Remaining", "9")
                self.end_headers()
                self.wfile.write(json.dumps({"auth": self.headers.get("Authorization")}).encode())

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def test_http_tool(self):
        ws = Workspace(self.repo, "docs", base_url=self.url, auth_headers={"Authorization": "Bearer t"})
        out = ws.run("http_request", {"method": "GET", "path": "/v1/items", "headers": [], "body": None})
        self.assertIn("HTTP 200", out)
        self.assertIn("X-RateLimit-Remaining: 9", out)
        self.assertIn("Bearer t", out)
        self.assertEqual(ws.http_log[0].path, "/v1/items")

    def test_read_only_by_default(self):
        ws = Workspace(self.repo, "docs", base_url=self.url)
        with self.assertRaises(ToolError):
            ws.run("http_request", {"method": "POST", "path": "/v1/items", "headers": [], "body": "{}"})

    def test_absolute_urls_rejected(self):
        ws = Workspace(self.repo, "docs", base_url=self.url)
        with self.assertRaises(ToolError):
            ws.run("http_request", {"method": "GET", "path": "http://example.com/", "headers": [], "body": None})


class Pricing(unittest.TestCase):
    def test_cost(self):
        u = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_input_tokens": 1_000_000,
             "cache_creation_input_tokens": 0}
        self.assertAlmostEqual(cost_usd("claude-opus-5-5", u), 4.0 + 2.0 + 0.2)
        self.assertIsNone(cost_usd("unknown-model", u))

    def test_levels(self):
        self.assertEqual([level_from_rate(r) for r in (0, 0.1, 0.5, 0.7, 0.9)], [0, 1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
