"""Refresh recent official price dates before the Strategy D daily update."""

from datetime import date, timedelta
from pathlib import Path
import time

import pandas as pd

from config import PROJECT_ROOT, make_session, today_in_taiwan
from finmind_client import ApiBudget
from update_prices import fetch_prices, save_prices


def missing_price_dates(prices_dir, asof, lookback=7):
    """Retry recent weekdays missing either market; never cache no-data as zero."""
    if not 1 <= lookback <= 14:
        raise ValueError("Price lookback must be 1-14 calendar days")
    days = [asof - timedelta(days=offset) for offset in range(lookback - 1, -1, -1)]
    days = [day for day in days if day.weekday() < 5]
    existing = set()
    for year in sorted({day.year for day in days}):
        path = Path(prices_dir) / f"{year}.csv"
        if path.exists():
            frame = pd.read_csv(path, usecols=["date", "market"], dtype=str)
            existing.update(zip(frame.date, frame.market))
    return [(day, {market for market in ("TWSE", "TPEx")
                   if (day.isoformat(), market) not in existing})
            for day in days if any((day.isoformat(), market) not in existing
                                   for market in ("TWSE", "TPEx"))]


def update_recent_prices(asof=None, *, root=PROJECT_ROOT, lookback=7,
                         session=None, sleep=time.sleep):
    """Use existing daily price parser; leave unpublished days pending for later runs."""
    asof = asof or today_in_taiwan()
    if asof > today_in_taiwan():
        raise ValueError("Daily institutional date cannot be in the future")
    root = Path(root)
    pending = missing_price_dates(root / "data/prices", asof, lookback)
    stocks = pd.read_csv(root / "data/market/stocks.csv", dtype={"stock_id": str})
    summary = {"attempted_dates": [], "added_rows": 0, "pending_market_dates": []}
    own_session = session is None
    session = session or make_session()
    try:
        for day, missing_markets in pending:
            rows = fetch_prices(session, day, stocks)
            with ApiBudget(path=root / "data/.history_batch_guard.json")._lock():
                added, _ = save_prices(rows, day)
            summary["attempted_dates"].append(day.isoformat())
            summary["added_rows"] += added
            returned = set(rows.market) if not rows.empty else set()
            summary["pending_market_dates"].extend(
                f"{day.isoformat()}:{market}" for market in sorted(missing_markets - returned))
            sleep(1)
    finally:
        if own_session:
            session.close()
    return summary
