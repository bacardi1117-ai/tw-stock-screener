"""Official zero observations, independent components and offline repair safety."""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from dividend_coverage import resolve_components
from history_batch import annual_rows, dividend_rows, merge_history, publish_history
from repair_history_official import repair_official
from update_dividends import dividend_metrics, save_dividends
from test_history_batch import INCOME, FLOWS, divs


def record(cash, stock=0):
    return dict(CashEarningsDistribution=cash, CashStatutorySurplus=0,
                StockEarningsDistribution=stock, StockStatutorySurplus=0)


def proof(**kwargs):
    return dict(source="https://example.test/official", checked_at="2026-10-18",
                year_basis="earnings_attribution", **kwargs)


class OfficialHistoryTests(unittest.TestCase):
    def temp(self):
        directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def test_absence_is_not_zero_official_explicit_zero_is_complete(self):
        a, _ = resolve_components({})
        self.assertTrue(math.isnan(a["cash_dividend"]))
        a, _ = resolve_components({}, proof(periods={"A": {"cash_dividend": 0, "stock_dividend": 0}}))
        self.assertEqual(a, dict(cash_dividend=0, stock_dividend=0))
        rows = dividend_rows("1", "S", [], [], verified={"1:2025": proof(periods={"A": {"cash_dividend": 0, "stock_dividend": 0}})})
        self.assertTrue(rows[-1]["annual_complete"])
        self.assertEqual(rows[-1]["dividend_status"], "zero")
        metrics = dividend_metrics(pd.DataFrame(rows), latest_dividend_year=2025)
        self.assertEqual(metrics["dividend_history_years_available"], 1)
        self.assertTrue(math.isnan(metrics["dividend_years_5"]))

    def test_half_year_and_quarter_periods_zero_evidence(self):
        a, _ = resolve_components({"H2": record(1)}, proof(periods={"H1": {"cash_dividend": 0, "stock_dividend": 0}}))
        self.assertEqual(a["cash_dividend"], 1)
        a, _ = resolve_components({"Q2": record(2), "Q4": record(3)}, proof(periods={
            "Q1": {"cash_dividend": 0, "stock_dividend": 0}, "Q3": {"cash_dividend": 0, "stock_dividend": 0}}))
        self.assertEqual(a["cash_dividend"], 5)
        a, _ = resolve_components({"Q2": record(2), "Q4": record(3)})
        self.assertTrue(math.isnan(a["cash_dividend"]))

    def test_annual_half_overlap_does_not_double_count(self):
        periods = {"A": record(11.5, .5), "H1": record(4, 0), "H2": record(7.5, .5)}
        missing, _ = resolve_components(periods)
        self.assertTrue(math.isnan(missing["cash_dividend"]))
        amounts, _ = resolve_components(periods, proof(components={
            "cash_dividend": dict(annual_value=11.5), "stock_dividend": dict(annual_value=.5)}))
        self.assertEqual(amounts, dict(cash_dividend=11.5, stock_dividend=.5))

    def test_annual_quarter_overlap_and_revisions(self):
        records = [dict(record(2), year=f"114年第{q}季", AnnouncementDate="2026-01-01") for q in range(1, 5)]
        records += [dict(record(1), year="114年第4季", AnnouncementDate="2025-12-31"),
                    dict(record(8), year="114年")]
        rows = dividend_rows("1", "S", records, [], verified={"1:2025": proof(components={
            "cash_dividend": dict(annual_value=8), "stock_dividend": dict(annual_value=0)})})
        self.assertEqual(rows[-1]["cash_dividend"], 8)
        self.assertEqual(rows[-1]["stock_dividend"], 0)

    def test_cash_stock_are_independent_unknown_component_remains_null(self):
        amounts, _ = resolve_components({"A": record(4, None)})
        self.assertEqual(amounts["cash_dividend"], 4)
        self.assertTrue(math.isnan(amounts["stock_dividend"]))
        amounts, _ = resolve_components({"A": record(0, .5), "H1": record(4), "H2": record(7.5)},
                                        proof(components={"cash_dividend": dict(annual_value=11.5)}))
        self.assertEqual(amounts["cash_dividend"], 11.5)
        self.assertTrue(math.isnan(amounts["stock_dividend"]))

    def test_disjoint_cash_annual_stock_half_components(self):
        cash_only = dict(CashEarningsDistribution=4, CashStatutorySurplus=0)
        stock_only = lambda value: dict(StockEarningsDistribution=value, StockStatutorySurplus=0)
        amounts, _ = resolve_components({"A": cash_only, "H1": stock_only(.2), "H2": stock_only(.3)})
        self.assertEqual(amounts, dict(cash_dividend=4, stock_dividend=.5))

    def test_rounded_official_value_preserves_cached_precision(self):
        amounts, _ = resolve_components({"H2": record(10.21394967)}, proof(components={
            "cash_dividend": dict(annual_value=10.21, preserve_periods=["H2"], display_tolerance=.005),
            "stock_dividend": dict(annual_value=0, preserve_periods=["H2"])}))
        self.assertEqual(amounts["cash_dividend"], 10.21394967)
        with self.assertRaises(ValueError):
            resolve_components({"H2": record(11)}, proof(components={
                "cash_dividend": dict(annual_value=10.21, preserve_periods=["H2"], display_tolerance=.005)}))

    def test_official_zero_does_not_override_conflicting_paid_cache(self):
        with self.assertRaises(ValueError):
            resolve_components({"A": record(1)}, proof(periods={"A": {"cash_dividend": 0}}))
        with self.assertRaises(ValueError):
            resolve_components({}, {"components": {"cash_dividend": dict(annual_value=0)}})

    def test_partial_merge_recovers_components_and_preserves_evidence(self):
        path = self.temp() / "history.csv"
        old = dividend_rows("1", "S", [dict(record(3, None), year="114年")], [])
        merge_history(path, old, True)
        new = dividend_rows("1", "S", [dict(record(None, .5), year="114年")], [])
        merged = merge_history(path, new, True)
        row = merged.loc[merged.year == 2025].iloc[0]
        self.assertEqual(row.cash_dividend, 3)
        self.assertEqual(row.stock_dividend, .5)
        self.assertTrue(row.annual_complete)
        self.assertEqual(row.total_dividend, 3.5)

    def test_complete_merge_preserves_round_trip_amount_precision(self):
        path = self.temp() / "history.csv"
        rows = dividend_rows("1", "S", divs(10.273452350000002), [])
        merge_history(path, rows, True)
        saved = merge_history(path, dividend_rows("1", "S", divs(10.27345235), []), True)
        self.assertEqual(saved.iloc[-1].cash_dividend, 10.273452350000002)

    def test_retained_legacy_amount_is_not_evidence_of_full_year(self):
        from repair_history_official import missing_details
        annual = pd.DataFrame(annual_rows("1", "S", INCOME, FLOWS))
        dividends = pd.DataFrame([dict(stock_id="1", year=2025, cash_dividend=1, stock_dividend=0,
                                       annual_complete=None, periods=None)])
        detail = missing_details(annual, dividends, "1", {2025: "Q2,Q3,Q4"})
        last = detail["dividends"][-1]
        self.assertEqual(last["reason"], "incomplete_or_overlapping_periods")
        self.assertEqual(last["missing_components"], [])
        self.assertEqual(last["unverified_components"], ["cash_dividend", "stock_dividend"])

    def test_daily_dividend_save_retains_verified_evidence(self):
        root = self.temp()
        old = dividend_rows("1", "S", [], [], verified={"1:2025": proof(periods={"A": {"cash_dividend": 0, "stock_dividend": 0}})})
        save_dividends(pd.DataFrame(old), root)
        save_dividends(pd.DataFrame([dict(stock_id="1", year=2025, cash_dividend=9, stock_dividend=0)]), root)
        row = pd.read_csv(root / "history.csv").query("year == 2025").iloc[0]
        self.assertEqual(row.cash_dividend, 0)
        self.assertIn("example.test/official", row.coverage_evidence)

    def test_known_official_conflict_blocks_completion_without_erasing_amount(self):
        directory = self.temp(); path = directory / "history.csv"
        original = dividend_rows("1", "S", divs(1.34714912), [])
        merge_history(path, original, True)
        evidence = proof(review_required_components=["cash_dividend"], review_note="Official 1.5 vs cached 1.34714912")
        reviewed = dividend_rows("1", "S", divs(1.34714912), [], verified={"1:2025": evidence})
        saved = merge_history(path, reviewed, True)
        row = saved.loc[saved.year == 2025].iloc[0]
        self.assertFalse(row.annual_complete)
        self.assertEqual(row.cash_dividend, 1.34714912)
        self.assertEqual(row.cash_coverage_method, "source_conflict_pending_review")
        save_dividends(pd.DataFrame(original), directory)
        row = pd.read_csv(path).query("year == 2025").iloc[0]
        self.assertFalse(row.annual_complete)
        self.assertTrue(row.source_review_required)

    def test_eps_scope_basic_and_annual_guards(self):
        valid = {f"1:{y}": dict(annual_eps=3, source="official", statement_scope="consolidated", eps_basis="basic",
                 period_start=f"{y}-01-01", period_end=f"{y}-12-31", currency="TWD") for y in (2023, 2024, 2025)}
        self.assertEqual(annual_rows("1", "S", INCOME, FLOWS, valid)[-1]["annual_eps"], 3)
        for field, value in (("eps_basis", "diluted"), ("period_start", "2025-07-01"), ("statement_scope", "standalone")):
            changed = json.loads(json.dumps(valid)); changed["1:2025"][field] = value
            with self.assertRaises(ValueError): annual_rows("1", "S", INCOME, FLOWS, changed)

    def test_original_successful_company_cache_fixtures(self):
        fixtures = json.loads((ROOT / "tests/fixtures/history_success_cases.json").read_text(encoding="utf8"))
        overrides = json.loads((ROOT / "data/state/annual_eps_verified.json").read_text(encoding="utf8"))
        for sid, sample in fixtures.items():
            annual = annual_rows(sid, sid, INCOME, FLOWS, overrides)
            self.assertEqual([r["annual_eps"] for r in annual], sample["annual_eps"])
            rows = dividend_rows(sid, sid, sample["dividends"], annual)
            self.assertTrue(all(r["annual_complete"] for r in rows))
            for row, cash, stock in zip(rows, sample["cash"], sample["stock"]):
                self.assertEqual(row["cash_dividend"], cash)
                self.assertEqual(row["stock_dividend"], stock)

    def test_hourly_publisher_does_not_stage_unreviewed_source_or_evidence(self):
        root = self.temp()
        for name in ("src/history_batch.py", "data/state/dividend_verified.json", "data/state/history_progress.json"):
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("test", encoding="utf8")
        from subprocess import CompletedProcess
        calls = []
        def fake_git(command, **kwargs):
            calls.append(command)
            output = "main" if command[1] == "branch" else ""
            return CompletedProcess(command, 0, output, "")
        with patch("history_batch.subprocess.run", side_effect=fake_git):
            self.assertIsNone(publish_history(root))
        stage = next(c for c in calls if c[1] == "add")
        self.assertEqual(stage[3:], ["data/state/history_progress.json"])
        self.assertFalse(any(c[1] in ("commit", "push") for c in calls))

    def test_locked_offline_repair_preserves_new_progress_and_skips_completed(self):
        root = self.temp(); state_dir = root / "data/state"; state_dir.mkdir(parents=True)
        cache = root / "data/.historical_coverage"; cache.mkdir(parents=True)
        proposed = root / "evidence"; proposed.mkdir()
        pd.DataFrame([dict(stock_id=s, stock_name="S", eligible=True, market="TWSE") for s in ("1", "2")]).to_csv(state_dir / "fundamentals_universe.csv", index=False)
        verified = {f"1:{y}": proof(periods={"A": {"cash_dividend": 0, "stock_dividend": 0}}) for y in range(2021, 2026)}
        (proposed / "dividend_verified_proposed.json").write_text(json.dumps(verified), encoding="utf8")
        for dataset, payload in (("TaiwanStockFinancialStatements", INCOME), ("TaiwanStockCashFlowsStatement", FLOWS), ("TaiwanStockDividend", [])):
            (cache / f"1_{dataset}.json").write_text(json.dumps(payload), encoding="utf8")
        progress = state_dir / "history_progress.json"
        state = dict(stocks={"1": dict(status="failed", failure_reason="no_data", last_attempt_at="old"),
                             "2": dict(status="completed", last_attempt_at="newer-run")},
                     completed_count=1, remaining_count=1, failed_count=1, retryable_count=0, last_run_api_calls=180)
        progress.write_text(json.dumps(state), encoding="utf8")
        with patch("requests.sessions.Session.request", side_effect=AssertionError("no network")), \
             patch("history_batch.FinMindClient", side_effect=AssertionError("no client")):
            result = repair_official(root, proposed, apply=True)
        after = json.loads(progress.read_text(encoding="utf8"))
        self.assertEqual(result["completed_from_cache"], 1)
        self.assertEqual(after["stocks"]["2"], state["stocks"]["2"])
        self.assertEqual(after["last_run_api_calls"], 180)
        self.assertEqual(after["stocks"]["1"]["last_attempt_at"], "old")
        self.assertEqual(after["completed_count"], 2)
        progress.write_text("invalid but untouched", encoding="utf8")
        with patch("repair_history_official.ApiBudget._lock", side_effect=OSError("busy")):
            with self.assertRaises(OSError): repair_official(root, proposed, apply=True)
        self.assertEqual(progress.read_text(encoding="utf8"), "invalid but untouched")


if __name__ == "__main__":
    unittest.main()
