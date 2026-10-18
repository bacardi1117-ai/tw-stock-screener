"""Strategy D inputs from complete market-day institutional windows."""

from pathlib import Path
import json

import pandas as pd


def read_years(directory):
    paths = sorted(Path(directory).glob("[0-9][0-9][0-9][0-9].csv"))
    frames = [pd.read_csv(path, dtype={"date": str, "stock_id": str}, encoding="utf-8-sig")
              for path in paths]
    if not frames:
        return pd.DataFrame(columns=["date", "stock_id", "market", "foreign_net", "trust_net"])
    return pd.concat(frames, ignore_index=True).drop_duplicates(["date", "stock_id", "market"], keep="last")


def make_context(prices, institutional, progress):
    calendars = {}
    if not prices.empty:
        for market, group in prices.groupby("market"):
            calendars[market] = sorted(group.date.dropna().astype(str).unique().tolist())
    groups = {}
    if not institutional.empty:
        for (market, sid), group in institutional.groupby(["market", "stock_id"]):
            groups[(market, sid)] = group.set_index("date")
    return calendars, groups, progress.get("dates", {})


def _reason(day, market, date_status, rows, field):
    if date_status.get(f"{day}:{market}", {}).get("status") != "saved":
        return f"來源日期缺漏：{day}"
    if day not in rows.index:
        return f"官方個股缺列：{day}"
    value = pd.to_numeric(rows.loc[day].get(field), errors="coerce")
    if pd.isna(value):
        return f"官方欄位缺值：{day} {field}"
    return None


def stock_factors(market, stock_id, latest_price_date, context):
    calendars, groups, date_status = context
    result = {"foreign_plus_trust_20d": float("nan"), "trust_10d": float("nan"),
              "institutional_data_date": None, "institutional_missing_reason": None}
    days = calendars.get(market, [])
    if len(days) < 20:
        result["institutional_missing_reason"] = "行情交易日不足 20 日"
        return result
    asof = days[-1]
    if str(latest_price_date) != asof:
        result["institutional_missing_reason"] = f"行情日期落後：{latest_price_date}"
        return result
    if date_status.get(f"{asof}:{market}", {}).get("status") == "saved":
        result["institutional_data_date"] = asof
    rows = groups.get((market, str(stock_id)))
    if rows is None:
        rows = pd.DataFrame(columns=["foreign_net", "trust_net"])
    missing = []
    for day in days[-20:]:
        for field in ("foreign_net", "trust_net"):
            reason = _reason(day, market, date_status, rows, field)
            if reason:
                missing.append(reason)
    if not missing:
        recent = rows.loc[days[-20:]]
        result["foreign_plus_trust_20d"] = int(pd.to_numeric(recent.foreign_net).sum() +
                                                pd.to_numeric(recent.trust_net).sum())
    # The 10-day trust value remains independently useful when the 20-day
    # window is incomplete. Neither window skips a missing market date.
    trust_missing = [_reason(day, market, date_status, rows, "trust_net") for day in days[-10:]]
    if not any(trust_missing):
        result["trust_10d"] = int(pd.to_numeric(rows.loc[days[-10:], "trust_net"]).sum())
    if missing:
        result["institutional_missing_reason"] = missing[0]
    return result


def load_context(root, prices):
    root = Path(root)
    path = root / "data/state/institutional_progress.json"
    progress = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"dates": {}}
    return make_context(prices, read_years(root / "data/institutional"), progress)
