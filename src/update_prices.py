"""Fetch date-specific daily quotes and append unseen stocks to yearly CSVs."""

from datetime import date
import logging
import time

import pandas as pd
import requests

from config import HISTORY_BACKOFF_SECONDS, PRICES_DIR, TPEX_PRICES_URL, TWSE_PRICES_URL, get_json
from fetch_market import is_ordinary_stock


LOGGER = logging.getLogger(__name__)
PRICE_COLUMNS = [
    "date", "stock_id", "stock_name", "market", "open", "high", "low",
    "close", "volume", "turnover", "change",
]


def _number(value):
    text = str(value).strip().replace(",", "")
    if text in ("", "--", "---", "—", "－", "nan", "None"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _table_rows(payload: dict, required_fields: set[str], requested: date, market: str):
    if not isinstance(payload, dict):
        raise ValueError(f"{market} price response is not an object")
    reported = str(payload.get("date", ""))
    if not reported and str(payload.get("stat", "")).lower() != "ok":
        return []  # Official no-data response on holidays is not a source error.
    if reported != requested.strftime("%Y%m%d"):
        LOGGER.warning("%s returned date %s for requested %s", market, reported, requested)
        return []
    for table in payload.get("tables", []):
        fields = table.get("fields") or []
        if required_fields.issubset(fields):
            return [dict(zip(fields, values)) for values in table.get("data", [])]
    if str(payload.get("stat", "")).lower() not in ("ok",):
        return []
    raise ValueError(f"{market} price fields changed")


def _twse_change(row: dict):
    amount = _number(row.get("漲跌價差"))
    sign = str(row.get("漲跌(+/-)", ""))
    if amount is None:
        return None
    if "-" in sign or "－" in sign:
        return -abs(amount)
    if "+" in sign:
        return abs(amount)
    return amount if amount == 0 else None


def _normalize(rows, market: str, requested: date, stock_ids: set[str]) -> pd.DataFrame:
    result = []
    for row in rows:
        stock_id = str(row.get("證券代號" if market == "TWSE" else "代號", "")).strip()
        name = str(row.get("證券名稱" if market == "TWSE" else "名稱", "")).strip()
        if not is_ordinary_stock(stock_id, name) or (stock_ids and stock_id not in stock_ids):
            continue
        if market == "TWSE":
            values = [row.get(key) for key in ("開盤價", "最高價", "最低價", "收盤價", "成交股數", "成交金額")]
            change = _twse_change(row)
        else:
            values = [row.get(key) for key in ("開盤", "最高", "最低", "收盤", "成交股數", "成交金額(元)")]
            change = _number(row.get("漲跌"))
        numbers = [_number(value) for value in values]
        if numbers[3] is None:
            continue
        open_, high, low, close, volume, turnover = numbers
        result.append((requested.isoformat(), stock_id, name, market, open_, high, low,
                       close, int(volume) if volume is not None else None,
                       int(turnover) if turnover is not None else None, change))
    return pd.DataFrame(result, columns=PRICE_COLUMNS).drop_duplicates(["date", "stock_id"])


def fetch_prices(session: requests.Session, requested: date, stocks: pd.DataFrame) -> pd.DataFrame:
    calls = (
        ("TWSE", TWSE_PRICES_URL, {"date": requested.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"}, {"證券代號", "收盤價", "成交股數"}),
        ("TPEx", TPEX_PRICES_URL, {"date": requested.strftime("%Y/%m/%d")}, {"代號", "收盤", "成交股數"}),
    )
    frames = []
    for market, url, params, fields in calls:
        try:
            payload = get_json(session, url, **params)
            rows = _table_rows(payload, fields, requested, market)
            market_ids = set(stocks.loc[stocks["market"] == market, "stock_id"])
            frame = _normalize(rows, market, requested, market_ids)
            frames.append(frame)
            LOGGER.info("%s price records: %s", market, len(frame))
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            LOGGER.error("%s price fetch failed: %s", market, exc)
            LOGGER.info("%s price records: 0", market)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS)


def save_prices(prices: pd.DataFrame, requested: date, sleep=time.sleep) -> tuple[int, int]:
    if prices.empty:
        LOGGER.info("No market data for %s", requested.isoformat())
        LOGGER.info("Saved records: 0")
        LOGGER.info("Duplicate records skipped: 0")
        return 0, 0
    path = PRICES_DIR / f"{requested.year}.csv"
    existing = pd.read_csv(path, dtype={"date": str, "stock_id": str}) if path.exists() else pd.DataFrame(columns=PRICE_COLUMNS)
    existing_keys = set(zip(existing["date"], existing["stock_id"]))
    new_rows = prices.loc[~prices.apply(lambda row: (row["date"], row["stock_id"]) in existing_keys, axis=1)]
    duplicates = len(prices) - len(new_rows)
    if not new_rows.empty:
        combined = pd.concat([existing, new_rows], ignore_index=True)
        combined = combined.drop_duplicates(["date", "stock_id"]).sort_values(["date", "market", "stock_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        try:
            combined.to_csv(temporary, index=False, columns=PRICE_COLUMNS, encoding="utf-8-sig")
            for attempt in range(len(HISTORY_BACKOFF_SECONDS) + 1):
                try:
                    temporary.replace(path)  # Prior file stays intact if replacement fails.
                    break
                except PermissionError:
                    if attempt == len(HISTORY_BACKOFF_SECONDS):
                        raise
                    delay = HISTORY_BACKOFF_SECONDS[attempt]
                    LOGGER.warning("Price CSV is busy; retrying write after %s seconds", delay)
                    sleep(delay)
        finally:
            temporary.unlink(missing_ok=True)
    LOGGER.info("Saved records: %s", len(new_rows))
    LOGGER.info("Duplicate records skipped: %s", duplicates)
    return len(new_rows), duplicates
