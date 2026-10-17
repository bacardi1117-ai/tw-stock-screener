"""Official valuation parsing and annual dividend calculations."""

import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from update_dividends import (dividend_metrics, parse_tpex as parse_tpex_dividends,
                              _merge_rows, parse_twse as parse_twse_dividends,
                              save_dividends)
from update_valuation import parse_tpex as parse_tpex_valuation, parse_twse
from strategy_engine import (evaluate_strategy, load_config, strategy_data_completeness,
                             strategy_required_fields)
from scoring import score_factors
import update_valuation


class Phase5BTests(unittest.TestCase):
    def test_twse_valuation_dash_is_missing_not_zero(self):
        payload = {"stat": "OK", "fields": ["證券代號", "證券名稱", "收盤價", "殖利率(%)", "本益比", "股價淨值比"],
                   "data": [["2330", "台積電", "1500", "1.2", "-", "5.1"]]}
        result = parse_twse(payload, pd.Timestamp("2026-10-16").date()).iloc[0]
        self.assertTrue(math.isnan(result.per))
        self.assertEqual(result.pbr, 5.1)
        self.assertEqual(result.dividend_yield, 1.2)

    def test_tpex_valuation_roc_date_and_values(self):
        row = parse_tpex_valuation([{"Date": "1151016", "SecuritiesCompanyCode": "2454",
                                     "CompanyName": "聯發科", "PriceEarningRatio": "18.2",
                                     "YieldRatio": "4.1", "PriceBookRatio": "3.4"}]).iloc[0]
        self.assertEqual((row.date, row.stock_id, row.market), ("2026-10-16", "2454", "TPEx"))
        self.assertEqual((row.per, row.pbr, row.dividend_yield), (18.2, 3.4, 4.1))

    def test_tpex_dividend_parsing_sums_cash_components(self):
        rows = parse_tpex_dividends([{"出表日期": "1150804", "公司代號": "2454", "公司名稱": "聯發科",
                                      "股利年度": "114", "股東配發內容-盈餘分配之現金股利(元/股)": "25",
                                      "股東配發內容-法定盈餘公積、資本公積發放之現金(元/股)": "1",
                                      "股東配發內容-盈餘轉增資配股(元/股)": "0.5"}])
        self.assertEqual(rows[0]["year"], 2025)
        self.assertEqual(rows[0]["cash_dividend"], 26)
        self.assertEqual(rows[0]["stock_dividend"], 0.5)

    def test_twse_board_decisions_are_kept_and_period_dividends_sum(self):
        records = [
            {"公司代號": "2330", "公司名稱": "台積電", "股利年度": "114", "決議（擬議）進度": "董事會決議",
             "股利所屬年(季)度": "年度", "股利所屬期間": "1140101~1140630", "出表日期": "1150101",
             "股東配發-盈餘分配之現金股利(元/股)": "3",
             "股東配發-盈餘轉增資配股(元/股)": "0.5"},
            {"公司代號": "2330", "公司名稱": "台積電", "股利年度": "114", "決議（擬議）進度": "董事會決議",
             "股利所屬年(季)度": "年度", "股利所屬期間": "1140701~1141231", "出表日期": "1150201",
             "股東配發-盈餘分配之現金股利(元/股)": "4",
             "股東配發-盈餘轉增資配股(元/股)": "0.5"},
        ]
        rows = parse_twse_dividends(records)
        merged = _merge_rows(rows, "TWSE", {("2330", 2025): 10})
        self.assertEqual(merged.iloc[0].cash_dividend, 7)
        self.assertEqual(merged.iloc[0].stock_dividend, 1)
        self.assertEqual(merged.iloc[0].total_dividend, 8)
        self.assertEqual(merged.iloc[0].payout_ratio, 70)
        negative_eps = _merge_rows(rows, "TWSE", {("2330", 2025): -10})
        self.assertTrue(math.isnan(negative_eps.iloc[0].payout_ratio))

    def test_dividend_rows_consolidate_to_one_incremental_history_file(self):
        frame = pd.DataFrame([{"stock_id": "2330", "stock_name": "台積電", "market": "TWSE",
                               "year": 2025, "cash_dividend": 4, "stock_dividend": 1,
                               "total_dividend": 5, "annual_eps": 10, "payout_ratio": 40,
                               "source_date": "1150101"}])
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path = Path(folder) / "2025.csv"
            frame.to_csv(path, index=False)
            self.assertEqual(save_dividends(frame, folder), 1)
            saved = pd.read_csv(Path(folder) / "history.csv", dtype={"stock_id": str})
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved.iloc[0].total_dividend, 5)
            self.assertFalse(path.exists())

    def test_five_year_count_consecutive_cagr_tolerance_and_nonpositive_eps(self):
        frame = pd.DataFrame({"year": [2021, 2022, 2023, 2024, 2025],
                              "cash_dividend": [2, 2.5, 3, 3.5, 4],
                              "payout_ratio": [50, 51, 52, 53, float("nan")]})
        result = dividend_metrics(frame, 2025, tolerance_pct=5)
        self.assertEqual(result["dividend_years"], 5)
        self.assertEqual(result["dividend_consecutive_years"], 5)
        self.assertAlmostEqual(result["dividend_growth_3y_cagr"], ((4 / 2.5) ** (1 / 3) - 1) * 100)
        self.assertTrue(result["dividend_non_decreasing_3y"])
        self.assertTrue(math.isnan(result["payout_ratio"]))

    def test_missing_dividend_history_stays_missing(self):
        result = dividend_metrics(pd.DataFrame())
        self.assertTrue(math.isnan(result["dividend_years"]))
        self.assertTrue(math.isnan(result["dividend_growth_3y_cagr"]))

    def test_zero_dividend_is_known_and_missing_cash_is_not_zero(self):
        zero_frame = pd.DataFrame({"year": [2021, 2022, 2023, 2024, 2025],
                                   "cash_dividend": [2, 0, 3, 4, 5],
                                   "payout_ratio": [10, 0, 12, 13, 14]})
        zero_result = dividend_metrics(zero_frame, 2025)
        self.assertEqual(zero_result["dividend_history_years_available"], 5)
        self.assertEqual(zero_result["dividend_years_5"], 4)
        missing_frame = zero_frame.copy()
        missing_frame.loc[missing_frame.year == 2022, "cash_dividend"] = float("nan")
        missing_result = dividend_metrics(missing_frame, 2025)
        self.assertEqual(missing_result["dividend_history_years_available"], 4)
        self.assertTrue(math.isnan(missing_result["dividend_years_5"]))

    def test_five_year_coverage_requires_all_five_non_null_annual_values(self):
        frame = pd.DataFrame({"year": [2021, 2022, 2023, 2024, 2025],
                              "cash_dividend": [1, 0, 2, 3, 4],
                              "payout_ratio": [10, 0, 20, 30, 40]})
        self.assertEqual(dividend_metrics(frame, 2025)["dividend_years_5"], 4)
        frame.loc[frame.year == 2023, "cash_dividend"] = float("nan")
        self.assertTrue(math.isnan(dividend_metrics(frame, 2025)["dividend_years_5"]))

    def test_strategy_c_completeness_ignores_dividend_inputs_and_e_requires_them(self):
        config = load_config()
        c_fields = {"roe": 20, "eps_positive_years": 3,
                    "operating_cash_flow_positive_years": 3, "debt_ratio": 30,
                    "per": 15, "pbr": 2}
        self.assertEqual(strategy_data_completeness(c_fields, config["strategy_c"]), 100)
        self.assertEqual(evaluate_strategy(c_fields, config["strategy_c"]), "pass")
        e_fields = set(strategy_required_fields(config["strategy_e"]))
        self.assertEqual(len(e_fields), 6)
        self.assertTrue({"dividend_years_5", "dividend_yield", "payout_ratio",
                         "dividend_growth_3y", "dividend_min_change_3y_pct",
                         "free_cash_flow_single"}.issubset(e_fields))
        self.assertNotIn("eps_yoy", e_fields)
        self.assertEqual(strategy_data_completeness(c_fields, config["strategy_e"]), 0)
        self.assertEqual(evaluate_strategy(c_fields, config["strategy_e"]), "missing_data")

    def test_missing_or_zero_dividend_does_not_change_qgm(self):
        base = {"roe_quarterly_approx": 15, "gross_margin_single": 30,
                "operating_margin_single": 10, "debt_ratio": 40,
                "operating_cash_flow_single": 100, "free_cash_flow_single": 50,
                "eps_positive_quarters_4": 4, "revenue_yoy": 10,
                "revenue_yoy_3m_avg": 5, "eps_yoy": 10,
                "gross_margin_yoy": 2, "operating_margin_yoy": 1,
                "close": 100, "ma20": 95, "ma60": 90, "ma120": 80,
                "return_20d": 5, "return_60d": 10, "avg_volume_20": 200,
                "avg_volume_60": 100, "distance_to_60d_high": -2}
        missing = score_factors(base)
        known_zero = score_factors(dict(base, dividend_years_5=0, dividend_yield=0,
                                        payout_ratio=0, dividend_growth_3y=0))
        self.assertEqual(missing, known_zero)

    def test_strategy_c_uses_official_per_pbr_and_keeps_missing_per_missing(self):
        strategy = load_config()["strategy_c"]
        row = {"roe": 20, "eps_positive_years": 4,
               "operating_cash_flow_positive_years": 4, "debt_ratio": 30,
               "per": 15, "pbr": 2}
        self.assertEqual(evaluate_strategy(row, strategy), "pass")
        row["per"] = None
        self.assertEqual(evaluate_strategy(row, strategy), "missing_data")

    def test_complete_latest_valuation_day_is_skipped_without_request(self):
        class NoRequests:
            def get(self, *args, **kwargs):
                raise AssertionError("a complete latest date should not be fetched again")

        today = update_valuation.today_in_taiwan()
        day = update_valuation.latest_weekday(today).isoformat()
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root = Path(folder)
            pd.DataFrame([{"date": day, "stock_id": "2330", "market": "TWSE"},
                          {"date": day, "stock_id": "6488", "market": "TPEx"}]).to_csv(
                              root / f"{today.year}.csv", index=False)
            with patch.object(update_valuation, "VALUATION_DIR", root):
                result = update_valuation.update_valuation(session=NoRequests())
        self.assertTrue(result["skipped"])


if __name__ == "__main__":
    unittest.main()
