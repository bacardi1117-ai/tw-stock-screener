import csv
from datetime import date, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
import build_backtest_data as builder


class BuildBacktestDataTests(unittest.TestCase):
    def test_cross_year_manifest_warmup_compression_and_missing_prices(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as name:
            root=Path(name); source=root/"data/prices"; target=root/"docs/data/backtest"
            source.mkdir(parents=True); (root/"data/state").mkdir()
            stocks=root/"stocks.csv"
            stocks.write_text("stock_id,stock_name,market\n2330,台積電,TWSE\n",encoding="utf-8")
            dates=[]; day=date(2025,7,1)
            while len(dates)<140:
                if day.weekday()<5: dates.append(day.isoformat())
                day+=timedelta(days=1)
            for year in (2025,2026):
                with (source/f"{year}.csv").open("w",newline="",encoding="utf-8") as out:
                    writer=csv.writer(out); writer.writerow(builder.FIELDS)
                    for day in dates:
                        if day.startswith(str(year)): writer.writerow([day,"2330",100,101,99,100,1000])
                    if year==2025:writer.writerow(["2025-06-30","2330","",101,99,100,1000])
            with patch.multiple(builder,ROOT=root,SOURCE=source,TARGET=target,STOCKS=stocks):builder.main()
            manifest=json.loads((target/"manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["backtest_start"],dates[120])
            self.assertEqual(manifest["trading_dates"],dates)
            self.assertEqual(manifest["volume_unit"],"shares")
            self.assertEqual(manifest["recent_year_warmup_sessions"],0)
            self.assertEqual(len(json.loads((root/"data/state/backtest_price_exclusions.json").read_text())),1)
            for year in manifest["years"]:
                raw=(target/year["file"]).read_bytes()
                self.assertNotIn(b"\r",raw)
                self.assertEqual(gzip.decompress((target/year["compressed_file"]).read_bytes()),raw)
                self.assertEqual(hashlib.sha256(raw).hexdigest(),year["sha256"])


if __name__=="__main__":unittest.main()
