"""Contract test: the probe's requests are accepted by the real anthropic SDK.

Runs the probe with the real SDK against a local mock of the Messages API, so
it costs nothing. Skipped when the SDK isn't installed (it needs Python >= 3.10).
"""
import http.server
import json
import os
import shutil
import tempfile
import threading
import unittest

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

from neosloc.agentic import Probe, select
from neosloc.agentic.llm import AnthropicBackend
from neosloc.repo import Repo

REPLIES = [
    {"stop_reason": "tool_use", "content": [
        {"type": "text", "text": "Reading the README."},
        {"type": "tool_use", "id": "toolu_1", "name": "read_file",
         "input": {"path": "README.md", "start_line": None}}]},
    {"stop_reason": "tool_use", "content": [
        {"type": "tool_use", "id": "toolu_2", "name": "submit_result", "input": {
            "feasible": True, "summary": "compose", "confidence": 0.7, "evidence": ["compose.yaml"],
            "steps": [{"kind": "cli", "description": "run", "method": None, "path": None,
                       "command": "docker compose up", "symbol": None, "env_vars": []}]}}]},
]


@unittest.skipIf(anthropic is None, "anthropic SDK not installed")
class SdkContract(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for rel, text in {"README.md": "# x\nRun with docker compose up.\n",
                          "compose.yaml": "services: {}\n", "app.py": "x = 1\n"}.items():
            with open(os.path.join(self.dir, rel), "w") as fh:
                fh.write(text)
        self.seen = []
        seen = self.seen

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append({"path": self.path, "beta": self.headers.get("anthropic-beta"), "body": body})
                r = REPLIES[len(seen) - 1]
                data = json.dumps({
                    "id": "msg_%d" % len(seen), "type": "message", "role": "assistant",
                    "model": body["model"], "content": r["content"], "stop_reason": r["stop_reason"],
                    "stop_sequence": None,
                    "usage": {"input_tokens": 1000, "output_tokens": 50, "cache_read_input_tokens": 900,
                              "cache_creation_input_tokens": 0}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.dir)

    def test_round_trip(self):
        client = anthropic.Anthropic(api_key="test", max_retries=0,
                                     base_url="http://127.0.0.1:%d" % self.server.server_port)
        backend = AnthropicBackend("claude-opus-5-5", client=client)
        rec = Probe(Repo(self.dir), backend, log=lambda s: None).run_task(select(["run"])[0], "docs")
        first, second = self.seen
        self.assertTrue(first["path"].startswith("/v1/messages"))
        self.assertEqual(first["beta"], "server-side-fallback-2026-07-01")
        self.assertEqual(first["body"]["fallbacks"], "default")
        self.assertEqual(first["body"]["output_config"], {"effort": "medium"})
        self.assertEqual(first["body"]["cache_control"], {"type": "ephemeral"})
        self.assertTrue(all(t["strict"] for t in first["body"]["tools"]))
        self.assertEqual([c["type"] for c in second["body"]["messages"][1]["content"]], ["text", "tool_use"])
        self.assertEqual(second["body"]["messages"][2]["content"][0]["tool_use_id"], "toolu_1")
        self.assertEqual(rec["outcome"], "solved")
        self.assertEqual(rec["cache_read_input_tokens"], 1800)


if __name__ == "__main__":
    unittest.main()
