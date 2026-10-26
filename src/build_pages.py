"""Build GitHub Pages JSON from existing local factor files only."""

from pathlib import Path
import json
import shutil

import pandas as pd

from config import PROJECT_ROOT
from eps_value_data import write_payload as write_eps_value_payload
from strategy_engine import evaluate_frame


PAGE_FIELDS = (
    "stock_id", "stock_name", "market", "industry", "is_financial", "latest_date", "close",
    "ma20", "ma60", "ma120", "avg_volume_20", "avg_volume_60",
    "foreign_plus_trust_20d", "trust_10d", "institutional_data_date", "institutional_missing_reason",
    "strategy_d_missing_reason",
    "return_20d", "return_60d", "return_120d", "distance_to_60d_high",
    "revenue_yoy", "revenue_yoy_3m_avg", "eps_yoy", "gross_margin_yoy",
    "operating_margin_yoy", "roe_quarterly_approx", "gross_margin_single",
    "operating_margin_single", "debt_ratio", "operating_cash_flow_single",
    "free_cash_flow_single", "eps_positive_quarters_4", "eps_ttm",
    "eps_positive_years", "operating_cash_flow_positive_years",
    "eps_positive_years_3", "ocf_positive_years_3",
    "annual_eps_2023", "annual_eps_2024", "annual_eps_2025",
    "annual_ocf_2023", "annual_ocf_2024", "annual_ocf_2025",
    "roe", "gross_margin", "operating_margin", "per", "pbr",
    "valuation_date", "dividend_yield", "cash_dividend", "stock_dividend", "total_dividend",
    "cash_dividend_latest", "dividend_years",
    "dividend_history_years_available",
    "stock_dividend_latest", "total_dividend_latest", "dividend_years_5",
    "dividend_consecutive_years", "payout_ratio", "dividend_growth_3y_cagr",
    "dividend_growth_3y", "dividend_min_change_3y_pct", "dividend_non_decreasing_3y",
    "strategy_a_data_completeness", "strategy_b_data_completeness",
    "strategy_c_data_completeness", "strategy_d_data_completeness",
    "strategy_e_data_completeness",
    "return_60d_vs_market", "market_return_60d_equal_weight",
    "data_completeness", "score_quality", "score_growth", "score_momentum", "score_total",
)


def build_pages(root=PROJECT_ROOT):
    root = Path(root)
    factors_path = root / "data" / "factors" / "latest.csv"
    if not factors_path.exists():
        raise FileNotFoundError(f"Run factors before building Pages: {factors_path}")
    frame = pd.read_csv(factors_path, dtype={"stock_id": str}, encoding="utf-8-sig",
                        float_precision="round_trip")
    evaluated = evaluate_frame(frame)
    data_path = root / "docs" / "data" / "latest.json"
    config_path = root / "docs" / "config" / "strategies.json"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    status_fields = tuple(field for letter in "abcde"
                          for field in (f"strategy_{letter}", f"strategy_{letter}_missing_data"))
    published = evaluated.reindex(columns=PAGE_FIELDS + status_fields)
    records = [{key: (None if pd.isna(value) else value.item() if hasattr(value, "item") else value)
                for key, value in row.items()}
               for row in published.to_dict("records")]
    with data_path.open("w", encoding="utf-8") as target:
        json.dump(records, target, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    shutil.copyfile(root / "config" / "strategies.json", config_path)
    write_eps_value_payload(root)
    return data_path, config_path, len(evaluated)
