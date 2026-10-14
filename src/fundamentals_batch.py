"""Budget-aware, resumable updates for the local listed-stock universe."""

from datetime import datetime
import json
import logging
from pathlib import Path

import pandas as pd

from config import FINANCIALS_DIR, FINMIND_API_LIMIT, REVENUE_DIR, STOCKS_PATH, TAIWAN_TIME
from finmind_client import ApiBudget, BudgetReached, FinMindClient, token_from_environment
from update_financials import update_financials
from update_revenue import update_revenue


LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROGRESS_PATH = PROJECT_ROOT / "data" / "state" / "fundamentals_progress.json"
REQUIRED_FINANCIAL_FIELDS = (
    "eps_single", "gross_margin_single", "operating_margin_single",
    "roe_quarterly_approx", "debt_ratio", "operating_cash_flow_single",
    "free_cash_flow_single",
)


def _empty_progress():
    return {
        "completed_stock_ids": [],
        "failed_stock_ids": [],
        "failure_reasons": {},
        "last_attempted_stock_id": None,
        "completed_count": 0,
        "remaining_count": 0,
        "last_run_api_calls": 0,
        "total_api_calls_estimated": 0,
        "updated_at": "",
        "last_run": {},
    }


def load_progress(path=PROGRESS_PATH):
    if not path.exists():
        return _empty_progress()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Cannot read fundamentals progress file: {path}") from exc
    if not isinstance(state, dict) or not isinstance(state.get("completed_stock_ids", []), list):
        raise RuntimeError(f"Invalid fundamentals progress structure: {path}")
    base = _empty_progress()
    base.update(state)
    return base


def save_progress(state, path=PROGRESS_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _read_data(directory):
    paths = sorted(directory.glob("[0-9][0-9][0-9][0-9].csv"))
    if not paths:
        return pd.DataFrame()
    frames = [pd.read_csv(path, dtype={"stock_id": str}, encoding="utf-8-sig") for path in paths]
    return pd.concat(frames, ignore_index=True)


def completed_from_local_data():
    """A stock is complete only when latest local revenue and financial metrics exist."""
    revenue = _read_data(REVENUE_DIR)
    financials = _read_data(FINANCIALS_DIR)
    if revenue.empty or financials.empty:
        return set()
    complete_revenue = set()
    revenue["date"] = revenue["date"].astype(str)
    for stock_id, rows in revenue.groupby("stock_id"):
        latest = rows.sort_values("date").iloc[-1]
        if pd.notna(pd.to_numeric(latest.get("revenue"), errors="coerce")):
            complete_revenue.add(str(stock_id))
    complete_financials = set()
    missing = [field for field in REQUIRED_FINANCIAL_FIELDS if field not in financials.columns]
    if missing:
        return set()
    financials = financials.sort_values(["year", "quarter"])
    for stock_id, rows in financials.groupby("stock_id"):
        latest = rows.iloc[-1]
        if all(pd.notna(pd.to_numeric(latest.get(field), errors="coerce"))
               for field in REQUIRED_FINANCIAL_FIELDS):
            complete_financials.add(str(stock_id))
    return complete_revenue & complete_financials


def _local_status(stock_id):
    revenue = _read_data(REVENUE_DIR)
    financials = _read_data(FINANCIALS_DIR)
    revenue_rows = revenue.loc[revenue["stock_id"].astype(str) == stock_id] if not revenue.empty else revenue
    financial_rows = financials.loc[financials["stock_id"].astype(str) == stock_id] if not financials.empty else financials
    has_revenue = not revenue_rows.empty and pd.notna(
        pd.to_numeric(revenue_rows.sort_values("date").iloc[-1].get("revenue"), errors="coerce")
    )
    has_financials = False
    if not financial_rows.empty and all(field in financial_rows.columns for field in REQUIRED_FINANCIAL_FIELDS):
        latest = financial_rows.sort_values(["year", "quarter"]).iloc[-1]
        has_financials = all(pd.notna(pd.to_numeric(latest.get(field), errors="coerce"))
                             for field in REQUIRED_FINANCIAL_FIELDS)
    return has_revenue, has_financials, not financial_rows.empty


def _failure_category(client, stock_id, has_revenue, has_financials, has_any_financials):
    categories = [entry["category"] for entry in client.errors if entry["stock_id"] == stock_id]
    priority = ("rate_limit", "network_error", "parse_error", "temporary_error")
    for category in priority:
        if category in categories:
            return category
    if has_any_financials and not has_financials:
        return "unsupported_financial_format"
    return "no_data"


def run_fundamentals_batch(api_budget=100, *, stocks_path=STOCKS_PATH,
                           progress_path=PROGRESS_PATH, client_factory=None):
    if not 1 <= api_budget <= 100:
        raise ValueError("Stage 1 --api-budget must be between 1 and 100")
    if not stocks_path.exists():
        raise FileNotFoundError(f"Stock list is missing: {stocks_path}")
    stocks = pd.read_csv(stocks_path, dtype={"stock_id": str}, encoding="utf-8-sig")
    stocks = stocks.dropna(subset=["stock_id"]).drop_duplicates("stock_id")
    stocks["stock_id"] = stocks["stock_id"].astype(str).str.strip()
    stocks = stocks.sort_values("stock_id").reset_index(drop=True)
    all_ids = stocks["stock_id"].tolist()
    state = load_progress(progress_path)
    completed = set(str(value) for value in state["completed_stock_ids"])
    completed.update(completed_from_local_data())
    completed.intersection_update(all_ids)
    state["completed_stock_ids"] = sorted(completed)
    state["completed_count"] = len(completed)
    state["remaining_count"] = len(all_ids) - len(completed)
    state["last_run_api_calls"] = 0
    save_progress(state, progress_path)

    candidates = stocks.loc[~stocks["stock_id"].isin(completed)]
    LOGGER.info("Stocks to update: %s", len(candidates))
    if client_factory is None:
        def persist_api_call():
            state["total_api_calls_estimated"] = int(state.get("total_api_calls_estimated", 0)) + 1
            state["last_run_api_calls"] = int(state.get("last_run_api_calls", 0)) + 1
            state["updated_at"] = datetime.now(TAIWAN_TIME).isoformat(timespec="seconds")
            save_progress(state, progress_path)

        client_factory = lambda: FinMindClient(token_from_environment(), ApiBudget(
            limit=FINMIND_API_LIMIT, run_limit=api_budget, on_consume=persist_api_call
        ))
    client = client_factory()
    attempted = 0
    run_completed = 0
    run_failed = 0
    completed_call_counts = []
    stopped_for_budget = False
    run_started = client.budget.calls_this_run
    try:
        for row in candidates.itertuples(index=False):
            if client.budget.calls_this_run - run_started >= api_budget:
                stopped_for_budget = True
                break
            stock_id = str(row.stock_id)
            name = str(row.stock_name)
            attempted += 1
            before_calls = client.budget.calls_this_run
            state["last_attempted_stock_id"] = stock_id
            save_progress(state, progress_path)
            try:
                update_revenue(client, stock_id, name)
                _, _, reached, _ = update_financials(client, stock_id, name)
                if reached:
                    stopped_for_budget = True
            except BudgetReached:
                stopped_for_budget = True
            except Exception as exc:  # A malformed stock must not stop the batch.
                LOGGER.warning("Fundamentals processing failed for %s (%s)",
                               stock_id, type(exc).__name__)
                client.errors.append({"stock_id": stock_id, "dataset": "batch",
                                      "category": "parse_error" if isinstance(exc, (ValueError, KeyError))
                                      else "temporary_error"})

            has_revenue, has_financials, has_any_financials = _local_status(stock_id)
            calls_for_stock = client.budget.calls_this_run - before_calls
            if has_revenue and has_financials:
                completed.add(stock_id)
                state["failure_reasons"].pop(stock_id, None)
                run_completed += 1
                completed_call_counts.append(calls_for_stock)
            else:
                category = ("rate_limit" if stopped_for_budget else
                            _failure_category(client, stock_id, has_revenue,
                                              has_financials, has_any_financials))
                state["failure_reasons"][stock_id] = category
                run_failed += 1
            state["completed_stock_ids"] = sorted(completed)
            state["failed_stock_ids"] = sorted(state["failure_reasons"])
            state["completed_count"] = len(completed)
            state["remaining_count"] = len(all_ids) - len(completed)
            state["last_run_api_calls"] = client.budget.calls_this_run - run_started
            if not hasattr(client.budget, "on_consume"):
                state["total_api_calls_estimated"] = int(state.get("total_api_calls_estimated", 0)) + calls_for_stock
            state["updated_at"] = datetime.now(TAIWAN_TIME).isoformat(timespec="seconds")
            save_progress(state, progress_path)
            if stopped_for_budget or client.stop_reason == "rate_limit":
                break
    finally:
        client.close()

    calls = client.budget.calls_this_run - run_started
    average_attempted = calls / attempted if attempted else None
    average_completed = (sum(completed_call_counts) / len(completed_call_counts)
                         if completed_call_counts else None)
    state["last_run_api_calls"] = calls
    state["total_api_calls_estimated"] = int(state.get("total_api_calls_estimated", 0))
    state["last_run"] = {
        "api_calls": calls,
        "attempted_stocks": attempted,
        "completed_stocks": run_completed,
        "failed_stocks": run_failed,
        "average_api_calls_per_attempted_stock": average_attempted,
        "average_api_calls_per_completed_stock": average_completed,
    }
    state["completed_stock_ids"] = sorted(completed)
    state["failed_stock_ids"] = sorted(state["failure_reasons"])
    state["completed_count"] = len(completed)
    state["remaining_count"] = len(all_ids) - len(completed)
    state["updated_at"] = datetime.now(TAIWAN_TIME).isoformat(timespec="seconds")
    save_progress(state, progress_path)
    LOGGER.info("Attempted stocks: %s", attempted)
    LOGGER.info("Completed stocks: %s", run_completed)
    LOGGER.info("Failed stocks: %s", run_failed)
    LOGGER.info("Average API calls per attempted stock: %s",
                f"{average_attempted:.2f}" if average_attempted is not None else "N/A")
    LOGGER.info("Average API calls per completed stock: %s",
                f"{average_completed:.2f}" if average_completed is not None else "N/A")
    LOGGER.info("FinMind API calls: %s / %s", calls, api_budget)
    if stopped_for_budget or client.stop_reason == "rate_limit":
        LOGGER.warning("Stage 1 API budget reached")
    LOGGER.info("Completed total: %s", state["completed_count"])
    LOGGER.info("Remaining stocks: %s", state["remaining_count"])
    return state
