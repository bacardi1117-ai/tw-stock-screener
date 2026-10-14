"""Offline checks for financial math, missing data, and the rolling API budget."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from finmind_client import ApiBudget, BudgetReached, FinMindClient
from fundamentals_store import safe_percent
from update_financials import FINANCIAL_COLUMNS, _empty_record, _recalculate
from update_revenue import REVENUE_COLUMNS, _recalculate as recalculate_revenue
import update_revenue
import update_financials


class FundamentalsTests(unittest.TestCase):
    def test_revenue_percentages_use_period_and_percent_units(self):
        frame = pd.DataFrame([
            ("2025-10-01", 2025, 9, "2330", "TSMC", 100.0, None, None),
            ("2026-09-01", 2026, 8, "2330", "TSMC", 150.0, None, None),
            ("2026-10-01", 2026, 9, "2330", "TSMC", 165.0, None, None),
        ], columns=REVENUE_COLUMNS)
        result = recalculate_revenue(frame)
        latest = result.iloc[-1]
        self.assertAlmostEqual(latest.revenue_mom, 10.0)
        self.assertAlmostEqual(latest.revenue_yoy, 65.0)
        self.assertTrue(pd.isna(safe_percent(3, 0)))

    def test_quarterly_metrics_and_negative_capex_direction(self):
        prior_year = _empty_record("2330", "TSMC", "2025-06-30")
        prior_year.update({"eps": 8.0, "revenue": 200.0, "gross_profit": 80.0,
                           "operating_income": 60.0, "equity": 900.0})
        q1 = _empty_record("2330", "TSMC", "2026-03-31")
        q1.update({"eps": 9.0, "revenue": 250.0, "gross_profit": 100.0,
                   "operating_income": 75.0, "equity": 1000.0,
                   "operating_cash_flow_ytd": 100.0, "capital_expenditure_ytd": -20.0})
        q2 = _empty_record("2330", "TSMC", "2026-06-30")
        q2.update({"eps": 10.0, "revenue": 300.0, "gross_profit": 135.0,
                   "operating_income": 105.0, "net_income": 90.0,
                   "total_assets": 2000.0, "total_liabilities": 600.0,
                   "equity": 1100.0, "operating_cash_flow_ytd": 220.0,
                   "capital_expenditure_ytd": -55.0})
        frame = pd.DataFrame([prior_year, q1, q2], columns=FINANCIAL_COLUMNS)
        latest = _recalculate(frame).iloc[-1]
        self.assertAlmostEqual(latest.eps_qoq, 100 / 9)
        self.assertAlmostEqual(latest.eps_yoy, 25.0)
        self.assertAlmostEqual(latest.gross_margin, 45.0)
        self.assertAlmostEqual(latest.gross_margin_qoq, 5.0)
        self.assertAlmostEqual(latest.gross_margin_yoy, 5.0)
        self.assertAlmostEqual(latest.operating_margin, 35.0)
        self.assertAlmostEqual(latest.operating_margin_qoq, 5.0)
        self.assertAlmostEqual(latest.operating_margin_yoy, 5.0)
        self.assertAlmostEqual(latest.roe, 90 / 1050 * 100)
        self.assertAlmostEqual(latest.debt_ratio, 30.0)
        self.assertAlmostEqual(latest.operating_cash_flow, 120.0)
        self.assertAlmostEqual(latest.capital_expenditure, 35.0)
        self.assertAlmostEqual(latest.free_cash_flow, 85.0)

    def test_missing_comparison_periods_stay_empty(self):
        only = _empty_record("2330", "TSMC", "2026-06-30")
        only.update({"eps": 5.0, "revenue": 100.0, "gross_profit": 40.0,
                     "operating_income": 20.0, "operating_cash_flow_ytd": 100.0,
                     "capital_expenditure_ytd": -50.0})
        row = _recalculate(pd.DataFrame([only], columns=FINANCIAL_COLUMNS)).iloc[0]
        for name in ("eps_qoq", "eps_yoy", "gross_margin_qoq", "gross_margin_yoy",
                     "operating_margin_qoq", "operating_margin_yoy", "operating_cash_flow",
                     "capital_expenditure", "free_cash_flow"):
            self.assertTrue(pd.isna(row[name]), name)

    def test_budget_persists_between_runs_and_stops_at_limit(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "budget.json"
            budget = ApiBudget(path=path, limit=2)
            budget.consume()
            budget.consume()
            self.assertEqual(ApiBudget(path=path, limit=2).count, 2)
            with self.assertRaises(BudgetReached):
                budget.consume()

    def test_request_retry_counts_each_attempt_and_contains_failure(self):
        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"status": 200, "data": [{"value": 1}]}

        class FakeSession:
            def __init__(self):
                self.headers = {}
                self.attempts = 0

            def get(self, *args, **kwargs):
                self.attempts += 1
                if self.attempts == 1:
                    raise requests.Timeout("simulated timeout")
                return FakeResponse()

            def close(self):
                return None

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            session = FakeSession()
            budget = ApiBudget(path=Path(directory) / "budget.json", limit=2)
            client = FinMindClient("", budget=budget, session=session)
            self.assertEqual(client.get("sample", "2330", "2026-01-01"), [{"value": 1}])
            self.assertEqual(session.attempts, 2)
            self.assertEqual(budget.count, 2)
            with self.assertRaises(BudgetReached):
                client.get("sample", "2330", "2026-01-01")

    def test_incremental_csv_upserts_revised_revenue(self):
        class FakeClient:
            rows = [
                {"date": "2026-09-01", "revenue_year": 2026, "revenue_month": 8, "revenue": 100},
                {"date": "2026-10-01", "revenue_year": 2026, "revenue_month": 9, "revenue": 110},
            ]

            def get(self, *args):
                return self.rows

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            with patch.object(update_revenue, "REVENUE_DIR", Path(directory)):
                client = FakeClient()
                self.assertEqual(update_revenue.update_revenue(client, "2330", "TSMC"), (2, 0))
                self.assertEqual(update_revenue.update_revenue(client, "2330", "TSMC"), (0, 0))
                client.rows[1] = dict(client.rows[1], revenue=120)
                self.assertEqual(update_revenue.update_revenue(client, "2330", "TSMC"), (0, 1))
                saved = pd.read_csv(Path(directory) / "2026.csv", dtype={"stock_id": str})
                self.assertEqual(len(saved), 2)
                self.assertAlmostEqual(saved.iloc[-1].revenue_mom, 20.0)

    def test_statement_mapping_and_incremental_csv(self):
        class FakeClient:
            def get(self, dataset, *args):
                if dataset == "TaiwanStockFinancialStatements":
                    return [{"date": "2026-03-31", "type": kind, "value": value} for kind, value in (
                        ("EPS", 5), ("Revenue", 100), ("GrossProfit", 40),
                        ("OperatingIncome", 20), ("IncomeAfterTaxes", 15))]
                if dataset == "TaiwanStockBalanceSheet":
                    return [{"date": "2026-03-31", "type": kind, "value": value} for kind, value in (
                        ("Assets", 200), ("Liabilities", 50), ("Equity", 150))]
                return [{"date": "2026-03-31", "type": kind, "value": value,
                         "origin_name": origin} for kind, value, origin in (
                             ("CashFlowsFromOperatingActivities", 30, "營業活動之淨現金流入"),
                             ("UnmappedCapex", -10, "取得不動產、廠房及設備"))]

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            with patch.object(update_financials, "FINANCIALS_DIR", Path(directory)):
                client = FakeClient()
                added, updated, reached, latest = update_financials.update_financials(client, "2330", "TSMC")
                self.assertEqual((added, updated, reached), (1, 0, False))
                self.assertEqual((latest.eps, latest.gross_margin, latest.free_cash_flow), (5, 40, 20))
                self.assertEqual(update_financials.update_financials(client, "2330", "TSMC")[:3], (0, 0, False))
                self.assertEqual(len(pd.read_csv(Path(directory) / "2026.csv")), 1)

    def test_one_request_failure_does_not_block_next_stock(self):
        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"status": 200, "data": [{"stock_id": "2317"}]}

        class FakeSession:
            headers = {}

            def __init__(self):
                self.attempts = 0

            def get(self, *args, **kwargs):
                self.attempts += 1
                if self.attempts <= 3:
                    raise requests.Timeout("simulated timeout")
                return FakeResponse()

            def close(self):
                return None

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            budget = ApiBudget(path=Path(directory) / "budget.json", limit=5)
            client = FinMindClient("", budget=budget, session=FakeSession())
            with self.assertLogs("finmind_client", level="WARNING"):
                self.assertIsNone(client.get("sample", "2330", "2026-01-01"))
            self.assertEqual(client.get("sample", "2317", "2026-01-01"), [{"stock_id": "2317"}])
            self.assertEqual(budget.count, 4)


if __name__ == "__main__":
    unittest.main()
