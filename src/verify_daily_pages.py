"""Wait for the public Pages site to expose the published daily fields."""

import json
from pathlib import Path
import sys
import time

import requests

ROOT = Path(__file__).resolve().parent.parent
URL = "https://bacardi1117-ai.github.io/tw-stock-screener/data/latest.json"


def signature(rows):
    return {str(row["stock_id"]): tuple(row.get(key) for key in (
        "latest_date", "close", "foreign_plus_trust_20d", "trust_10d",
        "institutional_data_date", "strategy_d_missing_reason")) for row in rows}


def main():
    expected = signature(json.loads((ROOT / "docs/data/latest.json").read_text(encoding="utf-8")))
    for attempt in range(31):
        try:
            response = requests.get(URL, params={"run": str(time.time_ns())}, timeout=30,
                                    headers={"Cache-Control": "no-cache"})
            response.raise_for_status()
            actual = signature(response.json())
            if actual == expected:
                print(json.dumps({"pages_url": URL, "stocks": len(actual),
                                  "status": "deployed and daily fields match"}))
                return
        except (requests.RequestException, ValueError) as exc:
            print(f"Pages check {attempt + 1}: {type(exc).__name__}", file=sys.stderr)
        if attempt < 30:
            time.sleep(20)
    raise SystemExit("Pages did not publish the expected daily snapshot within 10 minutes")


if __name__ == "__main__":
    main()
