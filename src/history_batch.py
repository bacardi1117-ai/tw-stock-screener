"""Bounded annual-history batches; no fundamental queue or QGM mutations."""
import json
import math
import re
import time
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from config import PROJECT_ROOT
from finmind_client import ApiBudget, BudgetReached, FinMindClient, token_from_environment
from historical_coverage import atomic_json, DATASETS

YEARS = (2023, 2024, 2025)
DIV_YEARS = (2021, 2022, 2023, 2024, 2025)
NAN = float("nan")

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else NAN
    except (ValueError, TypeError):
        return NAN

def annual_rows(sid, name, income, flows, overrides=None):
    rows = []
    for year in YEARS:
        eps, method = NAN, "missing"
        # Explicit vetted annual inputs take precedence; generic EPS is single-quarter.
        official = (overrides or {}).get(f"{sid}:{year}")
        if official:
            eps, method = number(official["annual_eps"]), official["source"]
        else:
            quarters = {r["date"]: number(r.get("value")) for r in income
                        if r.get("type") == "EPS" and str(r.get("date", "")).startswith(str(year))}
            dates = [f"{year}-{suffix}" for suffix in ("03-31", "06-30", "09-30", "12-31")]
            if all(d in quarters and math.isfinite(quarters[d]) for d in dates):
                eps, method = round(sum(quarters[d] for d in dates), 8), "FinMind:quarterly_basic_eps_sum_fallback"
        ocf = [number(r.get("value")) for r in flows if r.get("type") == "CashFlowsFromOperatingActivities"
               and r.get("date") == f"{year}-12-31"]
        rows.append(dict(stock_id=sid, stock_name=name, year=year, annual_eps=eps,
                         annual_operating_cash_flow=ocf[-1] if ocf else NAN,
                         eps_method=method, source="FinMind; " + method, updated_at=now()))
    return rows

def dividend_rows(sid, name, records, annual, market=""):
    result = []
    for year in DIV_YEARS:
        periods = {}
        for r in sorted(records, key=lambda r: (str(r.get("AnnouncementDate", "")), str(r.get("date", "")))):
            label = str(r.get("year", ""))
            match = re.fullmatch(r"(\d{3,4})年(?:(?:第([1-4])季)|(?:(前|後)半年度))?", label)
            if not match:
                continue
            parsed = int(match[1]); parsed += 1911 if parsed < 1911 else 0
            if parsed != year:
                continue
            period = "Q" + match[2] if match[2] else ("H1" if match[3] == "前" else "H2") if match[3] else "A"
            periods[period] = r
        keys = set(periods)
        complete = keys in ({"A"}, {"H1", "H2"}, {"Q1", "Q2", "Q3", "Q4"})
        amounts = {}
        for kind, fields in {"cash_dividend": ("CashEarningsDistribution", "CashStatutorySurplus"),
                             "stock_dividend": ("StockEarningsDistribution", "StockStatutorySurplus")}.items():
            values = [number(r.get(f)) for r in periods.values() for f in fields]
            amounts[kind] = sum(values) if complete and values and all(math.isfinite(v) for v in values) else NAN
        cash, stock = amounts["cash_dividend"], amounts["stock_dividend"]
        complete = complete and math.isfinite(cash) and math.isfinite(stock)
        eps = next((r["annual_eps"] for r in annual if r["year"] == year), NAN)
        result.append(dict(stock_id=sid, stock_name=name, market=market, year=year, **amounts,
                           total_dividend=cash + stock, annual_eps=eps,
                           payout_ratio=cash / eps * 100 if eps > 0 and complete else NAN,
                           annual_complete=complete, dividend_status=("paid" if cash + stock > 0 else "zero") if complete else "missing_data",
                           periods=",".join(sorted(keys)), source="FinMind:earnings_attribution_year",
                           source_date=max((str(r.get("date", "")) for r in periods.values()), default=""), updated_at=now()))
    return result

def merge_history(path, rows, dividend=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Retaining an older row can copy nullable legacy metadata (notably
    # annual_complete) into a newly inferred bool column. Pandas 3 rejects
    # that scalar assignment. Merge as objects, preserving None/NaN instead
    # of coercing missing metadata or financial amounts to False/zero.
    incoming = pd.DataFrame(rows, dtype=object)
    old = pd.read_csv(path, dtype={"stock_id": str}, float_precision="round_trip") if path.exists() else pd.DataFrame()
    if not old.empty:
        # Incomplete fetches never destroy previously available amounts.
        prior = old.set_index(["stock_id", "year"])
        for i, row in incoming.iterrows():
            key = (row.stock_id, row.year)
            if key not in prior.index:
                continue
            before = prior.loc[key]
            if dividend and not row.annual_complete:
                for field in before.index:
                    incoming.loc[i, field] = before[field]
            elif not dividend:
                for field in ("annual_eps", "annual_operating_cash_flow"):
                    if pd.isna(row[field]): incoming.loc[i, field] = before[field]
                if "quarterly_basic_eps_sum_fallback" in str(row.eps_method) and "fallback" not in str(before.get("eps_method", "missing")) and pd.notna(before.annual_eps):
                    incoming.loc[i, "annual_eps"] = before.annual_eps
                    incoming.loc[i, "eps_method"] = before.get("eps_method", "existing_annual")
    combined = pd.concat([old, incoming], ignore_index=True).drop_duplicates(["stock_id", "year"], keep="last").sort_values(["stock_id", "year"])
    temporary = path.with_suffix(".tmp")
    combined.to_csv(temporary, index=False, encoding="utf-8-sig")
    temporary.replace(path)

def annual_metrics(group):
    result = {}
    for kind, field in (("eps", "annual_eps"), ("ocf", "annual_operating_cash_flow")):
        for year in YEARS:
            rows = group.loc[group.year == year] if group is not None else pd.DataFrame()
            result[f"annual_{kind}_{year}"] = number(rows.iloc[-1][field]) if not rows.empty else NAN
        values = [result[f"annual_{kind}_{year}"] for year in YEARS]
        result[f"{kind}_positive_years_3"] = sum(v > 0 for v in values) if all(math.isfinite(v) for v in values) else NAN
    result["eps_positive_years"] = result["eps_positive_years_3"]
    result["operating_cash_flow_positive_years"] = result["ocf_positive_years_3"]
    return result

class AuditSession(requests.Session):
    def __init__(self, state):
        super().__init__(); self.state = state
    def get(self, *args, **kwargs):
        self.state["last_http_status"] = None
        try:
            response = super().get(*args, **kwargs)
            if response.status_code in (403, 429): self.state[f"http_{response.status_code}"] = True
            self.state["last_http_status"] = response.status_code
            return response
        except requests.Timeout:
            self.state["timeout"] = True
            raise

def run_history_batch(api_budget=360, max_stocks=100, root=PROJECT_ROOT, client_factory=None):
    # OS lock released on process exit; prevents concurrent runs selecting the same queue.
    lock = ApiBudget(path=Path(root) / "data/.history_batch_guard.json")
    with lock._lock():
        return _run_history_batch(api_budget, max_stocks, root, client_factory)

def _run_history_batch(api_budget=360, max_stocks=100, root=PROJECT_ROOT, client_factory=None):
    if not 1 <= api_budget <= 360 or not 1 <= max_stocks <= 100:
        raise ValueError("History limits: 1-360 API calls and 1-100 stocks")
    root = Path(root)
    universe = pd.read_csv(root / "data/state/fundamentals_universe.csv", dtype={"stock_id": str})
    eligible = universe.loc[universe.eligible.astype(str).str.lower().isin(["true", "1"])].drop_duplicates("stock_id")
    path = root / "data/state/history_progress.json"
    state = json.loads(path.read_text(encoding="utf8")) if path.exists() else {"stocks": {}}
    entries = state.setdefault("stocks", {})
    state.update(last_run_api_calls=0, attempted=0, completed=0, failed=0, retryable=0, http_429=False, http_403=False, timeout=False)
    ids = eligible.stock_id.tolist()
    def persist():
        for status, field in (("completed", "completed_stock_ids"), ("retryable", "retryable_stock_ids"), ("failed", "failed_stock_ids")):
            state[field] = [sid for sid in ids if entries.get(sid, {}).get("status") == status]
        state.update(completed_count=len(state["completed_stock_ids"]), eligible_count=len(ids),
                     failed_count=len(state["failed_stock_ids"]), retryable_count=len(state["retryable_stock_ids"]), updated_at=now())
        state["remaining_count"] = len(ids) - state["completed_count"]
        state.setdefault("last_attempted_stock_id", None)
        atomic_json(path, state)
    persist()
    if state["remaining_count"] == 0:
        print("Historical financial and dividend universe completed")
        return state
    pending = [sid for sid in ids if sid not in entries] + [sid for sid in ids if entries.get(sid, {}).get("status") == "retryable"]
    if not pending:
        state["stop_reason"] = "manual_review_required"; persist(); return state
    def consumed():
        state["last_run_api_calls"] += 1; persist()
    budget = ApiBudget(path=root / "data/.finmind_api_budget.json", limit=360, run_limit=api_budget, on_consume=consumed)
    if client_factory:
        client = client_factory(budget)
    else:
        token = token_from_environment()
        if not token: raise RuntimeError("FinMind authentication is not configured")
        client = FinMindClient(token, budget, AuditSession(state))
    overrides_path = root / "data/state/annual_eps_verified.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf8")) if overrides_path.exists() else {}
    state["stop_reason"] = "batch_limit"
    consecutive_network_errors = 0
    try:
        for sid in pending[:max_stocks]:
            if budget.calls_this_run >= api_budget: break
            state["attempted"] += 1; state["last_attempted_stock_id"] = sid
            entries[sid] = {"status": "retryable", "last_attempt_at": now()}; persist()
            stock = eligible.loc[eligible.stock_id == sid].iloc[0]
            payloads = {}; error = None; stop = False
            try:
                for dataset, start in DATASETS.items():
                    cache = root / "data/.historical_coverage" / f"{sid}_{dataset}.json"
                    if cache.exists():
                        payloads[dataset] = json.loads(cache.read_text(encoding="utf8")); continue
                    data = client.get(dataset, sid, start)
                    if data is None and state.get("last_http_status") == 403:
                        time.sleep(1)
                        data = client.get(dataset, sid, start)
                    if data is None:
                        error = client.errors[-1]["category"] if client.errors else "temporary_error"
                        stop = state.get("last_http_status") in (401, 402, 403)
                        break
                    atomic_json(cache, data); payloads[dataset] = data
                if error is None:
                    annual = annual_rows(sid, stock.stock_name, payloads["TaiwanStockFinancialStatements"], payloads["TaiwanStockCashFlowsStatement"], overrides)
                    dividends = dividend_rows(sid, stock.stock_name, payloads["TaiwanStockDividend"], annual, stock.get("market", ""))
                    merge_history(root / "data/annual_financials/history.csv", annual)
                    merge_history(root / "data/dividends/history.csv", dividends, dividend=True)
                    complete = all(math.isfinite(r[f]) for r in annual for f in ("annual_eps", "annual_operating_cash_flow")) and all(r["annual_complete"] for r in dividends)
                    if not complete:
                        error = "no_data" if any(not p for p in payloads.values()) or any(not r["periods"] for r in dividends) else "unsupported_format"
                status = "completed" if error is None else "retryable" if error in ("temporary_error", "network_error") else "failed"
                entries[sid].update(status=status, failure_reason=error)
                if status == "completed":
                    state["completed"] += 1; consecutive_network_errors = 0
                elif status == "retryable":
                    state["retryable"] += 1; consecutive_network_errors += 1
                else:
                    state["failed"] += 1; consecutive_network_errors = 0
            except BudgetReached:
                entries[sid]["failure_reason"] = "temporary_error"
                state["failed"] += 1
                state["stop_reason"] = client.stop_reason or "api_budget"
                stop = True
            except (ValueError, KeyError, TypeError) as exc:
                entries[sid].update(status="failed", failure_reason="parse_error", error_type=type(exc).__name__)
                state["failed"] += 1
            persist()
            print(f"History {sid}: {entries[sid]['status']}; API calls {state['last_run_api_calls']}", flush=True)
            if consecutive_network_errors >= 5:
                state["stop_reason"] = "consecutive_network_errors"
                stop = True
            if stop: break
    finally:
        client.close(); persist()
    return state

def publish_history(root=PROJECT_ROOT):
    """Commit only generated batch files; refuse unrelated staged changes."""
    root = Path(root)
    paths = [
        ".gitignore", "README.md", "config/strategies.json", "docs/labels.mjs",
        "docs/data/latest.json", "docs/config/strategies.json", "docs/phase5b2-source-validation.md",
        "src/build_pages.py", "src/calculate_factors.py", "src/main.py", "src/update_dividends.py",
        "src/history_batch.py", "src/historical_coverage.py",
        "tests/test_phase5b.py", "tests/test_strategy_engine.py", "tests/test_history_batch.py",
        "data/state/annual_eps_verified.json", "data/state/history_progress.json",
        "data/state/historical_coverage_progress.json", "data/annual_financials/history.csv",
        "data/dividends/history.csv",
    ]
    def git(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    if git("branch", "--show-current") != "main": raise RuntimeError("History publish requires main")
    staged = git("diff", "--cached", "--name-only").splitlines()
    if set(staged) - set(paths): raise RuntimeError("Unrelated staged files; publish stopped")
    existing = [p for p in paths if (root / p).exists()]
    git("add", "--", *existing)
    if not git("diff", "--cached", "--name-only"): return None
    git("commit", "-m", "Update annual financial and dividend history batch")
    git("push", "origin", "main")
    return git("rev-parse", "HEAD")
