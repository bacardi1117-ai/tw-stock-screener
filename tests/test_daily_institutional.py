"""Recent price-day selection for the daily Strategy D workflow."""

from datetime import date
from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from daily_institutional import missing_price_dates


class DailyInstitutionalTests(unittest.TestCase):
    def test_missing_market_is_retried_without_treating_holiday_as_zero(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "data") as directory:
            path = Path(directory) / "2026.csv"
            pd.DataFrame([
                {"date": "2026-10-14", "market": "TWSE"},
                {"date": "2026-10-14", "market": "TPEx"},
                {"date": "2026-10-15", "market": "TWSE"},
            ]).to_csv(path, index=False)
            expected = [(date(2026, 10, 15), {"TPEx"}),
                        (date(2026, 10, 16), {"TWSE", "TPEx"})]
            self.assertEqual(missing_price_dates(directory, date(2026, 10, 16), 3), expected)
            self.assertEqual(missing_price_dates(directory, date(2026, 10, 16), 3), expected)

    def test_weekends_are_not_invented_as_market_days(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "data") as directory:
            missing = missing_price_dates(directory, date(2026, 10, 18), 3)
            self.assertEqual(missing, [(date(2026, 10, 16), {"TWSE", "TPEx"})])


if __name__ == "__main__":
    unittest.main()
