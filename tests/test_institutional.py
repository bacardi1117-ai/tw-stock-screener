"""Official institutional schemas and complete-window semantics."""

from pathlib import Path
import json
import sys
import tempfile
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from institutional_factors import make_context, stock_factors
from strategy_engine import evaluate_strategy, load_config
from update_institutional import (SourceFormatError, TPEX_FIELDS, TWSE_FIELDS,
                                  parse_tpex, parse_twse, update_institutional)


class InstitutionalTests(unittest.TestCase):
    def test_twse_uses_named_columns_and_preserves_official_zero(self):
        fields = list(TWSE_FIELDS.values())[::-1]
        values = {"證券代號": "2330", "證券名稱": "台積電",
                  "外陸資買進股數(不含外資自營商)": "1,000",
                  "外陸資賣出股數(不含外資自營商)": "1,000",
                  "外陸資買賣超股數(不含外資自營商)": "0",
                  "投信買進股數": "250", "投信賣出股數": "50", "投信買賣超股數": "200"}
        payload = {"stat": "OK", "date": "20261016", "fields": fields,
                   "data": [[values[field] for field in fields]]}
        frame = parse_twse(payload, "2026-10-16", "official", {"2330"})
        self.assertEqual((frame.iloc[0].foreign_net, frame.iloc[0].trust_net), (0, 200))
        payload["date"] = "20261015"
        with self.assertRaises(SourceFormatError):
            parse_twse(payload, "2026-10-16", "official", {"2330"})

    def test_tpex_qualified_headers_disambiguate_repeated_net_names(self):
        headers = list(TPEX_FIELDS.values())[::-1]
        values = {"代號": "6187", "名稱": "萬潤",
                  "外資及陸資(不含外資自營商)-買進股數": "1,136,657",
                  "外資及陸資(不含外資自營商)-賣出股數": "1,029,479",
                  "外資及陸資(不含外資自營商)-買賣超股數": "107,178",
                  "投信-買進股數": "81,225", "投信-賣出股數": "170,000",
                  "投信-買賣超股數": "-88,775"}
        csv_text = "115年10月16日 三大法人日交易資訊\n" + ",".join(headers) + "\n"
        csv_text += ",".join('"'+values[h]+'"' for h in headers) + "\n"
        frame = parse_tpex(csv_text.encode("ms950"), "2026-10-16", "official", {"6187"})
        self.assertEqual((frame.iloc[0].foreign_net, frame.iloc[0].trust_net), (107178, -88775))
        bad = csv_text.replace("投信-買賣超股數", "買賣超股數")
        with self.assertRaises(SourceFormatError):
            parse_tpex(bad.encode("ms950"), "2026-10-16", "official", {"6187"})

    def test_missing_row_or_field_never_becomes_zero_or_older_observation(self):
        dates = pd.date_range("2026-09-14", periods=25, freq="B").strftime("%Y-%m-%d").tolist()
        prices = pd.DataFrame({"date": dates, "market": "TWSE"})
        rows = pd.DataFrame({"date": dates, "market": "TWSE", "stock_id": "2330",
                             "foreign_net": [100] * 25, "trust_net": [0] * 25})
        progress = {"dates": {f"{d}:TWSE": {"status": "saved"} for d in dates}}
        full = stock_factors("TWSE", "2330", dates[-1], make_context(prices, rows, progress))
        self.assertEqual((full["foreign_plus_trust_20d"], full["trust_10d"]), (2000, 0))
        missing = rows.loc[rows.date != dates[-15]]
        incomplete = stock_factors("TWSE", "2330", dates[-1], make_context(prices, missing, progress))
        self.assertTrue(pd.isna(incomplete["foreign_plus_trust_20d"]))
        self.assertEqual(incomplete["trust_10d"], 0)
        self.assertIn("官方個股缺列", incomplete["institutional_missing_reason"])
        with_gap = rows.copy()
        with_gap.loc[with_gap.date == dates[-1], "trust_net"] = float("nan")
        result = stock_factors("TWSE", "2330", dates[-1], make_context(prices, with_gap, progress))
        self.assertTrue(pd.isna(result["trust_10d"]))
        self.assertIn("官方欄位缺值", result["institutional_missing_reason"])

    def test_strategy_d_pass_fail_and_missing_without_changing_thresholds(self):
        strategy = load_config()["strategy_d"]
        self.assertEqual(strategy["conditions"]["foreign_plus_trust_20d"]["value"], 0)
        self.assertEqual(strategy["conditions"]["trust_10d"]["value"], 0)
        row = {"foreign_plus_trust_20d": 0, "trust_10d": 0,
               "close": 101, "ma20": 100, "ma60": 90, "ma120": 80,
               "avg_volume_20": 1000, "avg_volume_60": 900,
               "distance_to_60d_high": -2}
        self.assertEqual(evaluate_strategy(row, strategy), "pass")
        self.assertEqual(evaluate_strategy(dict(row, trust_10d=-1), strategy), "fail")
        self.assertEqual(evaluate_strategy(dict(row, trust_10d=None,
                                                institutional_missing_reason="官方個股缺列"), strategy),
                         "missing_data")

    def test_unpublished_official_day_stays_retryable_without_zero_rows(self):
        class Response:
            status_code = 200
            url = "https://www.twse.com.tw/rwd/zh/fund/T86"
            def raise_for_status(self):
                pass
            def json(self):
                return {"stat": "No data", "date": "20261016"}

        class Session:
            def get(self, *_args, **_kwargs):
                return Response()

        with tempfile.TemporaryDirectory(dir=ROOT / "data") as directory:
            root = Path(directory)
            (root / "data/prices").mkdir(parents=True)
            (root / "data/market").mkdir(parents=True)
            pd.DataFrame([{"date": "2026-10-16", "market": "TWSE"}]).to_csv(
                root / "data/prices/2026.csv", index=False)
            pd.DataFrame([{"stock_id": "2330", "market": "TWSE"}]).to_csv(
                root / "data/market/stocks.csv", index=False)
            result = update_institutional(root, days=20, start="2026-10-16",
                                          end="2026-10-16", session=Session(),
                                          sleep=lambda *_: None, request_interval=0)
            progress = json.loads((root / "data/state/institutional_progress.json").read_text())
            self.assertEqual((result["requested"], result["failed"]), (1, 1))
            self.assertEqual(progress["dates"]["2026-10-16:TWSE"]["status"], "retryable")
            self.assertFalse((root / "data/institutional/2026.csv").exists())


if __name__ == "__main__":
    unittest.main()
