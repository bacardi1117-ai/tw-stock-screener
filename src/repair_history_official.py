"""Apply reviewed official evidence to cached history, with no API requests.

This is an explicit local repair command, not a second fetching scheduler.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil

import pandas as pd

from config import PROJECT_ROOT
from finmind_client import ApiBudget
from historical_coverage import atomic_json
from history_batch import annual_rows, dividend_rows, merge_history, now, stored_complete
from repair_history_cache import cached_payloads, refresh_counts


def read_json(path):
    return json.loads(path.read_text(encoding="utf8")) if path.exists() else {}


def missing_details(annual, dividends, sid, observed_periods=None):
    a = annual.loc[annual.stock_id == sid]
    d = dividends.loc[dividends.stock_id == sid]
    missing = {field: [y for y in years if a.loc[a.year == y, field].empty or
                      pd.isna(a.loc[a.year == y, field].iloc[-1])]
               for field, years in (("annual_eps", (2023, 2024, 2025)),
                                    ("annual_operating_cash_flow", (2023, 2024, 2025)))}
    missing["dividends"] = []
    for y in range(2021, 2026):
        row = d.loc[d.year == y]
        if row.empty or str(row.iloc[-1].annual_complete).lower() != "true":
            periods = "" if row.empty or pd.isna(row.iloc[-1].get("periods")) else str(row.iloc[-1].periods)
            # A retained legacy amount can have no annual metadata. Consult
            # cached observations instead of mistaking that for source absence.
            if not periods and observed_periods is not None:
                periods = observed_periods.get(y, "")
            missing_amounts = [f for f in ("cash_dividend", "stock_dividend")
                               if row.empty or pd.isna(row.iloc[-1][f])]
            missing["dividends"].append(dict(year=y, periods=periods,
                reason="source_conflict" if not row.empty and str(row.iloc[-1].get("source_review_required", "")).lower() == "true" else
                       "incomplete_or_overlapping_periods" if periods else
                       "unverified_annual_coverage" if not missing_amounts else "source_not_returned",
                missing_components=missing_amounts,
                unverified_components=[f for kind, f in (("cash", "cash_dividend"), ("stock", "stock_dividend"))
                    if row.empty or str(row.iloc[-1].get(f"{kind}_complete", "")).lower() != "true"]))
    return missing


def metrics(frame, ids):
    from strategy_engine import evaluate_frame
    selected = evaluate_frame(frame.loc[frame.stock_id.isin(ids)])
    result = {
        "annual_eps_3y": int(frame[[f"annual_eps_{y}" for y in (2023, 2024, 2025)]].notna().all(axis=1).sum()),
        "annual_ocf_3y": int(frame[[f"annual_ocf_{y}" for y in (2023, 2024, 2025)]].notna().all(axis=1).sum()),
        "dividend_5y": int(frame.dividend_history_years_available.eq(5).sum()),
    }
    for letter in ("c", "e"):
        counts = selected[f"strategy_{letter}"].value_counts()
        result[f"strategy_{letter}"] = {k: int(counts.get(k, 0)) for k in ("pass", "fail", "missing_data")}
    return result


def repair_official(root=PROJECT_ROOT, evidence_directory=None, apply=False, rebuild=False):
    root = Path(root)
    evidence_directory = Path(evidence_directory or root / "data/.historical_coverage/official_review")
    # Reading progress and installing evidence both happen only after acquiring
    # the exact OS lock used by history-batch. Preserve the last API run counters.
    with ApiBudget(path=root / "data/.history_batch_guard.json")._lock():
        return _repair(root, evidence_directory, apply, rebuild)


def _repair(root, evidence_directory, apply, rebuild):
    state_path = root / "data/state/history_progress.json"
    state = read_json(state_path)
    original_entries = json.loads(json.dumps(state["stocks"]))
    universe = pd.read_csv(root / "data/state/fundamentals_universe.csv", dtype={"stock_id": str})
    eligible = universe.loc[universe.eligible.astype(str).str.lower().isin(["true", "1"])].drop_duplicates("stock_id")
    ids = eligible.stock_id.tolist()
    stocks = eligible.set_index("stock_id")
    eps_path, div_path = (root / f"data/state/{name}.json" for name in ("annual_eps_verified", "dividend_verified"))
    eps_proposed = read_json(evidence_directory / "annual_eps_verified_proposed.json")
    div_proposed = read_json(evidence_directory / "dividend_verified_proposed.json")
    overrides = read_json(eps_path) | eps_proposed
    verified = read_json(div_path) | div_proposed
    evidence_ids = {k.split(":")[0] for k in div_proposed} | {
        k.split(":")[0] for k, v in eps_proposed.items() if v.get("statement_scope")}
    targets = [sid for sid in ids if sid in evidence_ids and
               state["stocks"].get(sid, {}).get("status") == "failed"]
    report = dict(started_at=now(), api_calls=0, applied=apply, targets=targets, results=[],
                  before={k: state.get(k) for k in ("completed_count", "remaining_count", "failed_count", "retryable_count")})
    before_factors = None
    if rebuild:
        from calculate_factors import calculate_factors
        before_factors = calculate_factors()
        report["metrics_before"] = metrics(before_factors, ids)
    if apply:
        backup = root / "data/.historical_coverage/repair_backups" / ("official-" + now().replace(":", "-"))
        backup.mkdir(parents=True, exist_ok=False)
        for path in (state_path, eps_path, div_path, root / "data/annual_financials/history.csv",
                     root / "data/dividends/history.csv", root / "docs/data/latest.json"):
            if path.exists():
                dest = backup / path.relative_to(root)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
        report["backup_directory"] = backup.relative_to(root).as_posix()
        atomic_json(eps_path, overrides)
        atomic_json(div_path, verified)
    annual_path = root / "data/annual_financials/history.csv"
    dividend_path = root / "data/dividends/history.csv"
    old_a = pd.read_csv(annual_path, dtype={"stock_id": str}, float_precision="round_trip") if annual_path.exists() else pd.DataFrame()
    old_d = pd.read_csv(dividend_path, dtype={"stock_id": str}, float_precision="round_trip") if dividend_path.exists() else pd.DataFrame()
    saved_a, saved_d = old_a, old_d
    for sid in targets:
        payloads, missing = cached_payloads(root, sid)
        if missing:
            report["results"].append(dict(stock_id=sid, missing_cache=missing, completed=False))
            continue
        stock = stocks.loc[sid]
        a = annual_rows(sid, stock.stock_name, payloads["TaiwanStockFinancialStatements"],
                        payloads["TaiwanStockCashFlowsStatement"], overrides)
        d = dividend_rows(sid, stock.stock_name, payloads["TaiwanStockDividend"], a, stock.market, verified)
        if apply:
            saved_a = merge_history(annual_path, a)
            saved_d = merge_history(dividend_path, d, dividend=True)
        else:
            saved_a = pd.concat([saved_a, pd.DataFrame(a)]).drop_duplicates(["stock_id", "year"], keep="last")
            saved_d = pd.concat([saved_d, pd.DataFrame(d)]).drop_duplicates(["stock_id", "year"], keep="last")
        complete = bool(stored_complete(saved_a, saved_d, sid))
        detail = missing_details(saved_a, saved_d, sid, {r["year"]: r["periods"] for r in d})
        result = dict(stock_id=sid, stock_name=stock.stock_name, completed=complete, missing=detail)
        report["results"].append(result)
        if apply:
            entry = state["stocks"][sid]
            reason = None if complete else "no_data" if any(
                not r["periods"] for r in detail["dividends"]) else "unsupported_format"
            entry.update(official_repaired_at=now(), previous_failure_reason=entry.get("failure_reason"),
                         status="completed" if complete else "failed", failure_reason=reason,
                         official_repair_details=detail)
            refresh_counts(state, ids)
            state["updated_at"] = now()
            atomic_json(state_path, state)
    # All rows outside the explicit repair targets must retain their amounts.
    for before, after in ((old_a, saved_a), (old_d, saved_d)):
        if not before.empty:
            cols = before.columns.tolist()
            pd.testing.assert_frame_equal(
                before.loc[~before.stock_id.isin(targets), cols].reset_index(drop=True),
                after.loc[~after.stock_id.isin(targets), cols].reset_index(drop=True), check_dtype=False)
    report["unrelated_entries_preserved"] = all(state["stocks"][sid] == entry for sid, entry in original_entries.items() if sid not in targets)
    report["completed_from_cache"] = sum(r["completed"] for r in report["results"])
    report["after"] = {k: state.get(k) for k in report["before"]}
    report["remaining_failures"] = []
    for sid in ids:
        if state["stocks"].get(sid, {}).get("status") != "failed":
            continue
        payloads, missing = cached_payloads(root, sid)
        observations = {} if missing else {r["year"]: r["periods"] for r in dividend_rows(
            sid, stocks.loc[sid].stock_name, payloads["TaiwanStockDividend"], [], verified=verified)}
        report["remaining_failures"].append(dict(stock_id=sid, stock_name=stocks.loc[sid].stock_name,
            failure_reason=state["stocks"][sid].get("failure_reason"), missing_cache=missing,
            **missing_details(saved_a, saved_d, sid, observations)))
    report["failure_counts"] = dict(Counter(r["failure_reason"] for r in report["remaining_failures"]))
    if rebuild and apply:
        from calculate_factors import calculate_factors, save_factors
        from build_pages import build_pages
        after_factors = calculate_factors()
        fields = ["stock_id", "score_quality", "score_growth", "score_momentum", "score_total", "data_completeness"]
        pd.testing.assert_frame_equal(before_factors[fields].sort_values("stock_id").reset_index(drop=True),
                                      after_factors[fields].sort_values("stock_id").reset_index(drop=True))
        report["qgm_unchanged"] = True
        report["metrics_after"] = metrics(after_factors, ids)
        save_factors(after_factors)
        build_pages(root)
    report["finished_at"] = now()
    if apply:
        state["last_official_repair"] = {k: report[k] for k in ("started_at", "finished_at", "api_calls", "completed_from_cache", "targets")}
        atomic_json(state_path, state)
        atomic_json(root / "data/state/history_official_repair_report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    result = repair_official(apply=args.apply, rebuild=args.rebuild)
    print(json.dumps({k: v for k, v in result.items() if k != "remaining_failures"}, ensure_ascii=False, indent=2))
