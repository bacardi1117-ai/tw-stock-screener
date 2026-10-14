"""Build a local, reproducible universe for fundamentals collection."""

import logging
from pathlib import Path

import pandas as pd

from config import (
    EXCLUDE_FINANCIALS,
    FUNDAMENTALS_UNIVERSE_PATH,
    MIN_STOCK_PRICE,
    PRICES_DIR,
    STOCKS_PATH,
)
from fetch_market import fetch_industries, is_financial_industry
from fundamentals_batch import completed_from_local_data, load_progress, save_progress


LOGGER = logging.getLogger(__name__)
UNIVERSE_COLUMNS = [
    "stock_id", "stock_name", "market", "industry", "latest_close",
    "eligible", "exclude_reason",
]


def _write_csv_safely(frame, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    temporary.replace(path)


def _latest_prices(prices_dir):
    paths = sorted(Path(prices_dir).glob("[0-9][0-9][0-9][0-9].csv"))
    if not paths:
        return pd.DataFrame(columns=["stock_id", "latest_close"])
    frames = [pd.read_csv(path, dtype={"stock_id": str}, encoding="utf-8-sig",
                          usecols=lambda column: column in {"date", "stock_id", "close"})
              for path in paths]
    prices = pd.concat(frames, ignore_index=True)
    prices["stock_id"] = prices["stock_id"].astype(str).str.strip()
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices = prices.dropna(subset=["stock_id", "date", "close"])
    prices = prices.sort_values(["stock_id", "date"]).drop_duplicates("stock_id", keep="last")
    return prices.rename(columns={"close": "latest_close"})[["stock_id", "latest_close"]]


def build_fundamentals_universe(*, stocks_path=STOCKS_PATH,
                                prices_dir=PRICES_DIR,
                                universe_path=FUNDAMENTALS_UNIVERSE_PATH,
                                progress_path=None,
                                industry_fetcher=fetch_industries,
                                session=None):
    if not Path(stocks_path).exists():
        raise FileNotFoundError(f"Stock list is missing: {stocks_path}")
    stocks = pd.read_csv(stocks_path, dtype={"stock_id": str}, encoding="utf-8-sig")
    required = {"stock_id", "stock_name", "market"}
    if not required.issubset(stocks.columns):
        raise ValueError("Local stock list must contain stock_id, stock_name, and market")
    stocks["stock_id"] = stocks["stock_id"].astype(str).str.strip()
    if "industry" not in stocks.columns:
        stocks["industry"] = ""

    industries, succeeded = industry_fetcher(session)
    if succeeded:
        stocks["industry"] = stocks.apply(
            lambda row: industries.get(row["stock_id"], row["industry"]), axis=1
        )
        _write_csv_safely(stocks, stocks_path)
    elif stocks["industry"].fillna("").astype(str).str.strip().eq("").all():
        LOGGER.warning("Official industry data unavailable; unclassified stocks will be excluded")

    prices = _latest_prices(prices_dir)
    frame = stocks.merge(prices, on="stock_id", how="left")
    frame["industry"] = frame["industry"].fillna("").astype(str).str.strip()
    frame["latest_close"] = pd.to_numeric(frame["latest_close"], errors="coerce")

    financial = frame["industry"].map(lambda value: is_financial_industry(value))
    low_price = frame["latest_close"].notna() & frame["latest_close"].lt(MIN_STOCK_PRICE)
    missing_price = frame["latest_close"].isna()
    missing_industry = frame["industry"].eq("")
    eligible = ~(financial & EXCLUDE_FINANCIALS) & ~low_price & ~missing_price & ~missing_industry
    reasons = []
    for index in frame.index:
        if financial.loc[index] and EXCLUDE_FINANCIALS:
            reasons.append("financial")
        elif low_price.loc[index]:
            reasons.append("price_below_50")
        elif missing_price.loc[index]:
            reasons.append("missing_price")
        elif missing_industry.loc[index]:
            reasons.append("missing_industry")
        else:
            reasons.append("eligible")
    frame["eligible"] = eligible
    frame["exclude_reason"] = reasons
    frame = frame[UNIVERSE_COLUMNS].sort_values("stock_id").reset_index(drop=True)
    _write_csv_safely(frame, universe_path)

    state = load_progress(progress_path) if progress_path is not None else load_progress()
    eligible_ids = set(frame.loc[frame["eligible"], "stock_id"].astype(str))
    completed = set(str(value) for value in state.get("completed_stock_ids", [])) & eligible_ids
    completed.update(completed_from_local_data() & eligible_ids)
    failures = state.get("failure_reasons", {})
    failures = {str(stock_id): reason for stock_id, reason in failures.items()
                if str(stock_id) in eligible_ids and str(stock_id) not in completed}
    state.update({
        "completed_stock_ids": sorted(completed),
        "failed_stock_ids": sorted(failures),
        "failure_reasons": failures,
        "eligible_count": len(eligible_ids),
        "completed_count": len(completed),
        "remaining_count": len(eligible_ids) - len(completed),
        "failed_count": len(failures),
        "excluded_financial_count": int(financial.sum()) if EXCLUDE_FINANCIALS else 0,
        "excluded_price_count": int(low_price.sum()),
        "excluded_both_count": int((financial & low_price).sum()) if EXCLUDE_FINANCIALS else 0,
        "missing_price_count": int(missing_price.sum()),
        "missing_industry_count": int(missing_industry.sum()),
    })
    if progress_path is not None:
        save_progress(state, progress_path)
    else:
        save_progress(state)

    LOGGER.info("Universe stocks: %s", len(frame))
    LOGGER.info("Financial stocks excluded: %s", state["excluded_financial_count"])
    LOGGER.info("Stocks below minimum price: %s", state["excluded_price_count"])
    LOGGER.info("Stocks excluded by both conditions: %s", state["excluded_both_count"])
    LOGGER.info("Stocks missing price: %s", state["missing_price_count"])
    LOGGER.info("Eligible fundamentals stocks: %s", state["eligible_count"])
    LOGGER.info("Completed eligible stocks: %s", state["completed_count"])
    LOGGER.info("Remaining eligible stocks: %s", state["remaining_count"])
    return frame, state
