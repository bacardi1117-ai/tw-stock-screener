"""CLI for environment, market, and FinMind fundamentals updates."""

import argparse
from datetime import date
import logging
import platform

import numpy
import pandas
import requests

from config import FINMIND_API_LIMIT, STOCKS_PATH, make_session, today_in_taiwan
from fetch_market import fetch_stocks, save_stocks
from finmind_client import ApiBudget, BudgetReached, FinMindClient, token_from_environment
from update_financials import update_financials
from update_prices import fetch_prices, save_prices
from update_revenue import update_revenue


def check_environment() -> None:
    print(f"Python version: {platform.python_version()}")
    print(f"requests version: {requests.__version__}")
    print(f"pandas version: {pandas.__version__}")
    print(f"numpy version: {numpy.__version__}")

    if platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("This project requires Python 3.12")

    print("Environment OK")


def update_fundamentals(stock_ids: str | None, limit: int | None) -> None:
    token = token_from_environment()
    if not token:
        logging.error("FINMIND_TOKEN is not set")
        return
    if not STOCKS_PATH.exists():
        logging.error("Stock list is missing: %s", STOCKS_PATH)
        return
    stocks = pandas.read_csv(STOCKS_PATH, dtype={"stock_id": str})
    if stock_ids:
        selected = list(dict.fromkeys(value.strip() for value in stock_ids.split(",") if value.strip()))
        stocks = stocks.loc[stocks["stock_id"].isin(selected)]
        missing = set(selected) - set(stocks["stock_id"])
        if missing:
            logging.warning("Stocks not found in local list: %s", ",".join(sorted(missing)))
        stocks = stocks.set_index("stock_id").reindex([sid for sid in selected if sid in set(stocks["stock_id"])]).reset_index()
    elif limit is not None:
        stocks = stocks.head(limit)
    else:
        logging.error("Specify --stocks or --limit for fundamentals")
        return
    logging.info("Stocks to update: %s", len(stocks))
    if stocks.empty:
        return
    try:
        client = FinMindClient(token, ApiBudget())
    except BudgetReached:
        logging.warning("FinMind API budget reached")
        return
    revenue_added = revenue_updated = financial_added = financial_updated = 0
    try:
        for row in stocks.itertuples(index=False):
            try:
                added, updated = update_revenue(client, row.stock_id, row.stock_name)
                revenue_added += added
                revenue_updated += updated
                added, updated, reached, latest = update_financials(client, row.stock_id, row.stock_name)
                financial_added += added
                financial_updated += updated
                if latest is not None:
                    for label, field, suffix in (
                        ("EPS", "eps", ""), ("gross margin", "gross_margin", "%"),
                        ("operating margin", "operating_margin", "%"),
                        ("ROE", "roe", "%"), ("debt ratio", "debt_ratio", "%"),
                    ):
                        value = pandas.to_numeric(latest[field], errors="coerce")
                        logging.info("%s %s: %s%s", row.stock_id, label,
                                     f"{value:.2f}" if pandas.notna(value) else "N/A",
                                     suffix if pandas.notna(value) else "")
                if reached:
                    logging.warning("FinMind API budget reached")
                    break
            except BudgetReached:
                logging.warning("FinMind API budget reached")
                break
    finally:
        client.close()
        logging.info("FinMind API calls: %s / %s", client.budget.count, FINMIND_API_LIMIT)
        logging.info("Revenue records added: %s", revenue_added)
        logging.info("Revenue records updated: %s", revenue_updated)
        logging.info("Financial records added: %s", financial_added)
        logging.info("Financial records updated: %s", financial_updated)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the environment or update Taiwan market data")
    parser.add_argument("mode", nargs="?", choices=("env", "market", "fundamentals"), default="env")
    parser.add_argument("--date", type=date.fromisoformat, default=None, help="Trading date: YYYY-MM-DD")
    parser.add_argument("--stocks", help="Comma-separated stock IDs for fundamentals")
    parser.add_argument("--limit", type=int, help="First N stocks from the local stock list")
    args = parser.parse_args()
    if args.mode == "env":
        check_environment()
        return
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    if args.mode == "fundamentals":
        if args.limit is not None and args.limit <= 0:
            parser.error("--limit must be positive")
        if args.stocks and args.limit is not None:
            parser.error("Use either --stocks or --limit")
        update_fundamentals(args.stocks, args.limit)
        return
    requested = args.date or today_in_taiwan()
    with make_session() as session:
        stocks, succeeded = fetch_stocks(session)
        stocks = save_stocks(stocks, succeeded)
        prices = fetch_prices(session, requested, stocks)
        save_prices(prices, requested)


if __name__ == "__main__":
    main()
