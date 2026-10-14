from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fundamentals_universe import build_fundamentals_universe
from fetch_market import industry_name, is_financial_industry


class FundamentalsUniverseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root = Path(self.temp.name)
        self.stocks = self.root / "market" / "stocks.csv"
        self.prices = self.root / "prices"
        self.universe = self.root / "state" / "fundamentals_universe.csv"
        self.progress = self.root / "state" / "fundamentals_progress.json"
        self.stocks.parent.mkdir(parents=True)
        pd.DataFrame([
            {"stock_id": "1101", "stock_name": "A", "market": "TWSE", "industry": ""},
            {"stock_id": "1102", "stock_name": "B", "market": "TWSE", "industry": ""},
            {"stock_id": "1103", "stock_name": "C", "market": "TPEx", "industry": ""},
            {"stock_id": "1104", "stock_name": "D", "market": "TPEx", "industry": ""},
            {"stock_id": "1105", "stock_name": "E", "market": "TWSE", "industry": ""},
            {"stock_id": "1106", "stock_name": "F", "market": "TWSE", "industry": ""},
        ]).to_csv(self.stocks, index=False, encoding="utf-8-sig")
        self.prices.mkdir()
        pd.DataFrame([
            {"date": "2026-10-14", "stock_id": "1101", "close": 55},
            {"date": "2026-10-14", "stock_id": "1102", "close": 100},
            {"date": "2026-10-14", "stock_id": "1103", "close": 49},
            {"date": "2026-10-14", "stock_id": "1104", "close": 40},
            {"date": "2026-10-14", "stock_id": "1106", "close": 70},
            {"date": "2026-10-14", "stock_id": "1107", "close": 90},
        ]).to_csv(self.prices / "2026.csv", index=False, encoding="utf-8-sig")

    def tearDown(self):
        patch.stopall()
        self.temp.cleanup()

    def test_official_industry_code_17_is_financial(self):
        self.assertEqual(industry_name("17"), "金融保險業")
        self.assertTrue(is_financial_industry("金融保險業"))
        self.assertTrue(is_financial_industry("", "17"))
        self.assertFalse(is_financial_industry("半導體業", "24"))

    def test_builds_price_and_financial_filtered_universe(self):
        official = {
            "1101": "半導體業",
            "1102": "金融保險業",
            "1103": "半導體業",
            "1104": "金融保險業",
            "1105": "資訊服務業",
            "1106": "",
        }
        def fetcher(_session):
            return official, {"TWSE", "TPEx"}

        self.progress.parent.mkdir(parents=True)
        self.progress.write_text(
            '{"completed_stock_ids": ["1101", "1102"], '
            '"failed_stock_ids": ["1103"], "failure_reasons": {"1103": "no_data"}}',
            encoding="utf-8",
        )
        frame, state = build_fundamentals_universe(
            stocks_path=self.stocks, prices_dir=self.prices,
            universe_path=self.universe, progress_path=self.progress,
            industry_fetcher=fetcher,
        )
        self.assertEqual(len(frame), 6)
        self.assertEqual(int(frame.eligible.sum()), 1)
        self.assertEqual(state["excluded_financial_count"], 2)
        self.assertEqual(state["excluded_price_count"], 2)
        self.assertEqual(state["excluded_both_count"], 1)
        self.assertEqual(state["missing_price_count"], 1)
        self.assertEqual(state["missing_industry_count"], 1)
        self.assertEqual(state["completed_stock_ids"], ["1101"])
        self.assertEqual(state["remaining_count"], 0)
        self.assertEqual(state["failed_stock_ids"], [])
        updated_stocks = pd.read_csv(self.stocks, dtype={"stock_id": str}, encoding="utf-8-sig")
        self.assertEqual(updated_stocks.loc[updated_stocks.stock_id == "1102", "industry"].iloc[0], "金融保險業")


if __name__ == "__main__":
    unittest.main()
