import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import fundamentals_batch as batch
from finmind_client import ApiBudget, FinMindClient


class FakeBudget:
    def __init__(self):
        self.calls_this_run = 0

    def consume(self):
        self.calls_this_run += 1


class FakeClient:
    def __init__(self):
        self.budget = FakeBudget()
        self.errors = []
        self.stop_reason = None

    def close(self):
        pass


class FundamentalsBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root = Path(self.temp.name)
        self.stocks = self.root / "stocks.csv"
        self.progress = self.root / "state" / "fundamentals_progress.json"
        pd.DataFrame([
            {"stock_id": "1102", "stock_name": "B"},
            {"stock_id": "1101", "stock_name": "A"},
            {"stock_id": "1103", "stock_name": "C"},
        ]).to_csv(self.stocks, index=False, encoding="utf-8-sig")
        self.client = FakeClient()
        self.processed = set()

        def revenue(client, stock_id, _name):
            client.budget.consume()
            return 0, 0

        def financials(client, stock_id, _name):
            client.budget.consume()
            self.processed.add(stock_id)
            return 0, 0, False, None

        self.revenue_patch = patch.object(batch, "update_revenue", side_effect=revenue)
        self.financial_patch = patch.object(batch, "update_financials", side_effect=financials)
        self.local_complete_patch = patch.object(batch, "completed_from_local_data", return_value=set())
        self.local_status_patch = patch.object(
            batch, "_local_status",
            side_effect=lambda stock_id: (stock_id in self.processed,
                                          stock_id in self.processed,
                                          stock_id in self.processed),
        )
        for active in (self.revenue_patch, self.financial_patch,
                       self.local_complete_patch, self.local_status_patch):
            active.start()

    def tearDown(self):
        patch.stopall()
        self.temp.cleanup()

    def run_batch(self, budget=100):
        return batch.run_fundamentals_batch(
            budget, stocks_path=self.stocks, progress_path=self.progress,
            client_factory=lambda: self.client,
        )

    def test_progress_file_is_created_with_required_fields(self):
        state = self.run_batch()
        saved = json.loads(self.progress.read_text(encoding="utf-8"))
        self.assertTrue(self.progress.parent.exists())
        for key in ("completed_stock_ids", "failed_stock_ids", "last_attempted_stock_id",
                    "completed_count", "remaining_count", "last_run_api_calls",
                    "total_api_calls_estimated", "updated_at"):
            self.assertIn(key, saved)
        self.assertEqual(state["last_run"]["attempted_stocks"], 3)

    def test_completed_stock_is_skipped(self):
        self.progress.parent.mkdir(parents=True)
        self.progress.write_text(json.dumps({"completed_stock_ids": ["1101"]}), encoding="utf-8")
        self.run_batch()
        self.assertEqual(self.processed, {"1102", "1103"})

    def test_api_budget_stops_without_crashing(self):
        state = self.run_batch(budget=2)
        self.assertEqual(state["last_run_api_calls"], 2)
        self.assertEqual(state["last_run"]["attempted_stocks"], 1)
        self.assertEqual(state["last_run"]["completed_stocks"], 1)

    def test_second_run_continues_with_next_incomplete_stock(self):
        first = self.run_batch(budget=2)
        self.assertEqual(first["last_attempted_stock_id"], "1101")
        self.client = FakeClient()
        second = self.run_batch(budget=2)
        self.assertEqual(second["last_attempted_stock_id"], "1102")

    def test_single_stock_exception_does_not_stop_batch(self):
        original = batch.update_revenue

        def fail_first(client, stock_id, name):
            if stock_id == "1101":
                raise ValueError("bad row")
            return original(client, stock_id, name)

        with patch.object(batch, "update_revenue", side_effect=fail_first):
            state = self.run_batch()
        self.assertIn("1102", self.processed)
        self.assertIn("1103", self.processed)
        self.assertEqual(state["failure_reasons"]["1101"], "parse_error")

    def test_failed_progress_replace_preserves_previous_file(self):
        self.progress.parent.mkdir(parents=True)
        original = '{"completed_stock_ids": ["1101"]}'
        self.progress.write_text(original, encoding="utf-8")
        state = batch.load_progress(self.progress)
        with patch.object(Path, "replace", side_effect=OSError("locked")):
            with self.assertRaises(OSError):
                batch.save_progress(state, self.progress)
        self.assertEqual(self.progress.read_text(encoding="utf-8"), original)

    def test_client_logs_never_include_token(self):
        token = "must-not-appear-in-logs"

        class Response:
            status_code = 403

            def raise_for_status(self):
                pass

        class Session:
            headers = {}

            def get(self, *_args, **_kwargs):
                return Response()

            def close(self):
                pass

        client = FinMindClient(token, ApiBudget(path=self.root / "budget.json"), Session())
        with self.assertLogs("finmind_client", level="WARNING") as captured:
            client.get("income", "1101", "2024-01-01")
        self.assertNotIn(token, "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
