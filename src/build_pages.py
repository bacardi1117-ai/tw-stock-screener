"""Build GitHub Pages JSON from existing local factor files only."""

from pathlib import Path
import json
import shutil

import pandas as pd

from config import PROJECT_ROOT
from strategy_engine import evaluate_frame


PAGE_FIELDS = (
    "stock_id", "stock_name", "market", "industry", "is_financial", "latest_date", "close",
    "ma20", "ma60", "ma120", "avg_volume_20", "avg_volume_60",
    "return_20d", "return_60d", "return_120d", "distance_to_60d_high",
    "revenue_yoy", "revenue_yoy_3m_avg", "eps_yoy", "gross_margin_yoy",
    "operating_margin_yoy", "roe_quarterly_approx", "gross_margin_single",
    "operating_margin_single", "debt_ratio", "operating_cash_flow_single",
    "free_cash_flow_single", "eps_positive_quarters_4", "eps_ttm",
    "eps_positive_years", "operating_cash_flow_positive_years",
    "roe", "gross_margin", "operating_margin", "per", "pbr",
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
    return data_path, config_path, len(evaluated)
