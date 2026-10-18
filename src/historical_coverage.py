"""Bounded, resumable Phase 5B.2 source validation for three authorized stocks."""

import json
import time
from pathlib import Path

import requests

from config import PROJECT_ROOT
from finmind_client import ApiBudget, BudgetReached, FinMindClient, token_from_environment


SAMPLE_STOCKS = ("2330", "2317", "2454")
DATASETS = {"TaiwanStockFinancialStatements": "2023-01-01",
            "TaiwanStockCashFlowsStatement": "2023-01-01",
            "TaiwanStockDividend": "2021-01-01"}
CACHE = PROJECT_ROOT / "data" / ".historical_coverage"
PROGRESS = PROJECT_ROOT / "data" / "state" / "historical_coverage_progress.json"


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def fetch_sample():
    """Never expands beyond SAMPLE_STOCKS. Every HTTP attempt uses the existing budget."""
    token = token_from_environment()
    if not token:
        raise RuntimeError("FinMind token is not configured")
    state = json.loads(PROGRESS.read_text(encoding="utf-8")) if PROGRESS.exists() else {
        "scope": list(SAMPLE_STOCKS), "jobs": {}, "http_attempts": [], "api_calls": 0}

    def persist():
        atomic_json(PROGRESS, state)

    def consume():
        state["api_calls"] += 1
        persist()

    class AuditedSession(requests.Session):
        def get(self, url, **kwargs):
            start = time.monotonic()
            params = kwargs.get("params", {})
            entry = {"stock_id": params.get("data_id"), "dataset": params.get("dataset")}
            try:
                response = super().get(url, **kwargs)
                entry["status"] = response.status_code
                return response
            except requests.RequestException as exc:
                entry["error"] = type(exc).__name__
                raise
            finally:
                entry["seconds"] = round(time.monotonic() - start, 3)
                state["http_attempts"].append(entry)
                persist()

    client = FinMindClient(token, budget=ApiBudget(limit=400, run_limit=30, on_consume=consume),
                           session=AuditedSession())
    try:
        for stock_id in SAMPLE_STOCKS:
            for dataset, start_date in DATASETS.items():
                key = f"{stock_id}_{dataset}"
                cache_path = CACHE / f"{key}.json"
                if state["jobs"].get(key, {}).get("status") == "completed" and cache_path.exists():
                    continue
                rows = client.get(dataset, stock_id, start_date)
                if rows is None:
                    state["jobs"][key] = {"status": "retry", "errors": client.errors[-1:]}
                    persist()
                    if state["http_attempts"][-1].get("status") in (401, 402, 403):
                        return state
                    continue
                atomic_json(cache_path, rows)
                state["jobs"][key] = {"status": "completed", "rows": len(rows),
                                       "start_date": start_date}
                persist()
                print(f"Cached {stock_id} {dataset}: {len(rows)} rows")
    except BudgetReached:
        state["stop_reason"] = "api_budget_or_rate_limit"
        persist()
    finally:
        client.close()
    return state


if __name__ == "__main__":
    result = fetch_sample()
    print(json.dumps({"api_calls": result["api_calls"], "jobs": result["jobs"]}, ensure_ascii=False))
