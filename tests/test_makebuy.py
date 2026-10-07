"""Make or buy: the model moves the right way when its inputs do."""
import copy
import json
import os
import shutil
import tempfile
import unittest

from neosloc import makebuy
from neosloc.cli import analyze
from neosloc.makebuy import make_or_buy
from tests.test_cli import run, validate
from tests.test_criteria import CLI, PYPROJECT_CLI


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for rel, text in {"pyproject.toml": PYPROJECT_CLI, "tool/__init__.py": "", "tool/cli.py": CLI}.items():
            path = os.path.join(self.dir, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(text)
        self.report = analyze(self.dir)
        from neosloc.facts import Facts
        from neosloc.repo import Repo
        self.leg = Facts(Repo(self.dir)).legibility()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def mb(self, value=None, estimate=None, dims=None, **kw):
        return make_or_buy(dims or self.report.dimensions, self.leg, value or self.report.value,
                           estimate or self.report.estimate, **kw)


class Model(Base):
    def test_shape_and_consistency(self):
        m = self.mb()
        self.assertIn(m["verdict"], ("make", "buy", "toss-up"))
        mk, by = m["make"], m["buy"]
        self.assertGreater(mk["tokens"]["output"], 0)
        self.assertEqual(mk["tokens"]["input"], int(mk["tokens"]["output"] * makebuy.CONTEXT_RATIO))
        self.assertAlmostEqual(mk["total_cost"], mk["build_cost"] + 3 * mk["yearly_cost"], delta=0.05)
        self.assertAlmostEqual(m["make_buy_ratio"], mk["total_cost"] / by["total_cost"], places=3)

    def test_higher_price_favours_make(self):
        cheap, dear = self.mb(buy_price=0), self.mb(buy_price=5_000)
        self.assertGreater(dear["buy"]["total_cost"], cheap["buy"]["total_cost"])
        self.assertLess(dear["make_buy_ratio"], cheap["make_buy_ratio"])
        self.assertEqual(dear["verdict"], "make")

    def test_break_even_price_equalises_totals(self):
        be = self.mb(buy_price=10_000)["break_even_price_per_year"]
        if be > 0:
            m = self.mb(buy_price=be)
            self.assertAlmostEqual(m["make"]["total_cost"], m["buy"]["total_cost"], delta=1.0)

    def test_captured_behaviour_makes_make_cheaper(self):
        v = copy.deepcopy(self.report.value)
        v["capture"]["capture"] = 0.0
        low = self.mb(value=v)
        v["capture"]["capture"] = 1.0
        high = self.mb(value=v)
        self.assertLess(high["make"]["human_days"], low["make"]["human_days"])
        self.assertLess(high["make"]["final_tokens"], low["make"]["final_tokens"])

    def test_history_knowledge_makes_make_dearer(self):
        v = copy.deepcopy(self.report.value)
        v["rediscover_pm"] = 2.0
        self.assertAlmostEqual(self.mb(value=v)["make"]["rediscover_days"], 2.0 * makebuy.WORK_DAYS_PER_MONTH)

    def test_stable_contracts_mean_fewer_upgrades(self):
        dims = copy.deepcopy(self.report.dimensions)
        stab = next(d for d in dims if d.key == "stability")
        stab.level = 0
        unstable = self.mb(dims=dims)["buy"]["upgrade_minutes_per_year"]
        stab.level = 4
        stable = self.mb(dims=dims)["buy"]["upgrade_minutes_per_year"]
        self.assertLess(stable, unstable)

    def test_retrofit_is_not_a_buyer_cost(self):
        est = copy.deepcopy(self.report.estimate)
        est["retrofit_person_days"] = 100.0
        est["retrofit_by_dimension"] = {k: 50.0 for k in est["retrofit_by_dimension"]}
        self.assertEqual(self.mb(estimate=est)["buy"], self.mb()["buy"])

    def levels(self, **levels):
        dims = copy.deepcopy(self.report.dimensions)
        for d in dims:
            if d.key in levels:
                d.level, d.best_surface = levels[d.key]
        return self.mb(dims=dims)["buy"]["adoption_minutes"]

    def test_published_cli_is_adopted_in_minutes(self):
        a = self.levels(embeddability=(3, "cli"), interface=(4, "cli"))
        self.assertLessEqual(a["total"], 5)

    def test_standard_service_with_compose_is_minutes(self):
        a = self.levels(embeddability=(4, "service"), interface=(4, "service"))
        self.assertLessEqual(a["total"], 10)

    def test_no_programmatic_surface_takes_days(self):
        a = self.levels(embeddability=(1, "service"), interface=(0, "frontend"))
        self.assertGreaterEqual(a["total"], 8 * 60)

    def test_adoption_gets_faster_with_each_level(self):
        totals = [self.levels(embeddability=(lvl, "service"), interface=(lvl, "service"))["total"] for lvl in range(5)]
        self.assertEqual(totals, sorted(totals, reverse=True))

    def test_unknown_model_keeps_tokens_without_price(self):
        m = self.mb(model="anthropic:claude-unknown-9")
        self.assertIsNone(m["make"]["model_cost"])
        self.assertGreater(m["make"]["tokens"]["output"], 0)
        self.assertFalse(m["assumptions"]["model_priced"])

    def test_model_prices_change_token_cost_only(self):
        a, b = self.mb(model="anthropic:claude-opus-5-5"), self.mb(model="anthropic:claude-haiku-4-5")
        self.assertLess(b["make"]["model_cost"], a["make"]["model_cost"])
        self.assertEqual(a["make"]["tokens"], b["make"]["tokens"])


class Measured(Base):
    def test_probe_measurement_is_attached(self):
        from neosloc.makebuy import measured_adoption
        def task(name, ok, secs):
            return {"task": name, "scope": "docs", "success": ok, "outcome": "solved" if ok else "ungrounded",
                    "seconds": secs, "input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0, "cost_usd": 0.01}
        agentic = {"runs": [{"model": "m", "tasks": [task("run", True, 60), task("list", True, 30),
                                                      task("auth", False, 10)]}]}
        m = measured_adoption(agentic)
        self.assertEqual((m["succeeded"], m["minutes"], m["tokens"], m["cost_usd"]), (True, 1.5, 2200, 0.02))
        agentic["runs"][0]["tasks"][1] = task("list", False, 30)
        self.assertFalse(measured_adoption(agentic)["succeeded"])
        self.assertIsNone(measured_adoption({"runs": [{"model": "m", "tasks": [task("auth", True, 5)]}]}))
        self.assertIsNone(measured_adoption(None))


class Cli(Base):
    def test_flags_and_json(self):
        status, out, _ = run("--json", "--buy-price", "1200", "--horizon", "5", self.dir)
        doc = json.loads(out)
        validate(doc)
        self.assertEqual(status, 0)
        self.assertEqual((doc["make_or_buy"]["horizon_years"], doc["make_or_buy"]["buy"]["price_per_year"]), (5.0, 1200.0))

    def test_text(self):
        _, out, _ = run(self.dir)
        self.assertIn("Make or buy (over 3 years", out)
        self.assertIn("Verdict:", out)


if __name__ == "__main__":
    unittest.main()
