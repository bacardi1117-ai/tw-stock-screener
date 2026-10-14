"""First-pass Quality, Growth, Momentum rules and 100-point QGM score."""

import math

import pandas as pd


# Every score input must be present for 100% completeness. Missing inputs score 0.
CORE_FACTORS = (
    "roe_quarterly_approx", "gross_margin_single", "operating_margin_single",
    "debt_ratio", "operating_cash_flow_single", "free_cash_flow_single",
    "eps_positive_quarters_4", "revenue_yoy", "revenue_yoy_3m_avg",
    "eps_yoy", "gross_margin_yoy", "operating_margin_yoy", "close",
    "ma20", "ma60", "ma120", "return_20d", "return_60d",
    "avg_volume_20", "avg_volume_60", "distance_to_60d_high",
)


def _number(value):
    value = pd.to_numeric(value, errors="coerce")
    return float(value) if pd.notna(value) and math.isfinite(float(value)) else None


def _at_least(value, thresholds):
    value = _number(value)
    return next((points for minimum, points in thresholds if value is not None and value >= minimum), 0)


def _at_most(value, thresholds):
    value = _number(value)
    return next((points for maximum, points in thresholds if value is not None and value <= maximum), 0)


def score_factors(row):
    """Return quality flags, category scores, total, and input completeness."""
    get = row.get
    roe = get("roe_quarterly_approx")
    gross = get("gross_margin_single")
    operating = get("operating_margin_single")
    debt = get("debt_ratio")
    ocf = _number(get("operating_cash_flow_single"))
    fcf = _number(get("free_cash_flow_single"))
    positive_eps = _number(get("eps_positive_quarters_4"))
    flags = {
        "quality_roe": _number(roe) is not None and _number(roe) >= 5,
        "quality_gross_margin": _number(gross) is not None and _number(gross) >= 15,
        "quality_operating_margin": _number(operating) is not None and _number(operating) >= 5,
        "quality_debt": _number(debt) is not None and _number(debt) <= 60,
        "quality_ocf": ocf is not None and ocf > 0,
        "quality_fcf": fcf is not None and fcf > 0,
        "quality_eps_stability": positive_eps == 4,
    }
    quality = (
        _at_least(roe, ((20, 10), (15, 8), (10, 6), (5, 3)))
        + _at_least(gross, ((40, 6), (25, 4), (15, 2)))
        + _at_least(operating, ((20, 6), (10, 4), (5, 2)))
        + _at_most(debt, ((30, 6), (45, 4), (60, 2)))
        + (3 if flags["quality_ocf"] else 0)
        + (3 if flags["quality_fcf"] else 0)
        + _at_least(positive_eps, ((4, 6), (3, 4), (2, 2)))
    )
    growth = (
        _at_least(get("revenue_yoy"), ((30, 10), (20, 8), (10, 6), (0, 3)))
        + _at_least(get("revenue_yoy_3m_avg"), ((20, 5), (10, 4), (0, 2)))
        + _at_least(get("eps_yoy"), ((50, 10), (30, 8), (15, 6), (0, 3)))
        + _at_least(get("gross_margin_yoy"), ((3, 5), (1, 4), (0, 2)))
        + _at_least(get("operating_margin_yoy"), ((3, 5), (1, 4), (0, 2)))
    )
    close = _number(get("close"))
    momentum = sum(
        points for field, points in (("ma20", 3), ("ma60", 4), ("ma120", 4))
        if close is not None and _number(get(field)) is not None and close > _number(get(field))
    )
    momentum += _at_least(get("return_20d"), ((10, 4), (5, 3), (0, 1)))
    momentum += _at_least(get("return_60d"), ((20, 5), (10, 4), (0, 2)))
    vol20, vol60 = _number(get("avg_volume_20")), _number(get("avg_volume_60"))
    momentum += 2 if vol20 is not None and vol60 is not None and vol20 > vol60 else 0
    momentum += _at_least(get("distance_to_60d_high"), ((-2, 3), (-5, 2), (-10, 1)))
    complete = sum(_number(get(field)) is not None for field in CORE_FACTORS)
    result = dict(flags)
    result.update(score_quality=quality, score_growth=growth, score_momentum=momentum,
                  score_total=quality + growth + momentum,
                  data_completeness=complete / len(CORE_FACTORS) * 100)
    return result
