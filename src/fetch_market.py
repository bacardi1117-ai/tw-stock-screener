"""Fetch current ordinary-stock lists from TWSE and TPEx."""

import logging
import re

import pandas as pd
import requests

from config import STOCKS_PATH, TPEX_STOCKS_URL, TWSE_STOCKS_URL, get_json


LOGGER = logging.getLogger(__name__)
STOCK_COLUMNS = ["stock_id", "stock_name", "market"]
NON_ORDINARY_NAME = re.compile(r"(?:特別股|特股|受益證券|權證|ETN|ETF)", re.IGNORECASE)


def is_ordinary_stock(stock_id: str, stock_name: str) -> bool:
    """Phase 2 rule; keep this separate for future security classification."""
    return bool(re.fullmatch(r"\d{4}", stock_id.strip())) and not bool(
        NON_ORDINARY_NAME.search(stock_name)
    )


def _parse_stocks(rows, market: str, id_field: str, name_field: str) -> pd.DataFrame:
    if not isinstance(rows, list):
        raise ValueError(f"{market} stock response is not a JSON array")
    if rows and (id_field not in rows[0] or name_field not in rows[0]):
        raise ValueError(f"{market} stock fields changed")
    records = []
    for row in rows:
        stock_id = str(row.get(id_field, "")).strip()
        stock_name = str(row.get(name_field, "")).strip()
        if is_ordinary_stock(stock_id, stock_name):
            records.append((stock_id, stock_name, market))
    return pd.DataFrame(records, columns=STOCK_COLUMNS).drop_duplicates("stock_id")


def fetch_stocks(session: requests.Session) -> tuple[pd.DataFrame, set[str]]:
    sources = (
        ("TWSE", TWSE_STOCKS_URL, "公司代號", "公司簡稱"),
        ("TPEx", TPEX_STOCKS_URL, "SecuritiesCompanyCode", "CompanyAbbreviation"),
    )
    frames = []
    succeeded = set()
    for market, url, id_field, name_field in sources:
        try:
            frame = _parse_stocks(get_json(session, url), market, id_field, name_field)
            if frame.empty:
                raise ValueError("no ordinary stocks returned")
            frames.append(frame)
            succeeded.add(market)
            LOGGER.info("%s stocks loaded: %s", market, len(frame))
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            LOGGER.error("%s stock fetch failed: %s", market, exc)
            LOGGER.info("%s stocks loaded: 0", market)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=STOCK_COLUMNS)
    combined = combined.drop_duplicates("stock_id").sort_values(["market", "stock_id"])
    LOGGER.info("Total stocks: %s", len(combined))
    return combined.reset_index(drop=True), succeeded


def save_stocks(stocks: pd.DataFrame, succeeded: set[str]) -> pd.DataFrame:
    if not succeeded:
        LOGGER.warning("No stock list saved because both sources failed")
        return stocks
    if STOCKS_PATH.exists() and len(succeeded) < 2:
        previous = pd.read_csv(STOCKS_PATH, dtype={"stock_id": str})
        missing = previous.loc[~previous["market"].isin(succeeded), STOCK_COLUMNS]
        stocks = pd.concat([stocks, missing], ignore_index=True)
        stocks = stocks.drop_duplicates("stock_id").sort_values(["market", "stock_id"])
        LOGGER.warning("Preserved previous stock list for failed source")
    STOCKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    stocks.to_csv(STOCKS_PATH, index=False, encoding="utf-8-sig")
    LOGGER.info("Stock list saved: %s records", len(stocks))
    return stocks.reset_index(drop=True)
