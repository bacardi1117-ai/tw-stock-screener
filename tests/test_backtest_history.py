"""Backfill merge and restart guarantees without contacting an official API."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import date

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import backtest_history as bh
from market_history import SourceStopped


def quote(day, price, stock_id="2330"):
    return dict(date=day, stock_id=stock_id, stock_name="測試", market="TWSE",
                open=price, high=price, low=price, close=price, volume=1000,
                turnover=price*1000 if price is not None else None, change=0)


class BacktestHistoryTests(unittest.TestCase):
    def test_merge_preserves_valid_prices_and_repairs_only_invalid(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as name:
            folder = Path(name); cache = folder / "cache"; cache.mkdir()
            old = [quote("2025-12-31", 100), quote("2026-01-02", None)]
            for year, rows in [(2025,old[:1]),(2026,old[1:])]:
                pd.DataFrame(rows).to_csv(folder/f"{year}.csv",index=False)
            pd.DataFrame([quote("2025-12-31",101)]).to_csv(cache/"2025-12-31-TWSE.csv",index=False)
            pd.DataFrame([quote("2026-01-02",102),quote("2026-01-02",20,"2317")]).to_csv(cache/"2026-01-02-TWSE.csv",index=False)
            with patch.object(bh,"PRICES_DIR",folder), patch.object(bh,"CACHE",cache):
                result = bh.merge_cache({2025,2026})
                self.assertEqual(pd.read_csv(folder/"2025.csv").iloc[0].close,100)
                self.assertEqual(result["2025"]["preserved_conflicts"],1)
                self.assertEqual(result["2026"]["repaired"],1)
                self.assertEqual(result["2026"]["added"],1)
                second = bh.merge_cache({2025,2026})
                self.assertEqual(second["2026"]["added"],0)
                self.assertEqual(second["2026"]["repaired"],0)

    def test_interrupted_source_retries_on_restart_without_repeating_saved_source(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as name:
            folder=Path(name); stocks=folder/"stocks.csv"
            pd.DataFrame([{"stock_id":"2330","market":"TWSE"}]).to_csv(stocks,index=False)
            patches = dict(CACHE=folder/"cache", PROGRESS=folder/"progress.json", PRICES_DIR=folder, STOCKS_PATH=stocks)
            with patch.multiple(bh,**patches), patch.object(bh,"_normalize",return_value=pd.DataFrame([quote("2025-12-31",100)])):
                with patch.object(bh,"_request",side_effect=[[{}],SourceStopped("HTTP 429")]):
                    with self.assertRaises(SourceStopped): bh.run(date(2025,12,31),date(2025,12,31))
                saved=json.loads((folder/"progress.json").read_text())
                self.assertEqual(saved["dates"]["2025-12-31:TWSE"]["status"],"saved")
                self.assertEqual(saved["dates"]["2025-12-31:TPEx"]["status"],"retryable")
                with patch.object(bh,"_request",return_value=[]) as request:
                    result=bh.run(date(2025,12,31),date(2025,12,31))
                    self.assertEqual(request.call_count,1)
                    self.assertEqual(request.call_args.args[1],"TPEx")
                    self.assertEqual(result["stop_reason"],"range_completed")


if __name__ == "__main__": unittest.main()
