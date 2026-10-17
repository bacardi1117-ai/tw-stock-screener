"""Strategy behavior and Python/JavaScript parity on shared factors."""

import copy
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from strategy_engine import evaluate_all, evaluate_strategy, load_config, qgm_scores


class StrategyEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()
        cls.rows = json.loads((ROOT / "tests" / "strategy_fixture.json").read_text(encoding="utf-8"))

    def test_strategy_a_and_b_pass_with_full_inputs(self):
        statuses = evaluate_all(self.rows[0], self.config)
        self.assertEqual((statuses["strategy_a"], statuses["strategy_b"]), ("pass", "pass"))

    def test_revenue_yoy_min_changes_result(self):
        changed = copy.deepcopy(self.config)
        changed["strategy_a"]["conditions"]["revenue_yoy"]["value"] = 31
        self.assertEqual(evaluate_strategy(self.rows[0], changed["strategy_a"]), "fail")

    def test_roe_min_changes_result(self):
        changed = copy.deepcopy(self.config)
        changed["strategy_a"]["conditions"]["roe"]["value"] = 21
        self.assertEqual(evaluate_strategy(self.rows[0], changed["strategy_a"]), "fail")

    def test_disabled_condition_does_not_participate(self):
        changed = copy.deepcopy(self.config)
        condition = changed["strategy_a"]["conditions"]["revenue_yoy"]
        condition["value"] = 999
        condition["enabled"] = False
        self.assertEqual(evaluate_strategy(self.rows[0], changed["strategy_a"]), "pass")

    def test_nan_never_becomes_zero(self):
        changed = copy.deepcopy(self.config)
        changed["strategy_a"]["conditions"]["per"]["value"] = 18
        row = dict(self.rows[0], per=math.nan)
        self.assertEqual(evaluate_strategy(row, changed["strategy_a"]), "missing_data")

    def test_missing_data_flag(self):
        result = evaluate_all(self.rows[1], self.config)
        self.assertEqual(result["strategy_a"], "missing_data")
        self.assertTrue(result["strategy_a_missing_data"])

    def test_strategy_b_relative_market(self):
        row = dict(self.rows[0], return_60d_vs_market=-1)
        self.assertEqual(evaluate_all(row, self.config)["strategy_b"], "fail")

    def test_strategy_c_missing_valuation(self):
        result = evaluate_all(self.rows[0], self.config)
        self.assertEqual(result["strategy_c"], "missing_data")
        self.assertTrue(result["strategy_c_missing_data"])

    def test_strategy_d_unavailable_and_strategy_e_reports_missing_data(self):
        result = evaluate_all(self.rows[0], self.config)
        self.assertEqual((result["strategy_d"], result["strategy_e"]), ("unavailable", "missing_data"))

    def test_strategy_e_accepts_configured_dividend_profile(self):
        row = dict(self.rows[0], dividend_years=5, dividend_years_5=5,
                   dividend_yield=4.2, payout_ratio=65,
                   dividend_growth_3y=8, dividend_growth_3y_cagr=8,
                   dividend_min_change_3y_pct=-2,
                   free_cash_flow_single=10)
        self.assertEqual(evaluate_all(row, self.config)["strategy_e"], "pass")
        changed = copy.deepcopy(self.config)
        changed["strategy_e"]["conditions"]["free_cash_flow_positive"]["enabled"] = False
        row["free_cash_flow_single"] = None
        self.assertEqual(evaluate_all(row, changed)["strategy_e"], "pass")

    def test_qgm_weights_and_tiers_are_configurable(self):
        self.assertEqual(qgm_scores(self.rows[0], self.config)["score_total"], 100)
        changed = copy.deepcopy(self.config)
        changed["qgm"]["quality"][0]["tiers"][0]["value"] = 21
        self.assertLess(qgm_scores(self.rows[0], changed)["score_quality"], 40)
        changed["qgm"].update(quality_weight=50, growth_weight=25, momentum_weight=25)
        self.assertNotEqual(qgm_scores(self.rows[0], changed)["score_growth"], 35)

    def test_qgm_disabled_factor_defaults_and_maximum_normalization(self):
        self.assertTrue(all(rule.get("enabled", True) for rule in self.config["qgm"]["quality"]))
        changed = copy.deepcopy(self.config)
        changed["qgm"]["quality"][0]["enabled"] = False
        scores = qgm_scores(self.rows[0], changed)
        self.assertEqual(scores["quality_roe"], 0)
        self.assertEqual(scores["score_quality"], 40)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for cross-language parity")
    def test_javascript_parity(self):
        process = subprocess.run(["node", str(ROOT / "tests" / "strategy_fixture.mjs")],
                                 cwd=ROOT, capture_output=True, text=True, check=True)
        actual = json.loads(process.stdout)
        for row, js in zip(self.rows, actual):
            py = {**qgm_scores(row, self.config), **evaluate_all(row, self.config)}
            for key in ("score_quality", "score_growth", "score_momentum", "score_total"):
                self.assertAlmostEqual(py[key], js[key], places=4)
            for key in ("strategy_a", "strategy_b", "strategy_c", "strategy_d", "strategy_e"):
                self.assertEqual(py[key], js[key])


if __name__ == "__main__":
    unittest.main()
