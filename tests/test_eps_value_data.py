import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from eps_value_data import build_payload, write_payload


class EpsValueDataTests(unittest.TestCase):
    def test_local_payload_keeps_only_supported_annual_basic_eps_and_daily_prices(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            root = Path(directory)
            (root / "data/annual_financials").mkdir(parents=True)
            (root / "data/state").mkdir(parents=True)
            (root / "data/prices").mkdir(parents=True)
            with (root / "data/annual_financials/history.csv").open("w", newline="", encoding="utf-8") as target:
                writer = csv.DictWriter(target, fieldnames=("stock_id", "stock_name", "year", "annual_eps",
                    "eps_method", "eps_basis", "eps_statement_scope", "updated_at", "source"))
                writer.writeheader()
                for year, eps in ((2024, 10), (2025, 12)):
                    writer.writerow({"stock_id":"2330", "stock_name":"台積電", "year":year,
                        "annual_eps":eps, "eps_method":"official_verified:issuer", "eps_basis":"basic",
                        "eps_statement_scope":"consolidated", "source":"issuer"})
                writer.writerow({"stock_id":"9999", "year":2025, "annual_eps":4,
                    "eps_method":"FinMind:quarterly_basic_eps_sum_fallback", "eps_basis":"diluted"})
            (root / "data/state/annual_eps_verified.json").write_text(json.dumps({
                "2330:2024":{"annual_eps":10,"definition":"basic annual EPS","source":"issuer"},
                "2330:2025":{"annual_eps":12,"definition":"basic annual EPS","source":"issuer"},
            }), encoding="utf-8")
            (root / "data/prices/2026.csv").write_text(
                "date,stock_id,close\n2026-01-02,2330,100\n2026-01-05,2330,101\n", encoding="utf-8")
            payload = build_payload(root, max_price_rows=1)
            stock = payload["stocks"]["2330"]
            self.assertEqual(payload["dates"], ["2026-01-05"])
            self.assertEqual(stock["closes"], [101.0])
            self.assertEqual([row["year"] for row in stock["annual_eps"]], [2024, 2025])
            self.assertTrue(all(row["verified_official"] for row in stock["annual_eps"]))
            self.assertNotIn("9999", payload["stocks"])
            destination = write_payload(root)
            self.assertTrue(destination.exists())
            self.assertFalse(destination.with_name(destination.name + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
