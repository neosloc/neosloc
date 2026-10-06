"""The code view: comments, docstrings, prose and regex literals aren't evidence."""
import os
import shutil
import tempfile
import textwrap
import unittest

from neosloc.cli import analyze
from neosloc.codeview import code_view, has_ignore_pragma, is_prose

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Python(unittest.TestCase):
    SRC = textwrap.dedent('''\
        """Module docstring mentions webhook and OAuth."""
        import re
        # a comment about prometheus
        SIG = r"webhook|X-RateLimit"
        RX = re.compile("idempotency")
        MSG = "Offer outbound webhooks so consumers are told about changes."
        H = {"Idempotency-Key": key}  # trailing comment opentelemetry
        def deliver_webhook(sub):
            """Send the webhook."""
            return post(sub.url)
        urlpatterns = [re_path(r'^api/v1/items/$', view)]
        ''')

    def test_masks_non_usage(self):
        v = code_view(self.SRC, "python")
        for gone in ("OAuth", "prometheus", "X-RateLimit", "idempotency", "opentelemetry", "consumers",
                     "Send the webhook"):
            self.assertNotIn(gone, v)
        for kept in ('"Idempotency-Key"', "def deliver_webhook", "re_path(r'"):
            self.assertIn(kept, v)
        self.assertEqual(v.count("\n"), self.SRC.count("\n"))

    def test_keep_regex_for_routes(self):
        self.assertIn("^api/v1/items/$", code_view(self.SRC, "python", keep_regex=True))

    def test_unparseable_python_is_returned_as_is(self):
        src = "print 'python 2'\n"
        self.assertEqual(code_view(src, "python"), src)


class CFamily(unittest.TestCase):
    def test_javascript(self):
        src = ("// comment about webhook\nconst rx = /X-RateLimit|webhook/i;\n"
               "const h = {'X-RateLimit-Remaining': n}; /* opentelemetry */\n"
               "const r = new RegExp('prometheus'); const url = 'http://x.io/a'; const d = a / b / c;\n"
               "app.get('/health', h)\n")
        v = code_view(src, "javascript")
        self.assertNotIn("webhook", v)
        self.assertNotIn("opentelemetry", v)
        self.assertNotIn("prometheus", v)
        for kept in ("'X-RateLimit-Remaining'", "'http://x.io/a'", "a / b / c", "'/health'"):
            self.assertIn(kept, v)

    def test_go(self):
        src = "// Package x uses prometheus\nvar rx = regexp.MustCompile(`webhook`)\nhttp.HandleFunc(\"/healthz\", h)\n"
        v = code_view(src, "go")
        self.assertNotIn("prometheus", v)
        self.assertNotIn("webhook", v)
        self.assertIn('"/healthz"', v)


class Helpers(unittest.TestCase):
    def test_prose(self):
        self.assertTrue(is_prose("Expose /health and /ready endpoints for orchestrators."))
        for code in ("Idempotency-Key", "application/problem+json", "SELECT pg_notify('c', x)",
                     "Authorization: Bearer"):
            self.assertFalse(is_prose(code), code)

    def test_pragma(self):
        self.assertTrue(has_ignore_pragma("# neosloc: ignore (vocabulary)\nX = 'webhook'\n"))
        self.assertFalse(has_ignore_pragma("\n" * 10 + "# neosloc: ignore\n"))


class Detection(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def level(self, key):
        return next(d for d in analyze(self.dir, with_value=False).dimensions if d.key == key)

    def test_scanner_vocabulary_is_not_usage(self):
        self.write("lint/rules.py", 'import re\nRULES = [re.compile(r"prometheus|opentelemetry|structlog")]\n'
                   '# we look for /healthz endpoints\nHELP = "Expose a health endpoint so the orchestrator can probe it."\n')
        self.assertEqual(self.level("observability").level, 0)

    def test_pragma_opts_a_file_out(self):
        self.write("lint/rules.py", '# neosloc: ignore\nSIGNALS = ["prometheus", "opentelemetry"]\n')
        self.assertEqual(self.level("observability").level, 0)

    def test_real_usage_still_counts(self):
        self.write("app/ops.py", "from prometheus_client import Counter\nfrom opentelemetry import trace\n"
                   "import structlog\n@app.get('/healthz')\ndef h(): pass\n")
        self.assertEqual(self.level("observability").level, 4)

    def test_django_regex_routes_still_count(self):
        self.write("app/urls.py", "urlpatterns = [re_path(r'^api/v1/items/(?P<pk>\\d+)/$', v)]\n")
        iface = self.level("interface")
        self.assertEqual(iface.metrics["route_declarations"], 1)
        stab = next(d for d in analyze(self.dir, with_value=False).dimensions if d.key == "stability")
        self.assertTrue(any(e.signal == "versioned-api-paths" for e in stab.evidence))

    def test_json_dumps_and_dump_methods_are_not_exports(self):
        self.write("app/serial.py", "import json\nclass M:\n    def dump(self):\n        return json.dumps(self.__dict__)\n")
        sigs = self.level("portability").metrics["signals"]
        self.assertNotIn("export", sigs)
        self.assertNotIn("open-formats", sigs)


class SelfScan(unittest.TestCase):
    """neosloc is full of the vocabulary it detects; it must not score itself on it."""

    def test_neosloc_does_not_flag_itself(self):
        levels = {d.key: d.level for d in analyze(ROOT, with_value=False).dimensions}
        for key in ("events", "identity", "observability", "extensibility"):
            self.assertLessEqual(levels[key], 1, key)


if __name__ == "__main__":
    unittest.main()
