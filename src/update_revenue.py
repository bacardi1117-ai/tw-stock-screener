"""Incrementally update monthly revenue and calculate MoM/YoY percentages."""

import logging

import pandas as pd

from config import FINMIND_DATASETS, FINMIND_INITIAL_DATE, REVENUE_DIR
from fundamentals_store import changed, read_years, safe_percent, write_years


LOGGER = logging.getLogger(__name__)
REVENUE_COLUMNS = [
    "date", "year", "month", "stock_id", "stock_name", "revenue", "revenue_mom", "revenue_yoy",
]


def _start_date(existing, stock_id):
    rows = existing.loc[existing["stock_id"] == stock_id]
    return str(rows["date"].max()) if not rows.empty else FINMIND_INITIAL_DATE


def _parse(rows, stock_id, stock_name):
    parsed = []
    for row in rows:
        try:
            year = int(row["revenue_year"])
            month = int(row["revenue_month"])
            period_date = pd.to_datetime(row["date"], errors="raise").date().isoformat()
            revenue = pd.to_numeric(row.get("revenue"), errors="coerce")
            if 1 <= month <= 12 and not pd.isna(revenue):
                parsed.append((period_date, year, month, stock_id, stock_name, float(revenue)))
        except (KeyError, TypeError, ValueError):
            LOGGER.warning("Invalid monthly revenue row for %s", stock_id)
    return parsed


def _recalculate(frame):
    values = {(row.stock_id, int(row.year), int(row.month)): row.revenue for row in frame.itertuples()}
    moms, yoys = [], []
    for row in frame.itertuples():
        previous_year = int(row.year) - (int(row.month) == 1)
        previous_month = 12 if int(row.month) == 1 else int(row.month) - 1
        moms.append(safe_percent(row.revenue, values.get((row.stock_id, previous_year, previous_month))))
        yoys.append(safe_percent(row.revenue, values.get((row.stock_id, int(row.year) - 1, int(row.month)))))
    frame["revenue_mom"] = moms
    frame["revenue_yoy"] = yoys
    return frame


def update_revenue(client, stock_id, stock_name):
    LOGGER.info("Updating revenue: %s", stock_id)
    existing = read_years(REVENUE_DIR, REVENUE_COLUMNS)
    incoming = client.get(FINMIND_DATASETS["revenue"], stock_id, _start_date(existing, stock_id))
    if incoming is None:
        return 0, 0
    records = _parse(incoming, stock_id, stock_name)
    if not records:
        return 0, 0
    by_key = {(str(row.stock_id), int(row.year), int(row.month)): row._asdict() for row in existing.itertuples(index=False)}
    added = updated = 0
    for date_, year, month, sid, name, revenue in records:
        key = (sid, year, month)
        new = {"date": date_, "year": year, "month": month, "stock_id": sid,
               "stock_name": name, "revenue": revenue, "revenue_mom": float("nan"), "revenue_yoy": float("nan")}
        if key not in by_key:
            by_key[key] = new
            added += 1
        elif changed(by_key[key], new, ("date", "stock_name", "revenue")):
            by_key[key].update(new)
            updated += 1
    if added or updated:
        merged = pd.DataFrame(by_key.values(), columns=REVENUE_COLUMNS)
        merged["year"] = pd.to_numeric(merged["year"])
        merged["month"] = pd.to_numeric(merged["month"])
        merged["revenue"] = pd.to_numeric(merged["revenue"], errors="coerce")
        merged = merged.sort_values(["stock_id", "year", "month"]).reset_index(drop=True)
        write_years(_recalculate(merged), REVENUE_DIR, REVENUE_COLUMNS)
    return added, updated
