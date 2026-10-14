"""Normalize FinMind statements into quarterly figures and derived ratios."""

from datetime import date
import logging
import re

import pandas as pd

from config import FINANCIALS_DIR, FINMIND_DATASETS, FINMIND_INITIAL_DATE
from finmind_client import BudgetReached
from fundamentals_store import changed, read_years, safe_percent, safe_ratio, write_years


LOGGER = logging.getLogger(__name__)
FINANCIAL_COLUMNS = [
    "report_date", "year", "quarter", "stock_id", "stock_name",
    "eps_single", "revenue_single", "gross_profit_single", "operating_income_single",
    "net_income_single", "gross_margin_single", "operating_margin_single",
    "operating_cash_flow_cumulative", "operating_cash_flow_single",
    "capital_expenditure_cumulative", "capital_expenditure_single",
    "free_cash_flow_cumulative", "free_cash_flow_single", "roe_quarterly_approx",
    "eps", "eps_qoq", "eps_yoy",
    "revenue", "gross_profit", "gross_margin", "gross_margin_qoq", "gross_margin_yoy",
    "operating_income", "operating_margin", "operating_margin_qoq", "operating_margin_yoy",
    "net_income", "total_assets", "total_liabilities", "equity", "roe", "debt_ratio",
    "operating_cash_flow", "capital_expenditure", "free_cash_flow",
    "operating_cash_flow_ytd", "capital_expenditure_ytd",
]
RAW_FIELDS = (
    "eps", "revenue", "gross_profit", "operating_income", "net_income",
    "total_assets", "total_liabilities", "equity",
    "operating_cash_flow_ytd", "capital_expenditure_ytd",
)
TYPE_ALIASES = {
    "income": {
        "eps": ("EPS", "BasicEPS"),
        "revenue": ("Revenue", "OperatingRevenue", "NetRevenue"),
        "gross_profit": ("GrossProfit", "GrossProfitLoss"),
        "operating_income": ("OperatingIncome", "OperatingIncomeLoss"),
        "net_income": ("IncomeAfterTaxes", "NetIncome", "ProfitLoss"),
    },
    "balance": {
        "total_assets": ("Assets", "TotalAssets"),
        "total_liabilities": ("Liabilities", "TotalLiabilities"),
        "equity": ("Equity", "TotalEquity", "EquityAttributableToOwnersOfParent"),
    },
    "cash_flow": {
        "operating_cash_flow_ytd": ("CashFlowsFromOperatingActivities", "NetCashFlowsFromOperatingActivities"),
        "capital_expenditure_ytd": (
            "PropertyAndPlantAndEquipment",
            "PurchaseOfPropertyPlantAndEquipment",
            "AcquisitionOfPropertyPlantAndEquipment",
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "AcquisitionOfPropertyPlantAndEquipmentAndIntangibleAssets",
        ),
    },
}
CAPEX_ORIGIN = re.compile(r"(?:取得|購置|購買).*(?:不動產|廠房|設備)")


def _start_date(existing, stock_id):
    rows = existing.loc[existing["stock_id"] == stock_id]
    return str(rows["report_date"].max()) if not rows.empty else FINMIND_INITIAL_DATE


def _empty_record(stock_id, stock_name, report_date):
    day = date.fromisoformat(report_date)
    record = {column: float("nan") for column in FINANCIAL_COLUMNS}
    record.update({"report_date": report_date, "year": day.year,
                   "quarter": (day.month - 1) // 3 + 1,
                   "stock_id": stock_id, "stock_name": stock_name})
    return record


def _extract(rows, dataset, stock_id, stock_name):
    result = {}
    aliases = TYPE_ALIASES[dataset]
    for row in rows:
        try:
            report_date = date.fromisoformat(str(row["date"])).isoformat()
            if date.fromisoformat(report_date).month not in (3, 6, 9, 12):
                continue
            value = pd.to_numeric(row.get("value"), errors="coerce")
            if pd.isna(value):
                continue
            field_type = str(row.get("type", ""))
            for output, candidates in aliases.items():
                if field_type in candidates:
                    record = result.setdefault(report_date, _empty_record(stock_id, stock_name, report_date))
                    record[output] = float(value)
                    break
            else:
                if dataset == "cash_flow" and CAPEX_ORIGIN.search(str(row.get("origin_name", ""))):
                    record = result.setdefault(report_date, _empty_record(stock_id, stock_name, report_date))
                    record["capital_expenditure_ytd"] = float(value)
        except (KeyError, TypeError, ValueError):
            LOGGER.warning("Invalid financial row for %s", stock_id)
    return result


def _previous_key(year, quarter):
    return (year - 1, 4) if quarter == 1 else (year, quarter - 1)


def _difference(current, previous):
    current = pd.to_numeric(current, errors="coerce")
    previous = pd.to_numeric(previous, errors="coerce")
    return current - previous if not pd.isna(current) and not pd.isna(previous) else float("nan")


def _recalculate(frame):
    for column in RAW_FIELDS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    lookup = {(row.stock_id, int(row.year), int(row.quarter)): row for row in frame.itertuples(index=False)}
    calculated = []
    for row in frame.itertuples(index=False):
        year, quarter = int(row.year), int(row.quarter)
        previous = lookup.get((row.stock_id, *_previous_key(year, quarter)))
        year_ago = lookup.get((row.stock_id, year - 1, quarter))
        previous_equity = getattr(previous, "equity", float("nan")) if previous else float("nan")
        equity_base = (row.equity + previous_equity) / 2 if not pd.isna(previous_equity) and not pd.isna(row.equity) else row.equity
        gross_margin = safe_ratio(row.gross_profit, row.revenue)
        operating_margin = safe_ratio(row.operating_income, row.revenue)
        previous_gross = safe_ratio(previous.gross_profit, previous.revenue) if previous else float("nan")
        prior_gross = safe_ratio(year_ago.gross_profit, year_ago.revenue) if year_ago else float("nan")
        previous_operating = safe_ratio(previous.operating_income, previous.revenue) if previous else float("nan")
        prior_operating = safe_ratio(year_ago.operating_income, year_ago.revenue) if year_ago else float("nan")

        # FinMind cash-flow statements are year-to-date. Subtract the preceding
        # quarter's YTD value to obtain this quarter; Q1 is already standalone.
        prior_ytd = lookup.get((row.stock_id, year, quarter - 1)) if quarter > 1 else None
        ocf = row.operating_cash_flow_ytd if quarter == 1 else _difference(
            row.operating_cash_flow_ytd,
            prior_ytd.operating_cash_flow_ytd if prior_ytd else float("nan"),
        )
        # The acquisition/payment line may be negative in the source. Normalize
        # its YTD magnitude to positive spending before computing FCF.
        capex_ytd = abs(row.capital_expenditure_ytd) if not pd.isna(row.capital_expenditure_ytd) else float("nan")
        prior_capex_ytd = abs(prior_ytd.capital_expenditure_ytd) if prior_ytd and not pd.isna(prior_ytd.capital_expenditure_ytd) else float("nan")
        capex = capex_ytd if quarter == 1 else _difference(capex_ytd, prior_capex_ytd)
        if not pd.isna(capex) and capex < 0:
            capex = float("nan")  # A declining cumulative outlay needs source review.
        fcf = ocf - capex if not pd.isna(ocf) and not pd.isna(capex) else float("nan")
        cumulative_fcf = (row.operating_cash_flow_ytd - capex_ytd
                          if not pd.isna(row.operating_cash_flow_ytd) and not pd.isna(capex_ytd)
                          else float("nan"))
        roe = safe_ratio(row.net_income, equity_base)
        calculated.append({
            # The FinMind income statement already contains standalone quarters.
            # Do not subtract Q1 from Q2 EPS or profit; EPS also cannot be safely
            # summed into a reported cumulative EPS after share-count changes.
            "eps_single": row.eps,
            "revenue_single": row.revenue,
            "gross_profit_single": row.gross_profit,
            "operating_income_single": row.operating_income,
            "net_income_single": row.net_income,
            "gross_margin_single": gross_margin,
            "operating_margin_single": operating_margin,
            "operating_cash_flow_cumulative": row.operating_cash_flow_ytd,
            "operating_cash_flow_single": ocf,
            "capital_expenditure_cumulative": capex_ytd,
            "capital_expenditure_single": capex,
            "free_cash_flow_cumulative": cumulative_fcf,
            "free_cash_flow_single": fcf,
            "roe_quarterly_approx": roe,
            "eps_qoq": safe_percent(row.eps, previous.eps if previous else float("nan")),
            "eps_yoy": safe_percent(row.eps, year_ago.eps if year_ago else float("nan")),
            "gross_margin": gross_margin,
            "gross_margin_qoq": _difference(gross_margin, previous_gross),
            "gross_margin_yoy": _difference(gross_margin, prior_gross),
            "operating_margin": operating_margin,
            "operating_margin_qoq": _difference(operating_margin, previous_operating),
            "operating_margin_yoy": _difference(operating_margin, prior_operating),
            # First available quarter falls back to ending equity; later quarters
            # use average beginning/ending equity. Ratios are not annualized.
            "roe": roe,
            "debt_ratio": safe_ratio(row.total_liabilities, row.total_assets),
            "operating_cash_flow": ocf,
            "capital_expenditure": capex,
            "free_cash_flow": fcf,
        })
    for column in calculated[0] if calculated else []:
        frame[column] = [item[column] for item in calculated]
    return frame


def _needs_schema_migration():
    """Older local CSVs have unqualified aliases but not the explicit period columns."""
    for path in FINANCIALS_DIR.glob("[0-9][0-9][0-9][0-9].csv"):
        if "eps_single" not in pd.read_csv(path, nrows=0).columns:
            return True
    return False


def update_financials(client, stock_id, stock_name):
    LOGGER.info("Updating financials: %s", stock_id)
    migrate_schema = _needs_schema_migration()
    existing = read_years(FINANCIALS_DIR, FINANCIAL_COLUMNS)
    start = _start_date(existing, stock_id)
    incoming = {}
    budget_reached = False
    for dataset in ("income", "balance", "cash_flow"):
        try:
            rows = client.get(FINMIND_DATASETS[dataset], stock_id, start)
        except BudgetReached:
            budget_reached = True
            break
        if rows is None:
            continue
        for report_date, values in _extract(rows, dataset, stock_id, stock_name).items():
            target = incoming.setdefault(report_date, _empty_record(stock_id, stock_name, report_date))
            for column in RAW_FIELDS:
                if not pd.isna(values[column]):
                    target[column] = values[column]
    if not incoming and not migrate_schema:
        latest_existing = existing.loc[existing["stock_id"] == stock_id]
        return 0, 0, budget_reached, latest_existing.iloc[-1] if not latest_existing.empty else None
    by_key = {(str(row.stock_id), int(row.year), int(row.quarter)): row._asdict() for row in existing.itertuples(index=False)}
    added = updated = 0
    for values in incoming.values():
        key = (stock_id, int(values["year"]), int(values["quarter"]))
        if key not in by_key:
            by_key[key] = values
            added += 1
            continue
        changes = {column: values[column] for column in RAW_FIELDS if not pd.isna(values[column])}
        changes["stock_name"] = stock_name
        if changed(by_key[key], changes, changes):
            by_key[key].update(changes)
            updated += 1
    merged = pd.DataFrame(by_key.values(), columns=FINANCIAL_COLUMNS)
    merged["year"] = pd.to_numeric(merged["year"])
    merged["quarter"] = pd.to_numeric(merged["quarter"])
    merged = merged.sort_values(["stock_id", "year", "quarter"]).reset_index(drop=True)
    if added or updated or migrate_schema:
        merged = _recalculate(merged)
        write_years(merged, FINANCIALS_DIR, FINANCIAL_COLUMNS)
    latest = merged.loc[merged["stock_id"] == stock_id].iloc[-1] if not merged.empty else None
    return added, updated, budget_reached, latest
