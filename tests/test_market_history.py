"""Safety checks for historical all-market requests and their backoff."""

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_history import SourceStopped, _request
import update_prices


class Response:
    def __init__(self, status):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return {"date": "20260914", "tables": [{"fields": ["證券代號", "收盤價", "成交股數"],
                                                   "data": [["2330", "100", "1000"]]}]}


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return Response(item)


class MarketHistoryTests(unittest.TestCase):
    def test_official_holiday_response_is_empty_without_retry(self):
        rows = update_prices._table_rows({"stat": "No data"}, {"證券代號"},
                                         date(2026, 9, 25), "TWSE")
        self.assertEqual(rows, [])

    def test_one_successful_batch_sleeps_after_request(self):
        sleeps = []
        session = Session([200])
        counts = {"TWSE": 0, "TPEx": 0}
        rows = _request(session, "TWSE", date(2026, 9, 14), counts, sleeps.append)
        self.assertEqual(rows[0]["證券代號"], "2330")
        self.assertEqual((session.calls, counts["TWSE"]), (1, 1))
        self.assertEqual(sleeps, [1.0])

    def test_429_stops_immediately_without_retry(self):
        sleeps = []
        session = Session([429, 200])
        counts = {"TWSE": 0, "TPEx": 0}
        with self.assertRaises(SourceStopped):
            _request(session, "TWSE", date(2026, 9, 14), counts, sleeps.append)
        self.assertEqual((session.calls, counts["TWSE"]), (1, 1))
        self.assertEqual(sleeps, [1.0])

    def test_403_retries_with_backoff_then_stops(self):
        sleeps = []
        session = Session([403] * 4)
        counts = {"TWSE": 0, "TPEx": 0}
        with self.assertRaises(SourceStopped):
            _request(session, "TWSE", date(2026, 9, 14), counts, sleeps.append)
        self.assertEqual((session.calls, counts["TWSE"]), (4, 4))
        self.assertEqual(sleeps, [1.0, 2, 1.0, 5, 1.0, 10, 1.0])

    def test_timeout_retries_and_counts_each_attempt(self):
        sleeps = []
        session = Session([requests.Timeout("test"), 200])
        counts = {"TWSE": 0, "TPEx": 0}
        self.assertEqual(len(_request(session, "TWSE", date(2026, 9, 14), counts,
                                      sleeps.append)), 1)
        self.assertEqual(counts["TWSE"], 2)
        self.assertEqual(sleeps, [1.0, 2, 1.0])

    def test_yearly_csv_merge_is_incremental_and_preserves_prior_file_on_failure(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as name:
            folder = Path(name)
            path = folder / "2026.csv"
            existing_row = {column: None for column in update_prices.PRICE_COLUMNS}
            existing_row.update(date="2026-10-14", stock_id="2330", stock_name="TSMC",
                                market="TWSE", close=100)
            existing = pd.DataFrame([existing_row])
            existing.to_csv(path, index=False)
            fresh = pd.DataFrame([dict(existing_row, date="2026-09-14", close=90)])
            with patch.object(update_prices, "PRICES_DIR", folder):
                with patch.object(Path, "replace", side_effect=PermissionError("locked")):
                    with self.assertRaises(PermissionError):
                        update_prices.save_prices(fresh, date(2026, 9, 14), sleep=lambda _: None)
                self.assertEqual(pd.read_csv(path).iloc[0]["close"], 100)
                self.assertFalse((folder / "2026.tmp").exists())
                self.assertEqual(update_prices.save_prices(fresh, date(2026, 9, 14)), (1, 0))
                self.assertEqual(update_prices.save_prices(fresh, date(2026, 9, 14)), (0, 1))
            saved = pd.read_csv(path, dtype={"stock_id": str})
            self.assertEqual(len(saved), 2)
            self.assertEqual(saved.duplicated(["date", "stock_id"]).sum(), 0)


if __name__ == "__main__":
    unittest.main()
