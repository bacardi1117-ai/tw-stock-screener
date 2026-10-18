"""One resumable, rate-limited official daily-price audit/backfill (no FinMind).

Each successful date/source is saved before continuing. A separate OS lock prevents
duplicate price jobs; the financial-history scheduler and its files are untouched.
"""
import argparse
from datetime import date, timedelta, datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import time

import pandas as pd
import requests

from config import PRICES_DIR, STOCKS_PATH, today_in_taiwan
from market_history import SOURCES, SourceStopped, _request
from update_prices import PRICE_COLUMNS, _normalize

ROOT = Path(__file__).resolve().parent.parent
CACHE = PRICES_DIR / ".backtest_history"
PROGRESS = ROOT / "data/state/price_history_progress.json"
LOG = logging.getLogger(__name__)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def valid_values(row):
    try:
        prices = [float(row[k]) for k in ("open", "high", "low", "close")]
        volume = float(row["volume"])
        return (all(math.isfinite(v) and v > 0 for v in prices) and
                prices[1] >= max(prices[0], prices[2], prices[3]) and
                prices[2] <= min(prices[0], prices[1], prices[3]) and
                math.isfinite(volume) and volume >= 0 and volume.is_integer())
    except (ValueError, TypeError, KeyError):
        return False


def merge_cache(years):
    """Keep every old valid quote; add absent keys and repair invalid keys only."""
    result = {}
    for year in sorted(years):
        path = PRICES_DIR / f"{year}.csv"
        old = pd.read_csv(path, dtype={"stock_id": str}) if path.exists() else pd.DataFrame(columns=PRICE_COLUMNS)
        old = old.drop_duplicates(["date", "stock_id"], keep="first")
        records = {(r["date"], r["stock_id"]): r for r in old.to_dict("records")}
        added = repaired = conflicts = 0
        samples = []
        files = sorted(CACHE.glob(f"{year}-*-*.csv"))
        for file in files:
            frame = pd.read_csv(file, dtype={"stock_id": str})
            for row in frame.to_dict("records"):
                key = (row["date"], row["stock_id"])
                previous = records.get(key)
                if previous is None:
                    records[key] = row
                    added += 1
                elif not valid_values(previous) and valid_values(row):
                    records[key] = row
                    repaired += 1
                elif valid_values(previous) and valid_values(row) and any(
                    abs(float(previous[k]) - float(row[k])) > 1e-6
                    for k in ("open", "high", "low", "close", "volume")
                ):
                    conflicts += 1
                    if len(samples) < 20:
                        samples.append({"date": key[0], "stock_id": key[1],
                                        "preserved_close": previous["close"], "official_close": row["close"]})
        if added or repaired:
            combined = pd.DataFrame(records.values(), columns=PRICE_COLUMNS)
            combined = combined.sort_values(["date", "market", "stock_id"])
            tmp = path.with_suffix(".tmp")
            combined.to_csv(tmp, index=False, encoding="utf-8-sig", lineterminator="\n")
            tmp.replace(path)
        result[str(year)] = {"added": added, "repaired": repaired, "preserved_conflicts": conflicts,
                             "conflict_samples": samples, "rows": len(records)}
        LOG.info("Merged %s: %s", year, {k:v for k,v in result[str(year)].items() if k != "conflict_samples"})
    return result


def run(start, end):
    if start > end or end > today_in_taiwan():
        raise ValueError("Dates must be ordered and not in the future")
    if (end-start).days > 730:
        raise ValueError("One explicit backtest backfill is limited to 731 calendar days")
    CACHE.mkdir(parents=True, exist_ok=True)
    # Advisory OS lock is released even if the process crashes; no stale PID bypass.
    lock = (CACHE / "runner.lock").open("a+b")
    lock.seek(0); lock.write(b"0"); lock.flush(); lock.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stocks = pd.read_csv(STOCKS_PATH, dtype={"stock_id": str})
    stock_ids = set(stocks.stock_id)
    state = json.loads(PROGRESS.read_text(encoding="utf-8")) if PROGRESS.exists() else {"dates": {}}
    prior_attempts = state.get("total_http_attempts", sum(state.get("current_run_requests", {}).values()))
    state.update(start=str(start), end=str(end), volume_unit="shares", stock_count=len(stock_ids),
                 current_run_requests={m:0 for m in SOURCES}, stop_reason=None)
    counts = state["current_run_requests"]
    years = set(range(start.year, end.year + 1))
    session = requests.Session()
    try:
        day = start
        while day <= end:
            if day.weekday() >= 5:
                day += timedelta(days=1)
                continue
            for market in SOURCES:
                key = f"{day}:{market}"
                cached = CACHE / f"{day}-{market}.csv"
                previous = state["dates"].get(key, {})
                if previous.get("status") == "no_market_rows" or (
                    previous.get("status") == "saved" and cached.exists()
                ):
                    continue
                try:
                    rows = _request(session, market, day, counts, strict_dates=True)
                    if not rows:
                        entry = {"status": "no_market_rows", "rows": 0}
                    else:
                        frame = _normalize(rows, market, day, stock_ids)
                        invalid = [str(r["stock_id"]) for r in frame.to_dict("records") if not valid_values(r)]
                        tmp = cached.with_suffix(".tmp")
                        frame.to_csv(tmp, index=False, encoding="utf-8", lineterminator="\n")
                        tmp.replace(cached)
                        entry = {"status": "saved", "rows": len(frame), "invalid_ohlcv_ids": invalid}
                    state["dates"][key] = entry
                    state["total_http_attempts"] = prior_attempts + sum(counts.values())
                    state["updated_at"] = datetime.now(timezone.utc).isoformat()
                    write_json(PROGRESS, state)
                    LOG.info("%s %s: %s (%s requests)", day, market, entry["rows"], sum(counts.values()))
                except SourceStopped as exc:
                    state["dates"][key] = {"status": "retryable", "reason": str(exc)}
                    state["stop_reason"] = str(exc)
                    raise
            day += timedelta(days=1)
        state["stop_reason"] = "range_completed"
    finally:
        session.close()
        try:
            state["merge"] = merge_cache(years)
        finally:
            state["total_http_attempts"] = prior_attempts + sum(counts.values())
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            write_json(PROGRESS, state)
            lock.close()
    return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    run(args.start, args.end)
