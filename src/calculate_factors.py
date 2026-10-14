"""Build one local-only factor row per TWSE/TPEx stock."""

from datetime import datetime
from pathlib import Path

import pandas as pd

from config import FINANCIALS_DIR, PRICES_DIR, PROJECT_ROOT, REVENUE_DIR, STOCKS_PATH, TAIWAN_TIME
from scoring import score_factors


PRICE_FIELDS = ("ma20", "ma60", "ma120", "avg_volume_20", "avg_volume_60",
                "return_20d", "return_60d", "return_120d", "high_60d",
                "distance_to_60d_high")
REVENUE_FIELDS = ("latest_revenue", "revenue_mom", "revenue_yoy",
                  "revenue_yoy_3m_avg", "revenue_yoy_3m_positive_count")
FINANCIAL_FIELDS = ("eps_single", "eps_qoq", "eps_yoy", "gross_margin_single",
                    "gross_margin_qoq", "gross_margin_yoy", "operating_margin_single",
                    "operating_margin_qoq", "operating_margin_yoy", "roe_quarterly_approx",
                    "debt_ratio", "operating_cash_flow_single", "free_cash_flow_single",
                    "eps_ttm", "eps_positive_quarters_4", "eps_growth_positive_count_4")
TOP_FIELDS = ("rank", "stock_id", "stock_name", "market", "close", "score_total",
              "score_quality", "score_growth", "score_momentum", "data_completeness",
              "eps_ttm", "eps_yoy", "revenue_yoy", "revenue_yoy_3m_avg", "roe",
              "gross_margin", "gross_margin_yoy", "operating_margin",
              "operating_margin_yoy", "debt_ratio", "free_cash_flow", "ma20", "ma60",
              "ma120", "return_20d", "return_60d", "distance_to_60d_high", "updated_at")


def _read_years(directory):
    frames = [pd.read_csv(path, dtype={"stock_id": str}, encoding="utf-8-sig")
              for path in sorted(directory.glob("[0-9][0-9][0-9][0-9].csv"))]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _groups(frame, sort_fields, dedupe_fields):
    if frame.empty:
        return {}
    frame = frame.dropna(subset=["stock_id"]).drop_duplicates(dedupe_fields, keep="last")
    return {stock_id: group.sort_values(sort_fields).reset_index(drop=True)
            for stock_id, group in frame.groupby("stock_id", sort=False)}


def _value(row, column):
    return pd.to_numeric(row.get(column), errors="coerce")


def _consecutive(periods):
    return len(periods) > 0 and all(b - a == 1 for a, b in zip(periods, periods[1:]))


def price_factors(group):
    result = {field: float("nan") for field in PRICE_FIELDS}
    if group is None or group.empty:
        return result
    prices = pd.to_numeric(group["close"], errors="coerce")
    highs = pd.to_numeric(group["high"], errors="coerce") if "high" in group else prices
    volumes = pd.to_numeric(group["volume"], errors="coerce")
    for length in (20, 60, 120):
        if len(group) >= length and prices.iloc[-length:].notna().all():
            result[f"ma{length}"] = prices.iloc[-length:].mean()
        if len(group) > length and pd.notna(prices.iloc[-1]) and prices.iloc[-length-1] > 0:
            result[f"return_{length}d"] = (prices.iloc[-1] / prices.iloc[-length-1] - 1) * 100
    for length in (20, 60):
        if len(group) >= length and volumes.iloc[-length:].notna().all():
            result[f"avg_volume_{length}"] = volumes.iloc[-length:].mean()
    if len(group) >= 60 and highs.iloc[-60:].notna().all():
        high = highs.iloc[-60:].max()
        result["high_60d"] = high
        if high > 0 and pd.notna(prices.iloc[-1]):
            result["distance_to_60d_high"] = (prices.iloc[-1] / high - 1) * 100
    return result


def revenue_factors(group):
    result = {field: float("nan") for field in REVENUE_FIELDS}
    if group is None or group.empty:
        return result
    latest = group.iloc[-1]
    result.update(latest_revenue=_value(latest, "revenue"),
                  revenue_mom=_value(latest, "revenue_mom"),
                  revenue_yoy=_value(latest, "revenue_yoy"))
    if len(group) >= 3:
        recent = group.iloc[-3:]
        periods = (recent["year"].astype(int) * 12 + recent["month"].astype(int)).tolist()
        yoys = pd.to_numeric(recent["revenue_yoy"], errors="coerce")
        if _consecutive(periods) and yoys.notna().all():
            result["revenue_yoy_3m_avg"] = yoys.mean()
            result["revenue_yoy_3m_positive_count"] = int((yoys > 0).sum())
    return result


def financial_factors(group):
    result = {field: float("nan") for field in FINANCIAL_FIELDS}
    if group is None or group.empty:
        return result
    latest = group.iloc[-1]
    for field in FINANCIAL_FIELDS[:13]:
        result[field] = _value(latest, field)
    if len(group) >= 4:
        recent = group.iloc[-4:]
        periods = (recent["year"].astype(int) * 4 + recent["quarter"].astype(int)).tolist()
        if _consecutive(periods):
            eps = pd.to_numeric(recent["eps_single"], errors="coerce")
            growth = pd.to_numeric(recent["eps_yoy"], errors="coerce")
            if eps.notna().all():
                result["eps_ttm"] = eps.sum()
                result["eps_positive_quarters_4"] = int((eps > 0).sum())
            if growth.notna().all():
                result["eps_growth_positive_count_4"] = int((growth > 0).sum())
    return result


def calculate_factors(stocks_path=STOCKS_PATH, prices_dir=PRICES_DIR,
                      revenue_dir=REVENUE_DIR, financials_dir=FINANCIALS_DIR):
    """Use only local CSVs; no market or FinMind requests occur in this mode."""
    stocks = pd.read_csv(stocks_path, dtype={"stock_id": str}, encoding="utf-8-sig")
    prices = _groups(_read_years(prices_dir), ["date"], ["stock_id", "date"])
    revenue = _groups(_read_years(revenue_dir), ["year", "month"],
                      ["stock_id", "year", "month"])
    financials = _groups(_read_years(financials_dir), ["year", "quarter"],
                         ["stock_id", "year", "quarter"])
    updated_at = datetime.now(TAIWAN_TIME).isoformat(timespec="seconds")
    records = []
    for stock in stocks.drop_duplicates("stock_id").itertuples(index=False):
        sid = str(stock.stock_id)
        price_group = prices.get(sid)
        latest = price_group.iloc[-1] if price_group is not None else None
        row = {"stock_id": sid, "stock_name": stock.stock_name, "market": stock.market,
               "latest_date": latest["date"] if latest is not None else pd.NA,
               "close": _value(latest, "close") if latest is not None else float("nan"),
               "updated_at": updated_at}
        row.update(price_factors(price_group))
        row.update(revenue_factors(revenue.get(sid)))
        row.update(financial_factors(financials.get(sid)))
        # Short names in the Top 200 output always mean the latest single quarter.
        row.update(roe=row["roe_quarterly_approx"], gross_margin=row["gross_margin_single"],
                   operating_margin=row["operating_margin_single"],
                   free_cash_flow=row["free_cash_flow_single"])
        row.update(score_factors(row))
        records.append(row)
    result = pd.DataFrame(records)
    result = result.sort_values(["score_total", "score_growth", "score_quality",
                                 "score_momentum", "stock_id"],
                                ascending=[False, False, False, False, True]).reset_index(drop=True)
    result.insert(0, "rank", range(1, len(result) + 1))
    return result


def save_factors(frame, root=PROJECT_ROOT):
    factors_path = Path(root) / "data" / "factors" / "latest.csv"
    results_dir = Path(root) / "data" / "results"
    factors_path.parent.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(factors_path, index=False, encoding="utf-8-sig")
    top = frame.head(200).reindex(columns=TOP_FIELDS)
    top.to_csv(results_dir / "latest.csv", index=False, encoding="utf-8-sig")
    top.to_json(results_dir / "latest.json", orient="records", force_ascii=False, indent=2)
    return factors_path, results_dir / "latest.csv", results_dir / "latest.json"
