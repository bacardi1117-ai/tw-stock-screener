"""Incremental TWSE/TPEx institutional trading, with explicit missing values."""

from __future__ import annotations

import csv
from datetime import datetime
import io
import json
import logging
from pathlib import Path
import re
import time

import pandas as pd
import requests

from config import PROJECT_ROOT, REQUEST_TIMEOUT, TAIWAN_TIME
from finmind_client import ApiBudget


LOGGER = logging.getLogger(__name__)
COLUMNS = ("date", "stock_id", "stock_name", "market", "foreign_buy", "foreign_sell",
           "foreign_net", "trust_buy", "trust_sell", "trust_net", "source_url")
TWSE_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_URL = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
TWSE_FIELDS = {
    "stock_id": "證券代號", "stock_name": "證券名稱",
    "foreign_buy": "外陸資買進股數(不含外資自營商)",
    "foreign_sell": "外陸資賣出股數(不含外資自營商)",
    "foreign_net": "外陸資買賣超股數(不含外資自營商)",
    "trust_buy": "投信買進股數", "trust_sell": "投信賣出股數",
    "trust_net": "投信買賣超股數",
}
TPEX_FIELDS = {
    "stock_id": "代號", "stock_name": "名稱",
    "foreign_buy": "外資及陸資(不含外資自營商)-買進股數",
    "foreign_sell": "外資及陸資(不含外資自營商)-賣出股數",
    "foreign_net": "外資及陸資(不含外資自營商)-買賣超股數",
    "trust_buy": "投信-買進股數", "trust_sell": "投信-賣出股數",
    "trust_net": "投信-買賣超股數",
}
NUMERIC = ("foreign_buy", "foreign_sell", "foreign_net", "trust_buy", "trust_sell", "trust_net")


class SourceFormatError(ValueError):
    """An official response cannot be safely mapped to the requested date/fields."""


def source_request(market, day):
    if market == "TWSE":
        return TWSE_URL, {"date": day.replace("-", ""), "response": "json", "selectType": "ALLBUT0999"}
    if market == "TPEx":
        year, month, date = map(int, day.split("-"))
        return TPEX_URL, {"d": f"{year-1911}/{month:02d}/{date:02d}",
                          "l": "zh-tw", "o": "csv", "se": "EW", "t": "D"}
    raise ValueError(f"Unknown market: {market}")


def _number(value):
    raw = str(value).strip().replace(",", "")
    if not raw or raw in {"--", "---", "N/A", "nan", "None"}:
        return None
    if not re.fullmatch(r"[+-]?\d+", raw):
        return None
    return int(raw)


def _columns(headers, names):
    # Duplicate generic TPEx JSON names cannot identify an institution. The
    # official CSV supplies qualified names; reject ambiguous source columns.
    result = {}
    for field, label in names.items():
        matches = [i for i, header in enumerate(headers) if str(header).strip() == label]
        if len(matches) != 1:
            raise SourceFormatError(f"Missing or ambiguous official column: {field}")
        result[field] = matches[0]
    return result


def _normalize(rows, headers, names, day, market, source_url, stock_ids):
    indexes = _columns(headers, names)
    result = []
    seen = set()
    for source in rows:
        if len(source) != len(headers):
            continue
        sid = str(source[indexes["stock_id"]]).strip()
        if sid not in stock_ids:
            continue
        if sid in seen:
            raise SourceFormatError(f"Duplicate stock row: {sid}")
        seen.add(sid)
        row = {"date": day, "stock_id": sid,
               "stock_name": str(source[indexes["stock_name"]]).strip(),
               "market": market, "source_url": source_url}
        for field in NUMERIC:
            row[field] = _number(source[indexes[field]])
        for prefix in ("foreign", "trust"):
            buy, sell, net = (row[f"{prefix}_{part}"] for part in ("buy", "sell", "net"))
            if buy is None or sell is None or net is None or buy - sell != net:
                row[f"{prefix}_buy"] = None
                row[f"{prefix}_sell"] = None
                row[f"{prefix}_net"] = None
        result.append(row)
    return pd.DataFrame(result, columns=COLUMNS)


def parse_twse(payload, day, source_url, stock_ids):
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        raise SourceFormatError("TWSE response is not a successful daily report")
    if str(payload.get("date")) != day.replace("-", ""):
        raise SourceFormatError("TWSE response date differs from requested date")
    headers, rows = payload.get("fields"), payload.get("data")
    if not isinstance(headers, list) or not isinstance(rows, list) or not rows:
        raise SourceFormatError("TWSE report has no table")
    return _normalize(rows, headers, TWSE_FIELDS, day, "TWSE", source_url, stock_ids)


def parse_tpex(content, day, source_url, stock_ids):
    try:
        text = content.decode("ms950")
    except UnicodeError as exc:
        raise SourceFormatError("TPEx CSV encoding changed") from exc
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 3:
        raise SourceFormatError("TPEx report has no table")
    title = rows[0][0].strip()
    match = re.match(r"^(\d+)年(\d+)月(\d+)日", title)
    if not match:
        raise SourceFormatError("TPEx report date is missing")
    year, month, date = map(int, match.groups())
    if f"{year+1911:04d}-{month:02d}-{date:02d}" != day:
        raise SourceFormatError("TPEx response date differs from requested date")
    headers = rows[1]
    _columns(headers, TPEX_FIELDS)
    values = [row for row in rows[2:] if len(row) == len(headers)]
    if not values:
        raise SourceFormatError("TPEx report has no stock rows")
    return _normalize(values, headers, TPEX_FIELDS, day, "TPEx", source_url, stock_ids)


def trading_dates(prices_dir):
    calendar = {"TWSE": set(), "TPEx": set()}
    for path in sorted(Path(prices_dir).glob("[0-9][0-9][0-9][0-9].csv")):
        for chunk in pd.read_csv(path, usecols=["date", "market"], dtype=str, chunksize=100000):
            for market, dates in chunk.groupby("market")["date"]:
                if market in calendar:
                    calendar[market].update(dates)
    return {market: sorted(dates) for market, dates in calendar.items()}


def _atomic_json(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _stored_counts(directory):
    counts = {}
    for path in Path(directory).glob("[0-9][0-9][0-9][0-9].csv"):
        frame = pd.read_csv(path, usecols=["date", "market"], dtype=str, encoding="utf-8-sig")
        for (day, market), amount in frame.groupby(["date", "market"]).size().items():
            counts[f"{day}:{market}"] = int(amount)
    return counts


def _save_market_day(root, frame, day, market, state):
    # This is the same OS lock used by the hourly history writer. Read and
    # merge the current files *after* acquiring it; never replace newer rows.
    with ApiBudget(path=root / "data/.history_batch_guard.json")._lock():
        path = root / "data/institutional" / f"{day[:4]}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        old = pd.read_csv(path, dtype={"date": str, "stock_id": str},
                          encoding="utf-8-sig") if path.exists() else pd.DataFrame(columns=COLUMNS)
        old = old.loc[~((old.date == day) & (old.market == market))]
        combined = pd.concat([old, frame], ignore_index=True).drop_duplicates(["date", "stock_id", "market"], keep="last")
        combined = combined.sort_values(["date", "market", "stock_id"])
        temporary = path.with_suffix(".tmp")
        combined.to_csv(temporary, index=False, columns=COLUMNS, encoding="utf-8-sig")
        temporary.replace(path)
        state["dates"][f"{day}:{market}"] = {
            "status": "saved", "rows": len(frame),
            "updated_at": datetime.now(TAIWAN_TIME).isoformat(timespec="seconds"),
        }
        _atomic_json(root / "data/state/institutional_progress.json", state)


def update_institutional(root=PROJECT_ROOT, *, days=25, start=None, end=None,
                         session=None, sleep=time.sleep, request_interval=1.0):
    """Fetch missing official date/market reports; no FinMind call is made."""
    if days < 20 or days > 90:
        raise ValueError("--days must be between 20 and 90")
    root = Path(root)
    calendars = trading_dates(root / "data/prices")
    stocks = pd.read_csv(root / "data/market/stocks.csv", dtype={"stock_id": str})
    progress_path = root / "data/state/institutional_progress.json"
    lock = ApiBudget(path=root / "data/.institutional_batch_guard.json")
    result = {"requested": 0, "saved": 0, "skipped": 0, "failed": 0, "by_market": {}}
    own_session = session is None
    session = session or requests.Session()
    try:
        with lock._lock():
            state = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {"dates": {}}
            state.setdefault("dates", {})
            stored_counts = _stored_counts(root / "data/institutional")
            for market in ("TWSE", "TPEx"):
                selected = [d for d in calendars[market] if (start is None or d >= start) and (end is None or d <= end)][-days:]
                ids = set(stocks.loc[stocks.market == market, "stock_id"])
                result["by_market"][market] = {"calendar_dates": len(selected), "saved": 0, "failed": 0}
                for day in selected:
                    key = f"{day}:{market}"
                    if (state["dates"].get(key, {}).get("status") == "saved" and
                            stored_counts.get(key) == state["dates"][key].get("rows")):
                        result["skipped"] += 1
                        continue
                    url, params = source_request(market, day)
                    try:
                        for attempt in range(3):
                            result["requested"] += 1
                            try:
                                response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                                if response.status_code in (403, 429):
                                    raise RuntimeError(f"HTTP {response.status_code}; stopping institutional run")
                                response.raise_for_status()
                                frame = (parse_twse(response.json(), day, response.url, ids) if market == "TWSE"
                                         else parse_tpex(response.content, day, response.url, ids))
                                if frame.empty:
                                    raise SourceFormatError("Official report contains no listed ordinary stock")
                                _save_market_day(root, frame, day, market, state)
                                stored_counts[key] = len(frame)
                                result["saved"] += 1
                                result["by_market"][market]["saved"] += 1
                                break
                            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                                if attempt == 2:
                                    raise exc
                                sleep((2, 5)[attempt])
                            finally:
                                sleep(request_interval)
                    except (requests.RequestException, ValueError, RuntimeError) as exc:
                        reason = type(exc).__name__ if not isinstance(exc, RuntimeError) else str(exc)
                        state["dates"][key] = {"status": "retryable", "error": reason,
                                                 "updated_at": datetime.now(TAIWAN_TIME).isoformat(timespec="seconds")}
                        with ApiBudget(path=root / "data/.history_batch_guard.json")._lock():
                            _atomic_json(progress_path, state)
                        result["failed"] += 1
                        result["by_market"][market]["failed"] += 1
                        LOGGER.warning("Institutional %s %s: %s", market, day, reason)
                        if isinstance(exc, RuntimeError) and ("HTTP 429" in str(exc) or "HTTP 403" in str(exc)):
                            return result
    finally:
        if own_session:
            session.close()
    return result
