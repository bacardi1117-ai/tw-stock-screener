"""Wait for the public Pages site to expose the published daily fields."""

import json
import hashlib
from pathlib import Path
import sys
import time

import requests

ROOT = Path(__file__).resolve().parent.parent
URL = "https://bacardi1117-ai.github.io/tw-stock-screener/data/latest.json"


def main():
    expected_bytes = (ROOT / "docs/data/latest.json").read_bytes()
    expected = hashlib.sha256(expected_bytes).hexdigest()
    for attempt in range(31):
        try:
            response = requests.get(URL, params={"run": str(time.time_ns())}, timeout=30,
                                    headers={"Cache-Control": "no-cache"})
            response.raise_for_status()
            actual = hashlib.sha256(response.content).hexdigest()
            if actual == expected:
                print(json.dumps({"pages_url": URL,
                                  "snapshot_sha256": actual,
                                  "status": "deployed snapshot matches byte for byte"}))
                return
        except (requests.RequestException, ValueError) as exc:
            print(f"Pages check {attempt + 1}: {type(exc).__name__}", file=sys.stderr)
        if attempt < 30:
            time.sleep(20)
    raise SystemExit("Pages did not publish the expected daily snapshot within 10 minutes")


if __name__ == "__main__":
    main()
