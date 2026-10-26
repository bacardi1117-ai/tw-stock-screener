"""Build local-only source data for the EPS/value/monthly-average screen."""
from __future__ import annotations

import csv
import json
import math
import os
import time
from pathlib import Path


OUTPUT_RELATIVE_PATH = Path("docs/data/eps_value.json")
PRICE_HISTORY_ROWS = 180
FALLBACK_METHOD = "FinMind:quarterly_basic_eps_sum_fallback"


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def _finite(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _scope(value: str) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"consolidated", "standalone"}:
        return normalized
    return None


def build_payload(root: Path | str, max_price_rows: int = PRICE_HISTORY_ROWS) -> dict:
    """Return only locally stored annual EPS evidence and daily closing prices.

    No network requests are made. Annual rows are accepted only when they came
    from the verified annual-basic-EPS set or the existing complete-quarter
    basic-EPS fallback (display only). Screening requires verified official
    annual values and explicitly matching statement scopes. An identical
    calculation method is not evidence of consolidated/standalone scope.
    """
    root = Path(root)
    max_price_rows = max(1, int(max_price_rows))
    evidence_path = root / "data/state/annual_eps_verified.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.exists() else {}

    eps_by_stock: dict[str, list[dict]] = {}
    for row in _read_csv(root / "data/annual_financials/history.csv"):
        sid = str(row.get("stock_id", "")).strip()
        try:
            year = int(row.get("year", ""))
        except (TypeError, ValueError):
            continue
        method = str(row.get("eps_method", "")).strip()
        value = _finite(row.get("annual_eps"))
        verified = evidence.get(f"{sid}:{year}")
        if verified and str(verified.get("definition", "")).strip().lower() != "basic annual eps":
            verified = None
        if verified and (
            verified.get("eps_basis", "basic") != "basic"
            or verified.get("period_start", f"{year}-01-01") != f"{year}-01-01"
            or verified.get("period_end", f"{year}-12-31") != f"{year}-12-31"
        ):
            verified = None
        if verified:
            official_value = _finite(verified.get("annual_eps"))
            if official_value is None:
                continue
            value = official_value
            method = str(verified.get("source") or method)
        elif method != FALLBACK_METHOD:
            continue
        if value is None:
            continue
        if str(row.get("eps_basis", "")).strip().lower() not in {"", "basic"}:
            continue
        row_scope = _scope(row.get("eps_statement_scope"))
        verified_scope = _scope(verified.get("statement_scope") if verified else None)
        scope = verified_scope or row_scope
        if row_scope and verified_scope and row_scope != verified_scope:
            scope = None
        source = str((verified or {}).get("source") or row.get("source") or method)
        eps_by_stock.setdefault(sid, []).append({
            "year": year,
            "eps": value,
            "period_end": f"{year}-12-31",
            "method": method,
            "source": source,
            "verified_official": bool(verified),
            "basis": "basic",
            "scope": scope,
            "updated_at": row.get("updated_at") or None,
        })

    valuations_by_stock: dict[str, list[dict]] = {}
    for path in sorted((root / "data/valuation").glob("[0-9][0-9][0-9][0-9].csv")):
        for row in _read_csv(path):
            sid, day = row.get("stock_id", ""), row.get("date", "")
            per = _finite(row.get("per"))
            if sid and len(day) == 10 and per is not None and per > 0:
                valuations_by_stock.setdefault(sid, []).append({"date": day, "per": per})

    prices_by_stock: dict[str, dict[str, float]] = {}
    price_dir = root / "data/prices"
    for path in sorted(price_dir.glob("[0-9][0-9][0-9][0-9].csv")):
        for row in _read_csv(path):
            sid = str(row.get("stock_id", "")).strip()
            day = str(row.get("date", "")).strip()
            close = _finite(row.get("close"))
            if sid and len(day) == 10 and close is not None:
                prices_by_stock.setdefault(sid, {})[day] = close
    all_dates = sorted({day for records in prices_by_stock.values() for day in records})[-max_price_rows:]
    for records in eps_by_stock.values():
        records.sort(key=lambda row: row["year"])

    stock_ids = sorted(set(eps_by_stock) | set(prices_by_stock))
    return {
        "schema_version": 1,
        "price_history_rows": max_price_rows,
        "dates": all_dates,
        "stocks": {
            sid: {
                "annual_eps": eps_by_stock.get(sid, []),
                "valuations": sorted(valuations_by_stock.get(sid, []), key=lambda item: item["date"]),
                "closes": [prices_by_stock.get(sid, {}).get(day) for day in all_dates],
            }
            for sid in stock_ids
        },
    }


def write_payload(root: Path | str, max_price_rows: int = PRICE_HISTORY_ROWS) -> Path:
    """Atomically update the strategy sidecar from existing local CSVs."""
    root = Path(root)
    target = root / OUTPUT_RELATIVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_payload(root, max_price_rows=max_price_rows)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                         encoding="utf-8")
    for attempt in range(3):
        try:
            os.replace(temporary, target)
            return target
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.2 * (attempt + 1))
    return target
