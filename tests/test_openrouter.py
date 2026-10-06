"""OpenRouter backend and the judge/review/panel roles, against a local mock of
OpenRouter's API. No network, no spend."""
import http.server
import json
import shutil
import tempfile
import threading
import unittest

from neosloc.agentic import Budget, Judge, Probe, panel, parse_spec, review_all, select
from neosloc.agentic.llm import AuthFailure, OpenRouterBackend, validate
from neosloc.cli import analyze
from neosloc.repo import Repo
from tests.test_agentic import answer, service, step

MODELS = {"data": [
    {"id": "acme/tooler", "supported_parameters": ["tools", "tool_choice", "reasoning"],
     "pricing": {"prompt": "0.000001", "completion": "0.000002", "input_cache_read": "0.0000001"}},
    {"id": "acme/chatty", "supported_parameters": ["temperature"], "pricing": {"prompt": "0", "completion": "0"}},
]}


def completion(content=None, calls=(), finish="tool_calls", cost=0.001, cached=0):
    msg = {"role": "assistant", "content": content,
           "reasoning_details": [{"type": "reasoning.encrypted", "data": "abc"}]}
    if calls:
        msg["tool_calls"] = [{"id": "call_%d" % i, "type": "function",
                              "function": {"name": n, "arguments": a if isinstance(a, str) else json.dumps(a)}}
                             for i, (n, a) in enumerate(calls)]
    usage = {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100,
             "prompt_tokens_details": {"cached_tokens": cached}}
    if cost is not None:
        usage["cost"] = cost
    return {"id": "gen-1", "choices": [{"finish_reason": finish, "message": msg}], "usage": usage}


class MockOpenRouter:
    def __init__(self, replies, status=200):
        self.replies, self.requests, self.status = list(replies), [], status
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._send(200, MODELS)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"headers": dict(self.headers), "body": json.loads(json.dumps(body))})
                if outer.status != 200:
                    return self._send(outer.status, {"error": {"message": "nope"}})
                self._send(200, outer.replies.pop(0))

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d/api/v1" % self.server.server_port

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        service(self.dir)
        self.repo = Repo(self.dir)
        self.mocks = []

    def tearDown(self):
        for m in self.mocks:
            m.close()
        shutil.rmtree(self.dir)

    def mock(self, replies, status=200):
        m = MockOpenRouter(replies, status)
        self.mocks.append(m)
        return m

    def backend(self, mock, model="acme/tooler"):
        return OpenRouterBackend(model, "high", api_key="sk-or-test", base_url=mock.url, retries=0)


class Specs(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_spec("claude-opus-5-5"), ("anthropic", "claude-opus-5-5"))
        self.assertEqual(parse_spec("openai/gpt-5.6-luna"), ("openrouter", "openai/gpt-5.6-luna"))
        self.assertEqual(parse_spec("openrouter:anthropic/claude-opus-5.5"),
                         ("openrouter", "anthropic/claude-opus-5.5"))
        with self.assertRaises(ValueError):
            parse_spec("gpt5")


class Validation(unittest.TestCase):
    def test_validate(self):
        from neosloc.agentic.workspace import SUBMIT_TOOL
        schema = SUBMIT_TOOL["input_schema"]
        self.assertIsNone(validate(schema, answer(steps=[step("cli", command="x")])))
        self.assertIn("missing 'steps'", validate(schema, {"feasible": True, "summary": "",
                                                           "evidence": [], "confidence": 1}))
        bad = answer(steps=[step("shell", command="x")])
        self.assertIn("steps[0].kind", validate(schema, bad))
        self.assertIn("feasible should be boolean", validate(schema, dict(answer(), feasible="yes")))


class Backend(Base):
    def test_model_checks(self):
        m = self.mock([])
        with self.assertRaises(SystemExit):
            self.backend(m, "acme/chatty")  # no tool support
        with self.assertRaises(SystemExit):
            self.backend(m, "acme/missing")

    def test_auth_failure(self):
        m = self.mock([], status=401)
        conv = self.backend(m).conversation("sys", [])
        conv.send_user("hi")
        with self.assertRaises(AuthFailure):
            conv.next()

    def test_probe_over_openrouter(self):
        m = self.mock([
            completion(calls=[("read_file", {"path": "README.md", "start_line": None})], cached=400),
            completion(calls=[("submit_result", answer(steps=[
                step("cli", command="itemctl serve --port 8001", env_vars=["ITEMS_DB"])]))], cost=None),
        ])
        budget = Budget(5.0)
        probe = Probe(self.repo, self.backend(m), budget=budget, log=lambda s: None)
        rec = probe.run_task(select(["run"])[0], "docs")
        self.assertEqual(rec["outcome"], "solved")
        self.assertEqual(rec["model"], "openrouter:acme/tooler")
        first, second = m.requests
        self.assertEqual(first["headers"]["Authorization"], "Bearer sk-or-test")
        self.assertEqual(first["headers"]["X-Title"], "neosloc")
        self.assertEqual(first["body"]["reasoning"], {"effort": "high"})
        self.assertEqual(first["body"]["tool_choice"], "auto")
        self.assertEqual(first["body"]["tools"][0]["type"], "function")
        msgs = second["body"]["messages"]
        self.assertEqual([x["role"] for x in msgs], ["system", "user", "assistant", "tool"])
        self.assertEqual(msgs[2]["reasoning_details"][0]["data"], "abc")  # preserved across tool calls
        self.assertEqual(msgs[3]["tool_call_id"], "call_0")
        self.assertIn("itemctl serve", msgs[3]["content"])
        # Cost: reported 0.001 on turn one; turn two priced from the model listing.
        expected = 0.001 + (1000 * 0.000001 + 0 * 0.0000001 + 100 * 0.000002)
        self.assertAlmostEqual(rec["cost_usd"], expected)
        self.assertEqual(rec["cache_read_input_tokens"], 400)
        self.assertAlmostEqual(budget.spent, expected)

    def test_invalid_submission_is_bounced(self):
        m = self.mock([
            completion(calls=[("submit_result", "{not json")]),
            completion(calls=[("submit_result", {"feasible": True})]),
            completion(calls=[("submit_result", answer(feasible=False))]),
        ])
        rec = Probe(self.repo, self.backend(m), log=lambda s: None).run_task(select(["export"])[0], "docs")
        self.assertEqual(rec["outcome"], "infeasible")
        self.assertEqual(rec["tool_errors"], 2)
        tool_msgs = [x for x in m.requests[2]["body"]["messages"] if x["role"] == "tool"]
        self.assertIn("not valid JSON", tool_msgs[0]["content"])
        self.assertIn("invalid submission", tool_msgs[1]["content"])

    def test_content_filter_is_refusal(self):
        m = self.mock([completion(content="", finish="content_filter")])
        rec = Probe(self.repo, self.backend(m), log=lambda s: None).run_task(select(["auth"])[0], "docs")
        self.assertEqual(rec["outcome"], "refusal")


class Roles(Base):
    def test_judge_can_overrule_grounding(self):
        probe_m = self.mock([completion(calls=[("submit_result", answer(steps=[
            step("http", method="GET", path="/v1/items")]))])])
        judge_m = self.mock([
            completion(calls=[("search", {"regex": "def list_items", "path_regex": None})]),
            completion(calls=[("submit_verdict", {"works": False, "reason": "needs auth header",
                                                  "issues": ["no Authorization"]})]),
        ])
        budget = Budget(5.0)
        judge = Judge(self.repo, self.backend(judge_m), budget)
        probe = Probe(self.repo, self.backend(probe_m), budget=budget, judge=judge,
                      route_files=["items/api.py"], log=lambda s: None)
        rec = probe.run_task(select(["list"])[0], "docs")
        self.assertFalse(rec["success"])
        self.assertEqual(rec["outcome"], "judged_wrong")
        self.assertEqual(rec["judge"]["model"], "openrouter:acme/tooler")
        # The judge reads source: its search found the implementation.
        tool_msg = [x for x in judge_m.requests[1]["body"]["messages"] if x["role"] == "tool"][0]
        self.assertIn("items/api.py", tool_msg["content"])

    def test_judge_not_called_for_ungrounded(self):
        probe_m = self.mock([completion(calls=[("submit_result", answer(steps=[
            step("http", method="GET", path="/v1/widgets")]))])])
        judge_m = self.mock([])
        budget = Budget(5.0)
        probe = Probe(self.repo, self.backend(probe_m), budget=budget,
                      judge=Judge(self.repo, self.backend(judge_m), budget),
                      route_files=["items/api.py"], log=lambda s: None)
        self.assertEqual(probe.run_task(select(["list"])[0], "docs")["outcome"], "ungrounded")
        self.assertEqual(judge_m.requests, [])

    def test_review_panel(self):
        report = analyze(self.dir, only=["interface", "events"], with_value=False)
        a = self.mock([completion(calls=[("submit_review", {"level": 3, "rationale": "FastAPI spec",
                                                            "false_positives": [], "missed_evidence": []})]),
                       completion(calls=[("submit_review", {"level": 0, "rationale": "none",
                                                            "false_positives": [], "missed_evidence": []})])])
        b = self.mock([completion(calls=[("submit_review", {"level": 4, "rationale": "spec + CLI",
                                                            "false_positives": [], "missed_evidence": []})]),
                       completion(calls=[("submit_review", {"level": 1, "rationale": "hooks",
                                                            "false_positives": [], "missed_evidence": []})])])
        out = review_all(self.repo, report.dimensions, [self.backend(a), self.backend(b)], Budget(5.0),
                         log=lambda s: None)
        iface = out["dimensions"]["interface"]
        self.assertEqual([r["level"] for r in iface["reviews"]], [3, 4])
        self.assertEqual(iface["consensus"], 3)
        self.assertEqual(iface["spread"], 1)
        self.assertEqual(out["dimensions"]["events"]["consensus"], 0)
        prompt = json.loads(a.requests[0]["body"]["messages"][1]["content"])
        self.assertEqual(prompt["detector_level"], iface["static"])

    def test_probe_panel_agreement(self):
        runs = [{"model": "a", "tasks": [{"scope": "docs", "task": "auth", "success": True, "outcome": "solved"},
                                         {"scope": "docs", "task": "list", "success": False, "outcome": "ungrounded"}]},
                {"model": "b", "tasks": [{"scope": "docs", "task": "auth", "success": True, "outcome": "solved"},
                                         {"scope": "docs", "task": "list", "success": True, "outcome": "solved"}]}]
        p = panel(runs)
        self.assertEqual(p["agreement"], 0.5)
        self.assertEqual(p["success_share"]["docs/list"], 0.5)
        self.assertIsNone(panel(runs[:1]))


class CliWiring(Base):
    def test_cli_with_openrouter(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from unittest import mock
        from neosloc import agentic, cli

        m = self.mock([completion(calls=[("submit_result", answer(feasible=False))]),
                       completion(calls=[("submit_review", {"level": 2, "rationale": "r",
                                                            "false_positives": [], "missed_evidence": []})])])
        specs = []

        def fake_backend(spec, effort, fallbacks=True):
            specs.append((spec, effort))
            return self.backend(m)

        out = io.StringIO()
        with mock.patch.object(agentic, "make_backend", fake_backend), \
                redirect_stdout(out), redirect_stderr(io.StringIO()):
            cli.main([self.dir, "--agentic", "--tasks", "auth", "--review", "--only", "interface",
                      "--probe-model", "openrouter:acme/tooler", "--review-model", "openrouter:acme/other",
                      "--effort", "low", "--json"])
        self.assertEqual(specs, [("openrouter:acme/tooler", "low"), ("openrouter:acme/other", "low")])
        data = json.loads(out.getvalue())
        self.assertEqual(data["agentic"]["runs"][0]["tasks"][0]["outcome"], "infeasible")
        self.assertEqual(data["review"]["dimensions"]["interface"]["consensus"], 2)
        self.assertGreater(data["spend"]["usd"], 0)


if __name__ == "__main__":
    unittest.main()
