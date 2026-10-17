"""Incremental daily PER/PBR/yield from official TWSE and TPEx data."""

from datetime import date, timedelta
import logging
import time

import pandas as pd
import requests

from config import PROJECT_ROOT, REQUEST_TIMEOUT, today_in_taiwan


LOGGER = logging.getLogger(__name__)
VALUATION_DIR = PROJECT_ROOT / "data" / "valuation"
TWSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
FIELDS = ["date", "stock_id", "stock_name", "market", "close", "dividend_yield", "per", "pbr"]


def _number(value):
    return pd.to_numeric(str(value).replace(",", "").strip(), errors="coerce")


def parse_twse(payload, day):
    if payload.get("stat") != "OK":
        raise ValueError(f"TWSE valuation unavailable for {day}: {payload.get('stat')}")
    columns = payload.get("fields", [])
    rows = []
    for values in payload.get("data", []):
        item = dict(zip(columns, values))
        rows.append({"date": day.isoformat(), "stock_id": str(item.get("證券代號", "")).strip(),
                     "stock_name": item.get("證券名稱"), "market": "TWSE",
                     "close": _number(item.get("收盤價")),
                     "dividend_yield": _number(item.get("殖利率(%)")),
                     "per": _number(item.get("本益比")), "pbr": _number(item.get("股價淨值比"))})
    return pd.DataFrame(rows, columns=FIELDS)


def parse_tpex(records, day=None):
    rows = []
    for item in records:
        code = str(item.get("SecuritiesCompanyCode", "")).strip()
        if not code:
            continue
        raw_date = str(item.get("Date", "")).strip()
        try:
            parsed = pd.to_datetime(str(int(raw_date[:3]) + 1911) + raw_date[3:], format="%Y%m%d").date()
        except (ValueError, TypeError):
            parsed = day
        if parsed is None:
            continue
        rows.append({"date": parsed.isoformat(), "stock_id": code, "stock_name": item.get("CompanyName"),
                     "market": "TPEx", "close": float("nan"),
                     "dividend_yield": _number(item.get("YieldRatio")),
                     "per": _number(item.get("PriceEarningRatio")),
                     "pbr": _number(item.get("PriceBookRatio"))})
    return pd.DataFrame(rows, columns=FIELDS)


def _request(session, url, params=None, attempts=3, sleep=time.sleep):
    for attempt in range(attempts):
        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code == 429:
                raise RuntimeError("official valuation source rate-limited the request (429)")
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError, ValueError) as exc:
            if attempt + 1 == attempts:
                raise RuntimeError(f"valuation request failed: {type(exc).__name__}") from exc
            sleep((1, 3)[min(attempt, 1)])
    raise RuntimeError("valuation request exhausted retries")


def existing_dates(path):
    if not path.exists():
        return set()
    frame = pd.read_csv(path, dtype={"stock_id": str}, usecols=["date", "market"])
    return set(zip(frame.date.astype(str), frame.market.astype(str)))


def latest_weekday(day):
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def save_valuation(frame, directory=VALUATION_DIR):
    if frame.empty:
        return 0
    directory = type(VALUATION_DIR)(directory)
    count = 0
    for year, group in frame.groupby(frame.date.str[:4]):
        path = directory / f"{year}.csv"
        directory.mkdir(parents=True, exist_ok=True)
        combined = pd.concat([pd.read_csv(path, dtype={"stock_id": str}, encoding="utf-8-sig"), group],
                             ignore_index=True) if path.exists() else group
        combined = combined.drop_duplicates(["date", "stock_id"], keep="last").sort_values(["date", "stock_id"])
        combined.reindex(columns=FIELDS).to_csv(path, index=False, encoding="utf-8-sig")
        count += len(group)
    return count


def _latest_twse_snapshot(session, sleep):
    candidate = today_in_taiwan()
    for _ in range(10):
        if candidate.weekday() < 5:
            payload = _request(session, TWSE_URL,
                               {"date": candidate.strftime("%Y%m%d"), "selectType": "ALL", "response": "json"})
            if payload.get("stat") == "OK" and payload.get("data"):
                return candidate, payload
            sleep(1)
        candidate -= timedelta(days=1)
    raise RuntimeError("No TWSE valuation snapshot found in the last ten calendar days")


def update_valuation(day=None, session=None, sleep=time.sleep):
    """Fetch the current daily snapshot; an already stored date is never re-requested."""
    if day is not None and day > today_in_taiwan():
        raise ValueError("valuation date cannot be in the future")
    own_session = session is None
    session = session or requests.Session()
    frames = []
    try:
        twse_payload = None
        if day is None:
            current_file = VALUATION_DIR / f"{today_in_taiwan().year}.csv"
            existing = existing_dates(current_file)
            complete_days = {d for d, market in existing
                             if (d, "TWSE") in existing and (d, "TPEx") in existing}
            if complete_days and max(complete_days) >= latest_weekday(today_in_taiwan()).isoformat():
                return {"date": max(complete_days), "added": 0, "skipped": True}
            day, twse_payload = _latest_twse_snapshot(session, sleep)
        path = VALUATION_DIR / f"{day.year}.csv"
        existing = existing_dates(path)
        if (day.isoformat(), "TWSE") in existing and (day.isoformat(), "TPEx") in existing:
            return {"date": day.isoformat(), "added": 0, "skipped": True}
        if (day.isoformat(), "TWSE") not in existing:
            payload = twse_payload or _request(session, TWSE_URL,
                {"date": day.strftime("%Y%m%d"), "selectType": "ALL", "response": "json"}, sleep=sleep)
            frames.append(parse_twse(payload, day))
            sleep(1)
        if (day.isoformat(), "TPEx") not in existing:
            records = _request(session, TPEX_URL, sleep=sleep)
            frames.append(parse_tpex(records, day))
        combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=FIELDS)
        # The TPEx endpoint is a latest snapshot; do not label it with a requested date if its date differs.
        added = save_valuation(combined)
        LOGGER.info("Official valuation rows saved: %s", added)
        return {"date": day.isoformat(), "added": added, "skipped": False}
    finally:
        if own_session:
            session.close()
