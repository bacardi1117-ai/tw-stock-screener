"""Rate-limited, all-market historical quotes from the official daily JSON APIs."""

from datetime import date, timedelta
import json
import logging
import time

import pandas as pd
import requests

from config import (
    HISTORY_BACKOFF_SECONDS, HISTORY_EMPTY_DATES_PATH, HISTORY_MAX_RETRIES,
    HISTORY_REQUEST_INTERVAL, PRICES_DIR, REQUEST_TIMEOUT, TPEX_PRICES_URL,
    TWSE_PRICES_URL, today_in_taiwan,
)
from update_prices import _normalize, _table_rows, save_prices


LOGGER = logging.getLogger(__name__)
SOURCES = {
    "TWSE": (TWSE_PRICES_URL, {"證券代號", "收盤價", "成交股數"}),
    "TPEx": (TPEX_PRICES_URL, {"代號", "收盤", "成交股數"}),
}


class SourceStopped(Exception):
    """The source must not receive more requests during this run."""


def _params(market, day):
    if market == "TWSE":
        return {"date": day.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"}
    return {"date": day.strftime("%Y/%m/%d")}


def _known_empty():
    if not HISTORY_EMPTY_DATES_PATH.exists():
        return {market: set() for market in SOURCES}
    try:
        saved = json.loads(HISTORY_EMPTY_DATES_PATH.read_text(encoding="utf-8"))
        return {market: set(saved.get(market, [])) for market in SOURCES}
    except (OSError, ValueError, TypeError):
        LOGGER.warning("No-data date cache is unreadable; continuing without it")
        return {market: set() for market in SOURCES}


def _save_known_empty(cache):
    HISTORY_EMPTY_DATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = HISTORY_EMPTY_DATES_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps({market: sorted(days) for market, days in cache.items()}),
                         encoding="utf-8")
    temporary.replace(HISTORY_EMPTY_DATES_PATH)


def _request(session, market, day, counts, sleep=time.sleep):
    """Every HTTP attempt is counted and followed by at least one second of rest."""
    url, fields = SOURCES[market]
    for attempt in range(HISTORY_MAX_RETRIES + 1):
        counts[market] += 1
        try:
            response = session.get(url, params=_params(market, day), timeout=REQUEST_TIMEOUT)
            status = response.status_code
            if status == 429:
                LOGGER.warning("Rate limit detected. Historical update stopped safely.")
                raise SourceStopped("HTTP 429")
            if status == 403:
                if attempt == HISTORY_MAX_RETRIES:
                    LOGGER.warning("Access blocked or restricted by source.")
                    raise SourceStopped("HTTP 403")
            elif status >= 500:
                if attempt == HISTORY_MAX_RETRIES:
                    raise SourceStopped(f"HTTP {status}")
            else:
                response.raise_for_status()
                payload = response.json()
                return _table_rows(payload, fields, day, market)
        except SourceStopped:
            raise
        except (requests.Timeout, requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError) as exc:
            if attempt == HISTORY_MAX_RETRIES:
                raise SourceStopped(type(exc).__name__) from exc
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            raise SourceStopped(type(exc).__name__) from exc
        finally:
            sleep(HISTORY_REQUEST_INTERVAL)
        LOGGER.warning("%s request failed for %s; retrying after %s seconds",
                       market, day, HISTORY_BACKOFF_SECONDS[attempt])
        sleep(HISTORY_BACKOFF_SECONDS[attempt])
    raise SourceStopped("request attempts exhausted")


def _existing_keys(start, end):
    found = set()
    for year in range(start.year, end.year + 1):
        path = PRICES_DIR / f"{year}.csv"
        if path.exists():
            rows = pd.read_csv(path, usecols=["date", "market"], dtype=str)
            found.update(zip(rows["date"], rows["market"]))
    return found


def update_market_history(start, end, stocks, session=None, sleep=time.sleep):
    if start > end or end > today_in_taiwan():
        raise ValueError("History dates must be ordered and cannot be in the future")
    # An explicit safety bound prevents an accidental year-long backfill.
    if (end - start).days > 35:
        raise ValueError("One history run is limited to 36 calendar days")
    own_session = session is None
    session = session or requests.Session()  # No adapter-level retries: every attempt is visible.
    counts = {market: 0 for market in SOURCES}
    stopped = set()
    existing = _existing_keys(start, end)
    empty_dates = _known_empty()
    saved = duplicates = 0
    write_blocked = False
    try:
        day = start
        while day <= end:
            if day.weekday() < 5:
                for market in SOURCES:
                    key = (day.isoformat(), market)
                    if market in stopped or key in existing or day.isoformat() in empty_dates[market]:
                        continue
                    try:
                        rows = _request(session, market, day, counts, sleep)
                        if not rows:
                            LOGGER.info("No market data for %s (%s)", day, market)
                            if day < today_in_taiwan():
                                empty_dates[market].add(day.isoformat())
                                _save_known_empty(empty_dates)
                            continue
                        market_ids = set(stocks.loc[stocks["market"] == market, "stock_id"])
                        frame = _normalize(rows, market, day, market_ids)
                        if frame.empty:
                            LOGGER.info("No ordinary-stock records for %s (%s)", day, market)
                            continue
                        added, skipped = save_prices(frame, day)
                        saved += added
                        duplicates += skipped
                        existing.add(key)
                        LOGGER.info("%s %s price records: %s", day, market, len(frame))
                    except PermissionError as exc:
                        write_blocked = True
                        LOGGER.warning("Price CSV is locked or not writable; historical update stopped safely: %s", exc)
                        break
                    except (SourceStopped, ValueError, TypeError, KeyError) as exc:
                        stopped.add(market)
                        LOGGER.warning("%s historical source stopped for this run: %s", market, exc)
            day += timedelta(days=1)
            if write_blocked or len(stopped) == len(SOURCES):
                break
    finally:
        if own_session:
            session.close()
        LOGGER.info("TWSE requests: %s", counts["TWSE"])
        LOGGER.info("TPEx requests: %s", counts["TPEx"])
        LOGGER.info("Total HTTP requests: %s", sum(counts.values()))
        LOGGER.info("Historical records added: %s", saved)
        LOGGER.info("Duplicate records skipped: %s", duplicates)
    return {"requests": counts, "added": saved, "duplicates": duplicates,
            "stopped": stopped, "write_blocked": write_blocked}
