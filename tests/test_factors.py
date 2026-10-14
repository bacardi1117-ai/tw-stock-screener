"""Local CSV factor calculations, especially trading-day windows."""

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from calculate_factors import calculate_factors, financial_factors, price_factors, revenue_factors, save_factors


class FactorTests(unittest.TestCase):
    def test_price_averages_and_returns_use_trading_rows(self):
        prices = pd.DataFrame({"close": range(1, 122), "high": range(1, 122),
                               "volume": range(1, 122)})
        result = price_factors(prices)
        self.assertAlmostEqual(result["ma20"], sum(range(102, 122)) / 20)
        self.assertAlmostEqual(result["ma60"], sum(range(62, 122)) / 60)
        self.assertAlmostEqual(result["ma120"], sum(range(2, 122)) / 120)
        self.assertAlmostEqual(result["return_20d"], (121 / 101 - 1) * 100)
        self.assertAlmostEqual(result["return_60d"], (121 / 61 - 1) * 100)
        self.assertAlmostEqual(result["return_120d"], (121 / 1 - 1) * 100)
        self.assertEqual(result["distance_to_60d_high"], 0)
        short = price_factors(prices.head(1))
        self.assertTrue(pd.isna(short["ma20"]))
        self.assertTrue(pd.isna(short["return_20d"]))

    def test_recent_revenue_and_four_consecutive_eps_quarters(self):
        revenue = pd.DataFrame({"year": [2026] * 3, "month": [7, 8, 9],
                                "revenue": [100, 110, 120], "revenue_mom": [None, 10, 9.09],
                                "revenue_yoy": [10, -2, 20]})
        values = revenue_factors(revenue)
        self.assertAlmostEqual(values["revenue_yoy_3m_avg"], 28 / 3)
        self.assertEqual(values["revenue_yoy_3m_positive_count"], 2)
        financials = pd.DataFrame({"year": [2025, 2025, 2026, 2026],
                                   "quarter": [3, 4, 1, 2], "eps_single": [1, 2, 3, -1],
                                   "eps_yoy": [5, 6, -1, 8]})
        result = financial_factors(financials)
        self.assertEqual(result["eps_ttm"], 5)
        self.assertEqual(result["eps_positive_quarters_4"], 3)
        self.assertEqual(result["eps_growth_positive_count_4"], 3)
        financials.loc[2, "quarter"] = 2
        self.assertTrue(pd.isna(financial_factors(financials)["eps_ttm"]))

    def test_local_pipeline_keeps_stocks_with_missing_data_and_saves_top(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as name:
            root = Path(name)
            for folder in ("market", "prices", "revenue", "financials"):
                (root / "data" / folder).mkdir(parents=True)
            stocks = root / "data" / "market" / "stocks.csv"
            pd.DataFrame([{"stock_id": "2330", "stock_name": "TSMC", "market": "TWSE"},
                          {"stock_id": "2317", "stock_name": "Foxconn", "market": "TWSE"}]).to_csv(stocks, index=False)
            pd.DataFrame([{"date": "2026-10-14", "stock_id": "2330", "close": 100,
                           "high": 101, "volume": 10}]).to_csv(root / "data" / "prices" / "2026.csv", index=False)
            frame = calculate_factors(stocks, root / "data" / "prices",
                                      root / "data" / "revenue", root / "data" / "financials")
            self.assertEqual(len(frame), 2)
            self.assertEqual(frame.stock_id.nunique(), 2)
            self.assertEqual(frame.score_total.tolist(), [0, 0])
            self.assertTrue(frame.score_quality.between(0, 40).all())
            self.assertTrue(frame.score_growth.between(0, 35).all())
            self.assertTrue(frame.score_momentum.between(0, 25).all())
            paths = save_factors(frame, root)
            self.assertTrue(all(path.exists() for path in paths))
            self.assertEqual(len(pd.read_json(paths[2])), 2)


if __name__ == "__main__":
    unittest.main()
