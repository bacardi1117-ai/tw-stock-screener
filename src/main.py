"""Simple CLI for environment checks and market data updates."""

import argparse
from datetime import date
import logging
import platform

import numpy
import pandas
import requests

from config import make_session, today_in_taiwan
from fetch_market import fetch_stocks, save_stocks
from update_prices import fetch_prices, save_prices


def check_environment() -> None:
    print(f"Python version: {platform.python_version()}")
    print(f"requests version: {requests.__version__}")
    print(f"pandas version: {pandas.__version__}")
    print(f"numpy version: {numpy.__version__}")

    if platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("This project requires Python 3.12")

    print("Environment OK")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the environment or update Taiwan market data")
    parser.add_argument("mode", nargs="?", choices=("env", "market"), default="env")
    parser.add_argument("--date", type=date.fromisoformat, default=None, help="Trading date: YYYY-MM-DD")
    args = parser.parse_args()
    if args.mode == "env":
        check_environment()
        return
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    requested = args.date or today_in_taiwan()
    with make_session() as session:
        stocks, succeeded = fetch_stocks(session)
        stocks = save_stocks(stocks, succeeded)
        prices = fetch_prices(session, requested, stocks)
        save_prices(prices, requested)


if __name__ == "__main__":
    main()
