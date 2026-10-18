from history_batch import annual_metrics
"""Build one local-only factor row per TWSE/TPEx stock."""

from datetime import datetime
from pathlib import Path

import pandas as pd

from config import (DIVIDENDS_DIR, FINANCIALS_DIR, PRICES_DIR, PROJECT_ROOT,
                    REVENUE_DIR, STOCKS_PATH, TAIWAN_TIME, VALUATION_DIR,
                    today_in_taiwan)
from fetch_market import is_financial_industry
from institutional_factors import load_context as load_institutional_context, stock_factors as institutional_stock_factors
from scoring import score_factors
from strategy_engine import load_config, strategy_data_completeness as calculate_strategy_completeness
from update_dividends import dividend_metrics


PRICE_FIELDS = ("ma20", "ma60", "ma120", "avg_volume_20", "avg_volume_60",
                "return_20d", "return_60d", "return_120d", "high_60d",
                "distance_to_60d_high")
REVENUE_FIELDS = ("latest_revenue", "revenue_mom", "revenue_yoy",
                  "revenue_yoy_3m_avg", "revenue_yoy_3m_positive_count")
FINANCIAL_FIELDS = ("eps_single", "eps_qoq", "eps_yoy", "gross_margin_single",
                    "gross_margin_qoq", "gross_margin_yoy", "operating_margin_single",
                    "operating_margin_qoq", "operating_margin_yoy", "roe_quarterly_approx",
                    "debt_ratio", "operating_cash_flow_single", "free_cash_flow_single",
                    "eps_ttm", "eps_positive_quarters_4", "eps_growth_positive_count_4",
                    "eps_positive_years", "operating_cash_flow_positive_years")
TOP_FIELDS = ("rank", "stock_id", "stock_name", "market", "close", "score_total",
              "score_quality", "score_growth", "score_momentum", "data_completeness",
              "eps_ttm", "eps_yoy", "revenue_yoy", "revenue_yoy_3m_avg", "roe",
              "gross_margin", "gross_margin_yoy", "operating_margin",
              "operating_margin_yoy", "debt_ratio", "free_cash_flow", "ma20", "ma60",
              "ma120", "return_20d", "return_60d", "distance_to_60d_high", "per", "pbr",
              "dividend_yield", "cash_dividend", "stock_dividend", "total_dividend",
              "cash_dividend_latest", "stock_dividend_latest", "total_dividend_latest",
              "payout_ratio", "dividend_years_5", "dividend_consecutive_years",
              "dividend_growth_3y", "updated_at")


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
    full_years = []
    for year, rows in group.groupby("year"):
        if set(pd.to_numeric(rows["quarter"], errors="coerce")) == {1, 2, 3, 4}:
            full_years.append((int(year), rows.sort_values("quarter")))
    full_years.sort(key=lambda item: item[0])
    if len(full_years) >= 3:
        recent_years = full_years[-3:]
        if [year for year, _ in recent_years] == list(range(recent_years[0][0], recent_years[0][0] + 3)):
            eps_years = [pd.to_numeric(rows["eps_single"], errors="coerce") for _, rows in recent_years]
            ocf_years = [pd.to_numeric(rows["operating_cash_flow_single"], errors="coerce") for _, rows in recent_years]
            if all(values.notna().all() for values in eps_years):
                result["eps_positive_years"] = sum(values.sum() > 0 for values in eps_years)
            if all(values.notna().all() for values in ocf_years):
                result["operating_cash_flow_positive_years"] = sum(values.sum() > 0 for values in ocf_years)
    return result


def calculate_factors(stocks_path=STOCKS_PATH, prices_dir=PRICES_DIR,
                      revenue_dir=REVENUE_DIR, financials_dir=FINANCIALS_DIR,
                      valuation_dir=VALUATION_DIR, dividends_dir=DIVIDENDS_DIR):
    """Use only local CSVs; no market or FinMind requests occur in this mode."""
    stocks = pd.read_csv(stocks_path, dtype={"stock_id": str}, encoding="utf-8-sig")
    price_rows = _read_years(prices_dir)
    if not price_rows.empty and "market" not in price_rows:
        price_rows["market"] = price_rows.stock_id.map(stocks.drop_duplicates("stock_id").set_index("stock_id").market)
    prices = _groups(price_rows, ["date"], ["stock_id", "date"])
    institutional = load_institutional_context(Path(stocks_path).resolve().parents[2], price_rows)
    revenue = _groups(_read_years(revenue_dir), ["year", "month"],
                      ["stock_id", "year", "month"])
    financials = _groups(_read_years(financials_dir), ["year", "quarter"],
                         ["stock_id", "year", "quarter"])
    valuations = _groups(_read_years(valuation_dir), ["date"], ["stock_id", "date"])
    dividend_path = Path(dividends_dir) / "history.csv"
    if dividend_path.exists():
        dividend_frame = pd.read_csv(dividend_path, dtype={"stock_id": str}, encoding="utf-8-sig")
    else:
        dividend_frame = _read_years(dividends_dir)
    annual_path = Path(dividends_dir).parent / "annual_financials" / "history.csv"
    annual_frame = pd.read_csv(annual_path, dtype={"stock_id": str}) if annual_path.exists() else pd.DataFrame()
    annuals = _groups(annual_frame, ["year"], ["stock_id", "year"])
    dividends = _groups(dividend_frame, ["year"], ["stock_id", "year"])
    updated_at = datetime.now(TAIWAN_TIME).isoformat(timespec="seconds")
    strategy_config = load_config()
    dividend_decline_tolerance = abs(strategy_config["strategy_e"]["conditions"]["dividend_non_decreasing"]["value"])
    records = []
    for stock in stocks.drop_duplicates("stock_id").itertuples(index=False):
        sid = str(stock.stock_id)
        price_group = prices.get(sid)
        latest = price_group.iloc[-1] if price_group is not None else None
        row = {"stock_id": sid, "stock_name": stock.stock_name, "market": stock.market,
               "industry": getattr(stock, "industry", pd.NA),
               "is_financial": is_financial_industry(getattr(stock, "industry", "")),
               "latest_date": latest["date"] if latest is not None else pd.NA,
               "close": _value(latest, "close") if latest is not None else float("nan"),
               "updated_at": updated_at}
        row.update(price_factors(price_group))
        row.update(institutional_stock_factors(stock.market, sid, row["latest_date"], institutional))
        reason = row["institutional_missing_reason"]
        if reason is None:
            for field in ("close", "ma20", "ma60", "ma120", "avg_volume_20",
                          "avg_volume_60", "distance_to_60d_high"):
                if pd.isna(row.get(field)):
                    reason = f"動能欄位缺值：{field}"
                    break
        row["strategy_d_missing_reason"] = reason
        row.update(revenue_factors(revenue.get(sid)))
        row.update(financial_factors(financials.get(sid)))
        row.update(annual_metrics(annuals.get(sid)))
        valuation = valuations.get(sid)
        if valuation is not None and not valuation.empty:
            snapshot = valuation.iloc[-1]
            row.update(per=_value(snapshot, "per"), pbr=_value(snapshot, "pbr"),
                       dividend_yield=_value(snapshot, "dividend_yield"),
                       valuation_date=snapshot.get("date", pd.NA))
        else:
            row.update(per=float("nan"), pbr=float("nan"), dividend_yield=float("nan"),
                       valuation_date=pd.NA)
        dividend_summary = dividend_metrics(
            dividends.get(sid), latest_dividend_year=today_in_taiwan().year - 1,
            tolerance_pct=dividend_decline_tolerance)
        row.update(dividend_summary)
        eps = row["annual_eps_2025"]
        row["payout_ratio"] = row["cash_dividend_latest"] / eps * 100 if pd.notna(eps) and eps > 0 else float("nan")
        dividend_rows = dividends.get(sid)
        if dividend_rows is not None and not dividend_rows.empty:
            annual_row = dividend_rows.loc[pd.to_numeric(dividend_rows.year, errors="coerce") == today_in_taiwan().year - 1]
        else:
            annual_row = pd.DataFrame()
        if not annual_row.empty and ("annual_complete" not in annual_row or str(annual_row.iloc[-1].get("annual_complete")).lower() == "true"):
            latest_dividend = annual_row.iloc[-1]
            row.update(cash_dividend_latest=_value(latest_dividend, "cash_dividend"),
                       stock_dividend_latest=_value(latest_dividend, "stock_dividend"),
                       total_dividend_latest=_value(latest_dividend, "total_dividend"))
        else:
            row.update(cash_dividend_latest=float("nan"), stock_dividend_latest=float("nan"),
                       total_dividend_latest=float("nan"))
        row.update(cash_dividend=row["cash_dividend_latest"],
                   stock_dividend=row["stock_dividend_latest"],
                   total_dividend=row["total_dividend_latest"])
        # Short names in the Top 200 output always mean the latest single quarter.
        row.update(roe=row["roe_quarterly_approx"], gross_margin=row["gross_margin_single"],
                   operating_margin=row["operating_margin_single"],
                   free_cash_flow=row["free_cash_flow_single"])
        row.update(score_factors(row))
        records.append(row)
    result = pd.DataFrame(records)
    market_return_60d = pd.to_numeric(result["return_60d"], errors="coerce").mean()
    result["market_return_60d_equal_weight"] = market_return_60d
    result["return_60d_vs_market"] = result["return_60d"] - market_return_60d
    for strategy_name in ("strategy_a", "strategy_b", "strategy_c", "strategy_d", "strategy_e"):
        result[f"{strategy_name}_data_completeness"] = [calculate_strategy_completeness(r, strategy_config[strategy_name]) for r in result.to_dict("records")]
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
