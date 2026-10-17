"""Configurable Quality, Growth, Momentum scores and input completeness."""

from strategy_engine import load_config, number, qgm_scores

CORE_FACTORS = (
    "roe_quarterly_approx", "gross_margin_single", "operating_margin_single",
    "debt_ratio", "operating_cash_flow_single", "free_cash_flow_single",
    "eps_positive_quarters_4", "revenue_yoy", "revenue_yoy_3m_avg",
    "eps_yoy", "gross_margin_yoy", "operating_margin_yoy", "close",
    "ma20", "ma60", "ma120", "return_20d", "return_60d",
    "avg_volume_20", "avg_volume_60", "distance_to_60d_high",
)


def score_factors(row, config=None):
    config = config or load_config()
    scores = qgm_scores(row, config)
    eps_rule = next(rule for rule in config["qgm"]["quality"] if rule["id"] == "eps_stability")
    flags = {
        "quality_roe": scores["quality_roe"] > 0,
        "quality_gross_margin": scores["quality_gross_margin"] > 0,
        "quality_operating_margin": scores["quality_operating_margin"] > 0,
        "quality_debt": scores["quality_debt"] > 0,
        "quality_ocf": scores["quality_ocf"] > 0,
        "quality_fcf": scores["quality_fcf"] > 0,
        "quality_eps_stability": scores["quality_eps_stability"] == max(
            tier["points"] for tier in eps_rule["tiers"]),
    }
    complete = sum(number(row.get(field)) is not None for field in CORE_FACTORS)
    return {**flags, **{key: value for key, value in scores.items() if key.startswith("score_")},
            "data_completeness": complete / len(CORE_FACTORS) * 100}
