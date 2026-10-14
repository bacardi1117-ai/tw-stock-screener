"""Central settings and HTTP access for the two official market sources."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STOCKS_PATH = PROJECT_ROOT / "data" / "market" / "stocks.csv"
FUNDAMENTALS_UNIVERSE_PATH = PROJECT_ROOT / "data" / "state" / "fundamentals_universe.csv"
PRICES_DIR = PROJECT_ROOT / "data" / "prices"
REVENUE_DIR = PROJECT_ROOT / "data" / "revenue"
FINANCIALS_DIR = PROJECT_ROOT / "data" / "financials"
FINMIND_BUDGET_PATH = PROJECT_ROOT / "data" / ".finmind_api_budget.json"
TAIWAN_TIME = timezone(timedelta(hours=8))

TWSE_STOCKS_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_STOCKS_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
TWSE_PRICES_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_PRICES_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
HISTORY_EMPTY_DATES_PATH = PRICES_DIR / ".history_no_data.json"
HISTORY_REQUEST_INTERVAL = 1.0
HISTORY_MAX_RETRIES = 3
HISTORY_BACKOFF_SECONDS = (2, 5, 10)

REQUEST_TIMEOUT = 20
MAX_ATTEMPTS = 3

FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
FINMIND_API_LIMIT = 500
FUNDAMENTALS_API_BUDGET_PER_RUN = 400
MAX_STOCKS_PER_RUN = 50
MIN_STOCK_PRICE = 50
EXCLUDE_FINANCIALS = True
FINMIND_TIMEOUT = 20
FINMIND_MAX_ATTEMPTS = 3
FINMIND_INITIAL_DATE = "2024-01-01"
FINMIND_DATASETS = {
    "revenue": "TaiwanStockMonthRevenue",
    "income": "TaiwanStockFinancialStatements",
    "balance": "TaiwanStockBalanceSheet",
    "cash_flow": "TaiwanStockCashFlowsStatement",
}


def today_in_taiwan():
    return datetime.now(TAIWAN_TIME).date()


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=MAX_ATTEMPTS - 1,
        connect=MAX_ATTEMPTS - 1,
        read=MAX_ATTEMPTS - 1,
        status=MAX_ATTEMPTS - 1,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "choose-stock/phase2 (public market data)"})
    return session


def get_json(session: requests.Session, url: str, **params):
    response = session.get(url, params=params or None, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()
