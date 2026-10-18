"""Validate official endpoints and publish daily data over the newest main.

The disposable Actions checkout may lack ignored FinMind files. Rebuild the
public snapshot from its newest published financial fields, not from absent
local raw fundamentals. No network data is interpreted as zero.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calculate_factors import PRICE_FIELDS, price_factors
from config import (PROJECT_ROOT, REQUEST_TIMEOUT, TPEX_PRICES_URL,
                    TWSE_PRICES_URL, make_session)
from institutional_factors import load_context, stock_factors
from scoring import score_factors
from strategy_engine import evaluate_all, load_config, strategy_data_completeness
from update_institutional import (source_request, parse_tpex, parse_twse)
from update_prices import _table_rows

PRICE_KEYS = ("date", "stock_id")
INSTITUTIONAL_KEYS = ("date", "stock_id", "market")
PROGRESS_PATH = "data/state/institutional_progress.json"
SNAPSHOT_PATH = "docs/data/latest.json"


def git(*args, check=True):
    result = subprocess.run(["git", *args], cwd=PROJECT_ROOT, text=True,
                            capture_output=True, check=check)
    return result.stdout.strip()


def official_probe(root=PROJECT_ROOT, session=None):
    """One read-only request per market and report type, on a stored date."""
    root = Path(root)
    latest_file = max((root / "data/prices").glob("[0-9][0-9][0-9][0-9].csv"))
    prices = pd.read_csv(latest_file, usecols=["date"], dtype=str)
    day = prices.date.max()
    requested = date.fromisoformat(day)
    own_session = session is None
    session = session or make_session()
    results = {}
    try:
        for market, url, params, fields in (
            ("TWSE", TWSE_PRICES_URL,
             {"date": requested.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"},
             {"證券代號", "收盤價", "成交股數"}),
            ("TPEx", TPEX_PRICES_URL, {"date": requested.strftime("%Y/%m/%d")},
             {"代號", "收盤", "成交股數"}),
        ):
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            rows = _table_rows(response.json(), fields, requested, market)
            if not rows:
                raise RuntimeError(f"{market} price probe returned no rows for {day}")
            results[f"{market}_prices"] = len(rows)
        stocks = pd.read_csv(root / "data/market/stocks.csv", dtype={"stock_id": str})
        for market in ("TWSE", "TPEx"):
            url, params = source_request(market, day)
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            ids = set(stocks.loc[stocks.market == market, "stock_id"])
            frame = (parse_twse(response.json(), day, response.url, ids)
                     if market == "TWSE" else parse_tpex(response.content, day, response.url, ids))
            if frame.empty:
                raise RuntimeError(f"{market} institutional probe returned no ordinary stocks")
            results[f"{market}_institutional"] = len(frame)
    finally:
        if own_session:
            session.close()
    return {"date": day, **results}


def read_csv(path, keys):
    if not path.exists():
        return pd.DataFrame(columns=list(keys))
    return pd.read_csv(path, dtype={"date": str, "stock_id": str}, encoding="utf-8-sig")


def merge_csv(path, incoming, keys):
    old = read_csv(path, keys)
    if incoming.empty:
        return False
    existing = set(map(tuple, old.loc[:, list(keys)].itertuples(index=False, name=None)))
    added = incoming.loc[~incoming.loc[:, list(keys)].apply(tuple, axis=1).isin(existing)]
    if added.empty:
        return False
    merged = pd.concat([old, added], ignore_index=True).sort_values(list(keys))
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(path, index=False, encoding="utf-8-sig")
    return True


def merge_progress(path, incoming):
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"dates": {}}
    current.setdefault("dates", {})
    changed = False
    for key, value in incoming.get("dates", {}).items():
        prior = current["dates"].get(key)
        if prior is None or (prior.get("status") != "saved" and value.get("status") == "saved"):
            current["dates"][key] = value
            changed = True
    if changed:
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def _clean(value):
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    if hasattr(value, "item"):
        return _clean(value.item())
    return value


def refresh_snapshot(root=PROJECT_ROOT):
    """Overlay current quotes and Strategy D onto the newest remote snapshot."""
    root = Path(root)
    snapshot = root / SNAPSHOT_PATH
    records = json.loads(snapshot.read_text(encoding="utf-8"))
    price_files = sorted((root / "data/prices").glob("[0-9][0-9][0-9][0-9].csv"))
    prices = pd.concat([read_csv(path, PRICE_KEYS) for path in price_files], ignore_index=True)
    prices = prices.drop_duplicates(list(PRICE_KEYS), keep="last")
    groups = {str(sid): group.sort_values("date").reset_index(drop=True)
              for sid, group in prices.groupby("stock_id")}
    context = load_context(root, prices)
    config = load_config(root / "config/strategies.json")
    for row in records:
        group = groups.get(str(row["stock_id"]))
        latest = group.iloc[-1] if group is not None else None
        row["latest_date"] = latest["date"] if latest is not None else None
        row["close"] = _clean(latest["close"]) if latest is not None else None
        factors = price_factors(group)
        row.update({key: _clean(factors[key]) for key in PRICE_FIELDS if key in row})
        institutional = stock_factors(row["market"], str(row["stock_id"]), row["latest_date"], context)
        row.update({key: _clean(value) for key, value in institutional.items()})
        reason = row["institutional_missing_reason"]
        if reason is None:
            for field in ("close", "ma20", "ma60", "ma120", "avg_volume_20",
                          "avg_volume_60", "distance_to_60d_high"):
                if row.get(field) is None:
                    reason = f"動能欄位缺值：{field}"
                    break
        row["strategy_d_missing_reason"] = reason
    market_return = pd.to_numeric([row.get("return_60d") for row in records], errors="coerce").mean()
    for row in records:
        row["market_return_60d_equal_weight"] = _clean(market_return)
        ret = row.get("return_60d")
        row["return_60d_vs_market"] = _clean(ret - market_return) if ret is not None else None
        row.update({key: _clean(value) for key, value in score_factors(row, config).items()
                    if key.startswith("score_") or key == "data_completeness"})
        for name in (f"strategy_{letter}" for letter in "abcde"):
            row[f"{name}_data_completeness"] = strategy_data_completeness(row, config[name])
        row.update(evaluate_all(row, config))
    snapshot.write_text(json.dumps(records, ensure_ascii=False, allow_nan=False,
                                   separators=(",", ":")), encoding="utf-8")
    return {"stocks": len(records),
            "institutional_complete": sum(row["strategy_d_data_completeness"] == 100 for row in records),
            "strategy_d_pass": sum(row["strategy_d"] == "pass" for row in records),
            "latest_price_date": max((row["latest_date"] or "") for row in records),
            "latest_institutional_date": max((row["institutional_data_date"] or "") for row in records)}


def publish(max_attempts=4):
    """Replay runner CSV additions over latest main; retry concurrent pushes."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("publish is restricted to the disposable GitHub Actions checkout")
    data_paths = [path.relative_to(PROJECT_ROOT).as_posix()
                  for kind in ("prices", "institutional")
                  for path in sorted((PROJECT_ROOT / "data" / kind).glob("[0-9][0-9][0-9][0-9].csv"))]
    generated = {path: read_csv(PROJECT_ROOT / path, PRICE_KEYS if "prices" in path else INSTITUTIONAL_KEYS)
                 for path in data_paths}
    progress = json.loads((PROJECT_ROOT / PROGRESS_PATH).read_text(encoding="utf-8"))
    for attempt in range(max_attempts):
        git("fetch", "origin", "main")
        git("reset", "--hard", "origin/main")
        changed = []
        for name, frame in generated.items():
            keys = PRICE_KEYS if "prices" in name else INSTITUTIONAL_KEYS
            if merge_csv(PROJECT_ROOT / name, frame, keys):
                changed.append(name)
        if merge_progress(PROJECT_ROOT / PROGRESS_PATH, progress):
            changed.append(PROGRESS_PATH)
        if changed:
            metrics = refresh_snapshot()
            changed.append(SNAPSHOT_PATH)
        else:
            metrics = {"message": "No source data changed; no commit"}
        git("add", "--", *([*changed] if changed else [SNAPSHOT_PATH]))
        if not git("diff", "--cached", "--name-only"):
            return {"committed": False, "metrics": metrics}
        git("commit", "-m", "Update daily prices and institutional data")
        pushed = subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=PROJECT_ROOT,
                                text=True, capture_output=True)
        if pushed.returncode == 0:
            return {"committed": True, "sha": git("rev-parse", "HEAD"), "metrics": metrics}
        if "non-fast-forward" not in pushed.stderr and "fetch first" not in pushed.stderr:
            raise RuntimeError(f"Git push failed: {pushed.stderr.strip()}")
    raise RuntimeError("Main advanced during every publish attempt; retry the workflow")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("probe", "publish", "snapshot"))
    args = parser.parse_args()
    result = (official_probe() if args.mode == "probe" else
              publish() if args.mode == "publish" else refresh_snapshot())
    print(json.dumps(result, ensure_ascii=False))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write(f"### {args.mode}\n\n```json\n"
                          f"{json.dumps(result, ensure_ascii=False, indent=2)}\n```\n\n")
