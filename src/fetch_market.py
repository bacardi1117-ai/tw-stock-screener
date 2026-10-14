"""Fetch current ordinary-stock lists from TWSE and TPEx."""

import logging
import re

import pandas as pd
import requests

from config import STOCKS_PATH, TPEX_STOCKS_URL, TWSE_STOCKS_URL, get_json


LOGGER = logging.getLogger(__name__)
STOCK_COLUMNS = ["stock_id", "stock_name", "market", "industry"]
NON_ORDINARY_NAME = re.compile(r"(?:特別股|特股|受益證券|權證|ETN|ETF)", re.IGNORECASE)
FINANCIAL_INDUSTRY_CODE = "17"
INDUSTRY_NAMES = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維",
    "05": "電機機械", "06": "電器電纜", "08": "玻璃陶瓷", "09": "造紙工業",
    "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業", "14": "建材營造",
    "15": "航運業", "16": "觀光餐旅", "17": "金融保險業", "18": "貿易百貨",
    "19": "綜合", "20": "其他", "21": "化學工業", "22": "生技醫療業",
    "23": "油電燃氣業", "24": "半導體業", "25": "電腦及週邊設備業",
    "26": "光電業", "27": "通信網路業", "28": "電子零組件業",
    "29": "電子通路業", "30": "資訊服務業", "31": "其他電子業",
    "32": "文化創意業", "33": "農業科技", "35": "綠能環保",
    "36": "數位雲端", "37": "運動休閒", "38": "居家生活", "80": "管理股票",
}
FINANCIAL_INDUSTRY_LABEL = re.compile(r"金融|銀行|證券|保險|金控")


def is_ordinary_stock(stock_id: str, stock_name: str) -> bool:
    """Phase 2 rule; keep this separate for future security classification."""
    return bool(re.fullmatch(r"\d{4}", stock_id.strip())) and not bool(
        NON_ORDINARY_NAME.search(stock_name)
    )


def industry_name(value) -> str:
    """Normalize official TWSE/TPEx industry codes to their display labels."""
    if value is None or pd.isna(value):
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    code = raw.zfill(2) if raw.isdigit() else raw
    return INDUSTRY_NAMES.get(code, raw if not raw.isdigit() else "")


def is_financial_industry(industry: str, industry_code: str | None = None) -> bool:
    code = str(industry_code or "").strip().zfill(2)
    label = str(industry or "").strip()
    return code == FINANCIAL_INDUSTRY_CODE or bool(FINANCIAL_INDUSTRY_LABEL.search(label))


def _parse_stocks(rows, market: str, id_field: str, name_field: str,
                  industry_field: str | None = None) -> pd.DataFrame:
    if not isinstance(rows, list):
        raise ValueError(f"{market} stock response is not a JSON array")
    if rows and (id_field not in rows[0] or name_field not in rows[0]):
        raise ValueError(f"{market} stock fields changed")
    records = []
    for row in rows:
        stock_id = str(row.get(id_field, "")).strip()
        stock_name = str(row.get(name_field, "")).strip()
        if is_ordinary_stock(stock_id, stock_name):
            industry = industry_name(row.get(industry_field, "")) if industry_field else ""
            records.append((stock_id, stock_name, market, industry))
    return pd.DataFrame(records, columns=STOCK_COLUMNS).drop_duplicates("stock_id")


def fetch_stocks(session: requests.Session) -> tuple[pd.DataFrame, set[str]]:
    sources = (
        ("TWSE", TWSE_STOCKS_URL, "公司代號", "公司簡稱", "產業別"),
        ("TPEx", TPEX_STOCKS_URL, "SecuritiesCompanyCode", "CompanyAbbreviation", "SecuritiesIndustryCode"),
    )
    frames = []
    succeeded = set()
    for market, url, id_field, name_field, industry_field in sources:
        try:
            frame = _parse_stocks(get_json(session, url), market, id_field,
                                  name_field, industry_field)
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
        if "industry" not in previous.columns:
            previous["industry"] = ""
        missing = previous.loc[~previous["market"].isin(succeeded)].reindex(
            columns=STOCK_COLUMNS, fill_value=""
        )
        stocks = pd.concat([stocks, missing], ignore_index=True)
        stocks = stocks.drop_duplicates("stock_id").sort_values(["market", "stock_id"])
        LOGGER.warning("Preserved previous stock list for failed source")
    STOCKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    stocks.to_csv(STOCKS_PATH, index=False, encoding="utf-8-sig")
    LOGGER.info("Stock list saved: %s records", len(stocks))
    return stocks.reset_index(drop=True)


def fetch_industries(session):
    """Fetch official industry classifications without calling FinMind."""
    sources = (
        ("TWSE", TWSE_STOCKS_URL, "公司代號", "產業別"),
        ("TPEx", TPEX_STOCKS_URL, "SecuritiesCompanyCode", "SecuritiesIndustryCode"),
    )
    industries = {}
    succeeded = set()
    for market, url, id_field, industry_field in sources:
        try:
            rows = get_json(session, url)
            if not isinstance(rows, list):
                raise ValueError("response is not a JSON array")
            count = 0
            for row in rows:
                stock_id = str(row.get(id_field, "")).strip()
                raw_code = str(row.get(industry_field, "")).strip()
                industry = industry_name(raw_code)
                if stock_id and industry:
                    industries[stock_id] = industry
                    count += 1
            if count == 0:
                raise ValueError("no industry classifications returned")
            succeeded.add(market)
            LOGGER.info("%s industry classifications loaded: %s", market, count)
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            LOGGER.error("%s industry fetch failed: %s", market, exc)
    return industries, succeeded
