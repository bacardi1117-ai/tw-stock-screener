"""Repair parse failures from existing files only; never construct an API client."""
import argparse
import json
import math
import shutil
from pathlib import Path

import pandas as pd

from config import PROJECT_ROOT
from finmind_client import ApiBudget
from historical_coverage import DATASETS, atomic_json
from history_batch import annual_rows, dividend_rows, merge_history, now


def cached_payloads(root, sid):
    found, missing = {}, []
    for dataset in DATASETS:
        path = root / "data/.historical_coverage" / f"{sid}_{dataset}.json"
        if path.exists():
            found[dataset] = json.loads(path.read_text(encoding="utf-8"))
        else:
            missing.append(dataset)
    return found, missing


def diagnose(stock, payloads, overrides):
    sid = str(stock.stock_id)
    annual = annual_rows(sid, stock.stock_name, payloads["TaiwanStockFinancialStatements"],
                         payloads["TaiwanStockCashFlowsStatement"], overrides)
    dividends = dividend_rows(sid, stock.stock_name, payloads["TaiwanStockDividend"],
                             annual, stock.get("market", ""))
    eps_missing = [r["year"] for r in annual if not math.isfinite(r["annual_eps"])]
    ocf_missing = [r["year"] for r in annual if not math.isfinite(r["annual_operating_cash_flow"])]
    dividend_missing = [r["year"] for r in dividends if not r["annual_complete"]]
    details = []
    for row in dividends:
        if row["annual_complete"]:
            continue
        periods = row["periods"]
        if not periods:
            reason = "no_attribution_year_records"
        elif set(periods.split(",")) not in ({"A"}, {"H1", "H2"}, {"Q1", "Q2", "Q3", "Q4"}):
            reason = "incomplete_or_mixed_periods"
        else:
            reason = "missing_distribution_component"
        details.append({"year": row["year"], "reason": reason, "periods": periods})
    complete = not (eps_missing or ocf_missing or dividend_missing)
    failure = None if complete else "no_data" if any(not p for p in payloads.values()) or any(
        not r["periods"] for r in dividends) else "unsupported_format"
    return annual, dividends, {
        "stock_id": sid, "stock_name": stock.stock_name, "failure_reason": failure,
        "missing_eps_years": eps_missing, "missing_ocf_years": ocf_missing,
        "missing_dividend_years": dividend_missing, "dividend_details": details,
        "dataset_rows": {key: len(value) for key, value in payloads.items()},
    }


def refresh_counts(state, ids):
    for status, field in (("completed", "completed_stock_ids"),
                          ("retryable", "retryable_stock_ids"), ("failed", "failed_stock_ids")):
        state[field] = [sid for sid in ids if state["stocks"].get(sid, {}).get("status") == status]
    state.update(eligible_count=len(ids), completed_count=len(state["completed_stock_ids"]),
                 retryable_count=len(state["retryable_stock_ids"]), failed_count=len(state["failed_stock_ids"]))
    state["remaining_count"] = len(ids) - state["completed_count"]


def repair_from_cache(root=PROJECT_ROOT, apply=False):
    root = Path(root)
    if not apply:
        return _repair(root, False)
    # Same OS lock as history-batch; read the queue only AFTER acquiring it.
    # If another run owns the Windows lock this raises rather than overwriting it.
    with ApiBudget(path=root / "data/.history_batch_guard.json")._lock():
        return _repair(root, True)


def _repair(root, apply):
    path = root / "data/state/history_progress.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    universe = pd.read_csv(root / "data/state/fundamentals_universe.csv", dtype={"stock_id": str})
    universe = universe.loc[universe.eligible.astype(str).str.lower().isin(["true", "1"])].drop_duplicates("stock_id")
    ids = universe.stock_id.tolist()
    stocks = universe.set_index("stock_id", drop=False)
    targets = [sid for sid in ids if state["stocks"].get(sid, {}).get("failure_reason") == "parse_error"
               and state["stocks"][sid].get("status") == "failed"]
    override_path = root / "data/state/annual_eps_verified.json"
    overrides = json.loads(override_path.read_text(encoding="utf-8")) if override_path.exists() else {}
    report = {"mode": "apply" if apply else "dry_run", "started_at": now(), "api_calls": 0,
              "target_count": len(targets), "repaired_count": 0, "completed_from_cache": 0,
              "queued_for_api": [], "results": [], "other_failures": [], "before": {
                  k: state.get(k) for k in ("completed_count", "remaining_count", "failed_count", "retryable_count")}}
    if apply and targets:
        backup = root / "data/.historical_coverage/repair_backups" / now().replace(":", "-")
        backup.mkdir(parents=True, exist_ok=False)
        for source, name in ((path, "history_progress.json"),
                             (root / "data/annual_financials/history.csv", "annual_history.csv"),
                             (root / "data/dividends/history.csv", "dividend_history.csv")):
            if source.exists():
                shutil.copy2(source, backup / name)
        report["backup_directory"] = str(backup.relative_to(root)).replace("\\", "/")
    for sid in targets:
        payloads, missing = cached_payloads(root, sid)
        entry = state["stocks"][sid]
        if missing:
            report["queued_for_api"].append(sid)
            result = {"stock_id": sid, "stock_name": stocks.loc[sid].stock_name, "missing_cache": missing}
            if apply:
                entry.update(previous_failure_reason=entry["failure_reason"], status="retryable",
                             previous_error_type=entry.pop("error_type", None),
                             failure_reason="temporary_error", cache_repair_missing_datasets=missing)
        else:
            annual, dividends, result = diagnose(stocks.loc[sid], payloads, overrides)
            if apply:
                merge_history(root / "data/annual_financials/history.csv", annual)
                merge_history(root / "data/dividends/history.csv", dividends, dividend=True)
                entry.update(previous_failure_reason=entry["failure_reason"],
                             previous_error_type=entry.pop("error_type", None),
                             failure_reason=result["failure_reason"],
                             status="completed" if result["failure_reason"] is None else "failed",
                             cache_repaired_at=now(), unresolved_details=result)
            report["repaired_count"] += 1
            report["completed_from_cache"] += result["failure_reason"] is None
        report["results"].append(result)
        if apply:
            # Keep the actual API attempt timestamps and last network-run counters.
            state.setdefault("last_fetch_finished_at", state.get("updated_at"))
            refresh_counts(state, ids)
            state["updated_at"] = now()
            atomic_json(path, state)
    for sid in ids:
        entry = state["stocks"].get(sid, {})
        if sid in targets or entry.get("failure_reason") not in ("no_data", "unsupported_format"):
            continue
        payloads, missing = cached_payloads(root, sid)
        if not missing:
            _, _, details = diagnose(stocks.loc[sid], payloads, overrides)
            details["original_failure_reason"] = entry["failure_reason"]
            report["other_failures"].append(details)
    report["finished_at"] = now()
    report["after"] = {k: state.get(k) for k in report["before"]}
    if apply and targets:
        state["last_cache_repair"] = {k: report[k] for k in (
            "started_at", "finished_at", "api_calls", "target_count", "repaired_count",
            "completed_from_cache", "queued_for_api")}
        atomic_json(path, state)
        atomic_json(root / "data/state/history_cache_repair_report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Save recovered rows under the history-batch lock")
    args = parser.parse_args()
    result = repair_from_cache(apply=args.apply)
    print(json.dumps({k: v for k, v in result.items() if k not in ("results", "other_failures")},
                     ensure_ascii=False, indent=2))
