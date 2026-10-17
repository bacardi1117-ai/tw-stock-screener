"""Update official TWSE/TPEx cash-dividend history and derived dividend metrics."""

from datetime import date
from io import BytesIO
import logging
import time

import pandas as pd
import requests

from config import DIVIDENDS_DIR, FINANCIALS_DIR, REQUEST_TIMEOUT


LOGGER = logging.getLogger(__name__)
TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap45_L"
TPEX_URL = "https://mopsfin.twse.com.tw/opendata/t187ap45_O.csv"
FIELDS = ["stock_id", "stock_name", "market", "year", "cash_dividend", "stock_dividend",
          "total_dividend", "annual_eps", "payout_ratio", "source_date"]


def _number(value):
    return pd.to_numeric(str(value).replace(",", "").strip(), errors="coerce")


def _sum_present(values):
    present = [value for value in values if pd.notna(value)]
    return sum(present) if present else float("nan")


def _year(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        number = int(raw)
    except ValueError:
        return None
    return number + 1911 if number < 1911 else number


def parse_twse(records):
    rows = []
    for item in records:
        year = _year(item.get("股利年度"))
        code = str(item.get("公司代號", "")).strip()
        if not year or not code or "特" in str(item.get("公司名稱", "")):
            continue
        progress = str(item.get("決議（擬議）進度", ""))
        values = [_number(item.get(key)) for key in (
            "股東配發-盈餘分配之現金股利(元/股)",
            "股東配發-法定盈餘公積發放之現金(元/股)",
            "股東配發-資本公積發放之現金(元/股)")]
        stock_values = [_number(item.get(key)) for key in (
            "股東配發-盈餘轉增資配股(元/股)", "股東配發-法定盈餘公積轉增資配股(元/股)",
            "股東配發-資本公積轉增資配股(元/股)")]
        rows.append({"stock_id": code, "stock_name": item.get("公司名稱"), "market": "TWSE",
                     "year": year, "cash_dividend": _sum_present(values),
                     "stock_dividend": _sum_present(stock_values),
                     "source_date": str(item.get("出表日期", "")), "_progress": progress,
                     "_period": str(item.get("股利所屬年(季)度", "")) + ":" +
                                str(item.get("股利所屬期間", item.get("期別", "")))})
    return rows


def parse_tpex(records):
    rows = []
    for item in records:
        year = _year(item.get("股利年度"))
        code = str(item.get("公司代號", "")).strip()
        if not year or not code:
            continue
        values = [_number(_first(item, keys)) for keys in (
            ("股東配發內容-盈餘分配之現金股利(元/股)", "股東配發-盈餘分配之現金股利(元/股)"),
            ("股東配發內容-法定盈餘公積、資本公積發放之現金(元/股)",
             "股東配發-法定盈餘公積發放之現金(元/股)"),
            ("股東配發-資本公積發放之現金(元/股)",))]
        stock_values = [_number(_first(item, keys)) for keys in (
            ("股東配發內容-盈餘轉增資配股(元/股)", "股東配發-盈餘轉增資配股(元/股)"),
            ("股東配發內容-法定盈餘公積、資本公積轉增資配股(元/股)",
             "股東配發-法定盈餘公積轉增資配股(元/股)"),
            ("股東配發-資本公積轉增資配股(元/股)",))]
        rows.append({"stock_id": code, "stock_name": item.get("公司名稱"), "market": "TPEx",
                     "year": year, "cash_dividend": _sum_present(values),
                     "stock_dividend": _sum_present(stock_values),
                     "source_date": str(item.get("出表日期", "")),
                     "_progress": str(item.get("決議（擬議）進度", "董事會通過")),
                     "_period": str(item.get("股利所屬年(季)度", "")) + ":" +
                                str(item.get("股利所屬期間", item.get("期別", "")))})
    return rows


def _first(item, candidates):
    return next((item.get(key) for key in candidates if item.get(key) not in (None, "")), None)


def _request(session, url, attempts=3, sleep=time.sleep):
    for attempt in range(attempts):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 429:
                raise RuntimeError("official dividend source rate-limited the request (429)")
            response.raise_for_status()
            if url.lower().endswith(".csv"):
                return pd.read_csv(BytesIO(response.content), dtype=str, encoding="utf-8-sig").to_dict("records")
            payload = response.json()
            if not isinstance(payload, list):
                raise ValueError("official dividend response is not a record list")
            return payload
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError, ValueError) as exc:
            if attempt + 1 == attempts:
                raise RuntimeError(f"dividend request failed: {type(exc).__name__}") from exc
            sleep((1, 3)[min(attempt, 1)])
    raise RuntimeError("dividend request exhausted retries")


def _annual_eps(financials_dir=FINANCIALS_DIR):
    frames = [pd.read_csv(path, dtype={"stock_id": str}, encoding="utf-8-sig")
              for path in financials_dir.glob("[0-9][0-9][0-9][0-9].csv")]
    if not frames:
        return {}
    frame = pd.concat(frames, ignore_index=True)
    frame["year"] = pd.to_numeric(frame.year, errors="coerce")
    frame["quarter"] = pd.to_numeric(frame.quarter, errors="coerce")
    frame["eps_single"] = pd.to_numeric(frame.eps_single, errors="coerce")
    result = {}
    for (stock_id, year), rows in frame.groupby(["stock_id", "year"]):
        if set(rows.quarter.dropna().astype(int)) == {1, 2, 3, 4} and rows.eps_single.notna().all():
            result[(str(stock_id), int(year))] = float(rows.eps_single.sum())
    return result


def _merge_rows(records, market, eps_map):
    if not records:
        return pd.DataFrame(columns=FIELDS)
    frame = pd.DataFrame(records)
    frame = frame.loc[frame.market == market]
    if frame.empty:
        return pd.DataFrame(columns=FIELDS)
    frame["_rank"] = frame._progress.map(
        lambda value: 3 if "股東會確認" in str(value) else 2 if any(
            state in str(value) for state in ("董事會通過", "董事會決議")) else 1)
    frame = frame.sort_values(["_rank", "source_date"]).drop_duplicates(
        ["stock_id", "year", "_period"], keep="last")
    representative = frame.sort_values(["_rank", "source_date"]).drop_duplicates(
        ["stock_id", "year"], keep="last").set_index(["stock_id", "year"])
    frame = frame.groupby(["stock_id", "year"], as_index=False).agg(
        cash_dividend=("cash_dividend", "sum"), stock_dividend=("stock_dividend", "sum"))
    frame = frame.join(representative[["stock_name", "market", "source_date", "_progress"]],
                       on=["stock_id", "year"])
    frame["annual_eps"] = [eps_map.get((str(sid), int(year)), float("nan")) for sid, year in zip(frame.stock_id, frame.year)]
    frame["total_dividend"] = frame.apply(
        lambda row: row.cash_dividend + row.stock_dividend
        if pd.notna(row.cash_dividend) and pd.notna(row.stock_dividend) else float("nan"), axis=1)
    frame["payout_ratio"] = frame.apply(
        lambda row: row.cash_dividend / row.annual_eps * 100
        if pd.notna(row.cash_dividend) and pd.notna(row.annual_eps) and row.annual_eps > 0
        else float("nan"), axis=1)
    return frame.reindex(columns=FIELDS)


def save_dividends(frame, directory=DIVIDENDS_DIR):
    if frame.empty:
        return 0
    directory = type(DIVIDENDS_DIR)(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "history.csv"
    prior = [pd.read_csv(item, dtype={"stock_id": str}, encoding="utf-8-sig")
             for item in sorted(directory.glob("[0-9][0-9][0-9][0-9].csv"))]
    if path.exists():
        prior.append(pd.read_csv(path, dtype={"stock_id": str}, encoding="utf-8-sig"))
    combined = pd.concat(prior + [frame], ignore_index=True, sort=False) if prior else frame.copy()
    for field in ("cash_dividend", "stock_dividend"):
        if field not in combined:
            combined[field] = float("nan")
    combined["stock_dividend"] = pd.to_numeric(combined.stock_dividend, errors="coerce")
    combined["cash_dividend"] = pd.to_numeric(combined.cash_dividend, errors="coerce")
    combined["total_dividend"] = combined.apply(
        lambda row: row.cash_dividend + row.stock_dividend
        if pd.notna(row.cash_dividend) and pd.notna(row.stock_dividend) else float("nan"), axis=1)
    combined = combined.drop_duplicates(["stock_id", "year"], keep="last").sort_values(["stock_id", "year"])
    temporary = path.with_suffix(".tmp")
    combined.reindex(columns=FIELDS).to_csv(temporary, index=False, encoding="utf-8-sig")
    temporary.replace(path)
    # The consolidated file is durable before the old per-year copies are removed.
    for old_path in directory.glob("[0-9][0-9][0-9][0-9].csv"):
        old_path.unlink()
    return len(frame)


def update_dividends(session=None, sleep=time.sleep, financials_dir=FINANCIALS_DIR):
    """Fetch two whole-market official dividend reports, then save annual rows incrementally."""
    own_session = session is None
    session = session or requests.Session()
    try:
        twse = parse_twse(_request(session, TWSE_URL, sleep=sleep))
        sleep(1)
        tpex = parse_tpex(_request(session, TPEX_URL, sleep=sleep))
        eps_map = _annual_eps(financials_dir)
        frames = [_merge_rows(twse, "TWSE", eps_map), _merge_rows(tpex, "TPEx", eps_map)]
        result = pd.concat(frames, ignore_index=True).drop_duplicates(["stock_id", "year"], keep="last")
        added = save_dividends(result)
        LOGGER.info("Official annual dividend rows saved or refreshed: %s", added)
        return {"rows": added, "years": sorted(result.year.astype(int).unique().tolist())}
    finally:
        if own_session:
            session.close()


def dividend_metrics(group, latest_dividend_year=None, tolerance_pct=5):
    """Summarize five completed dividend years; unavailable values stay NaN."""
    result = {key: float("nan") for key in (
        "dividend_years", "dividend_history_years_available", "dividend_consecutive_years", "cash_dividend_latest",
        "dividend_years_5", "dividend_growth_3y", "payout_ratio",
        "dividend_growth_3y_cagr", "dividend_min_change_3y_pct")}
    result["dividend_non_decreasing_3y"] = float("nan")
    if group is None or group.empty:
        return result
    frame = group.copy()
    frame["year"] = pd.to_numeric(frame.year, errors="coerce")
    frame["cash_dividend"] = pd.to_numeric(frame.cash_dividend, errors="coerce")
    frame["payout_ratio"] = pd.to_numeric(frame.payout_ratio, errors="coerce")
    frame = frame.dropna(subset=["year"]).sort_values("year").drop_duplicates("year", keep="last")
    last = int(latest_dividend_year or frame.year.max())
    recent = frame.loc[frame.year.between(last - 4, last)].set_index("year")
    result["dividend_history_years_available"] = int(recent.index.nunique())
    positive = {int(year) for year, value in recent.cash_dividend.items() if pd.notna(value) and value > 0}
    full_window = set(recent.index.astype(int)) == set(range(last - 4, last + 1))
    if full_window:
        result["dividend_years"] = len(positive)
        result["dividend_years_5"] = len(positive)
        consecutive = 0
        for year in range(last, last - 5, -1):
            if year not in positive:
                break
            consecutive += 1
        result["dividend_consecutive_years"] = consecutive
    latest = frame.loc[frame.year == last]
    if not latest.empty:
        result["cash_dividend_latest"] = latest.iloc[-1].cash_dividend
        result["payout_ratio"] = latest.iloc[-1].payout_ratio
    series = recent.loc[recent.cash_dividend.notna(), "cash_dividend"]
    years = series.index.astype(int).tolist()
    values = series.astype(float).tolist()
    if full_window and len(values) >= 4 and years[-4:] == list(range(years[-4], years[-4] + 4)) and all(v > 0 for v in values[-4:]):
        changes = [(values[i] / values[i - 1] - 1) * 100 for i in range(len(values) - 3, len(values))]
        result["dividend_growth_3y_cagr"] = ((values[-1] / values[-4]) ** (1 / 3) - 1) * 100
        result["dividend_growth_3y"] = result["dividend_growth_3y_cagr"]
        result["dividend_min_change_3y_pct"] = min(changes)
        result["dividend_non_decreasing_3y"] = float(min(changes) >= -abs(tolerance_pct))
    return result
