"""Boundary and missing-value tests for the QGM point schedule."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scoring import CORE_FACTORS, score_factors


class ScoringTests(unittest.TestCase):
    def test_quality_roe_debt_and_eps_stability(self):
        row = {"roe_quarterly_approx": 20, "debt_ratio": 30,
               "eps_positive_quarters_4": 4}
        result = score_factors(row)
        self.assertEqual(result["score_quality"], 22)
        self.assertTrue(result["quality_roe"])
        self.assertTrue(result["quality_debt"])
        self.assertTrue(result["quality_eps_stability"])
        row.update(roe_quarterly_approx=5, debt_ratio=60, eps_positive_quarters_4=2)
        self.assertEqual(score_factors(row)["score_quality"], 7)

    def test_growth_revenue_eps_and_margin_yoy(self):
        row = {"revenue_yoy": 30, "revenue_yoy_3m_avg": 20,
               "eps_yoy": 50, "gross_margin_yoy": 3,
               "operating_margin_yoy": 3}
        self.assertEqual(score_factors(row)["score_growth"], 35)
        row.update(revenue_yoy=0, eps_yoy=0, gross_margin_yoy=0)
        self.assertEqual(score_factors(row)["score_growth"], 3 + 5 + 3 + 2 + 5)

    def test_maximum_and_missing_scores(self):
        complete = {field: 100 for field in CORE_FACTORS}
        complete.update(debt_ratio=0, eps_positive_quarters_4=4,
                        operating_cash_flow_single=1, free_cash_flow_single=1,
                        close=200, ma20=100, ma60=100, ma120=100,
                        avg_volume_20=200, avg_volume_60=100,
                        distance_to_60d_high=0)
        scores = score_factors(complete)
        self.assertEqual((scores["score_quality"], scores["score_growth"],
                          scores["score_momentum"], scores["score_total"]), (40, 35, 25, 100))
        self.assertEqual(scores["data_completeness"], 100)
        missing = score_factors({})
        self.assertEqual(missing["score_total"], 0)
        self.assertEqual(missing["data_completeness"], 0)


if __name__ == "__main__":
    unittest.main()
