"""Text rendering of every report section."""
import shutil
import tempfile
import unittest

from neosloc.agentic.runner import panel, summarize
from neosloc.cli import analyze
from neosloc.report import _k, to_json, to_text
from tests.test_agentic import service


def task(name, dim, ok, outcome, problems=()):
    return {"task": name, "dimension": dim, "scope": "docs", "model": "m", "outcome": outcome, "success": ok,
            "turns": 3, "tool_calls": 4, "tool_errors": 0, "problems": list(problems), "input_tokens": 1500,
            "output_tokens": 500, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            "cost_usd": 0.01}


class Render(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        service(cls.dir)
        cls.report = analyze(cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def test_static_sections(self):
        text = to_text(self.report)
        for line in ("neosloc integrability report", "Inventory:", "Interface surface", "Change legibility",
                     "Integrability index", "Retrofit effort", "Wrappability", "Value (neoCOCOMO",
                     "Classic COCOMO", "Knowledge at risk"):
            self.assertIn(line, text)
        # Levels are drawn as four boxes.
        self.assertRegex(text, r"Interface surface\s+[■□]{4}\s+\d ")

    def test_verbose_shows_all_evidence(self):
        dims = self.report.dimensions
        many = max(dims, key=lambda d: len(d.evidence))
        if len(many.evidence) > 4:
            self.assertIn("more (use -v)", to_text(self.report))
        self.assertNotIn("more (use -v)", to_text(self.report, verbose=True))

    def test_evaluator_sections(self):
        r = analyze(self.dir, only=["interface", "identity"], with_value=False)
        run_a = summarize([task("auth", "identity", True, "solved"),
                           task("list", "interface", False, "ungrounded", ["GET /x is not a declared route"])],
                          "anthropic:a", "medium", ["docs"], judge="openrouter:j")
        run_b = summarize([task("auth", "identity", True, "solved"), task("list", "interface", True, "solved")],
                          "openrouter:b", "low", ["docs"])
        r.agentic = {"runs": [run_a, run_b], "panel": panel([run_a, run_b])}
        r.review = {"models": ["openrouter:r"], "reviewed_index": 2.5, "disagreements": ["identity"],
                    "dimensions": {"interface": {"static": 3, "consensus": 3, "spread": 0,
                                                 "reviews": [{"level": 3, "rationale": "ok"}]},
                                   "identity": {"static": 0, "consensus": 2, "spread": 0,
                                                "reviews": [{"level": 2, "rationale": "x" * 200}]}}}
        r.spend = {"usd": 0.123, "max_usd": 5.0, "unpriced_calls": 2}
        text = to_text(r)
        self.assertIn("Agentic probe (anthropic:a, effort medium, scope docs, judge openrouter:j)", text)
        self.assertIn("success 1/2 (50%), level 2", text)
        self.assertIn("-- [docs] list      ungrounded", text)
        self.assertIn("GET /x is not a declared route", text)
        self.assertIn("models agree on 50% of tasks", text)
        self.assertIn("! identity       static 0 -> reviewed 2", text)
        self.assertIn("...", text)  # long rationale truncated
        self.assertIn("Reviewed integrability index: 2.50", text)
        self.assertIn("Disagreements to calibrate: identity", text)
        self.assertIn("Model spend: $0.12 of $5.00 budget; 2 call(s) could not be priced", text)

    def test_json_renderer(self):
        import json
        self.assertEqual(json.loads(to_json(self.report))["target"], self.report.target)

    def test_k(self):
        self.assertEqual([_k(999), _k(1500), _k(2_500_000)], ["999", "2k", "2.5M"])


if __name__ == "__main__":
    unittest.main()
