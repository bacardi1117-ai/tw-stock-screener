"""Resolve attribution-year distributions without adding overlapping periods.

Verified evidence is curated from official publications, never inferred from a
missing API row. Cash and stock are independent components.
"""
import math

NAN = float("nan")
FIELDS = {"cash_dividend": ("CashEarningsDistribution", "CashStatutorySurplus"),
          "stock_dividend": ("StockEarningsDistribution", "StockStatutorySurplus")}
FULL_PERIODS = ({"A"}, {"H1", "H2"}, {"Q1", "Q2", "Q3", "Q4"})


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else NAN
    except (TypeError, ValueError):
        return NAN


def resolve_components(periods, evidence=None):
    evidence = evidence or {}
    if evidence and (evidence.get("year_basis") != "earnings_attribution" or
                     not evidence.get("source") or not evidence.get("checked_at")):
        raise ValueError("Dividend evidence requires source, verification date and attribution basis")
    amounts, methods = {}, {}
    for component, fields in FIELDS.items():
        values = {}
        for period, record in periods.items():
            parts = [number(record.get(field)) for field in fields]
            # This record may describe only the other component. Explicit zero
            # is still an observation; an entirely absent component is not.
            if not any(math.isfinite(v) for v in parts):
                continue
            values[period] = sum(parts) if all(math.isfinite(v) for v in parts) else NAN
        # Explicit official period observations can supply omitted zero rows.
        # A contradiction is reviewable, rather than silently overriding cache.
        for period, record in evidence.get("periods", {}).items():
            if component not in record:
                continue
            value = number(record[component])
            if not math.isfinite(value):
                raise ValueError("Verified dividend amount must be finite")
            if math.isfinite(values.get(period, NAN)) and not math.isclose(values[period], value, abs_tol=1e-8):
                raise ValueError(f"Official/cache dividend conflict: {component} {period}")
            values[period] = value
        proof = evidence.get("components", {}).get(component)
        if proof is not None:
            reference = number(proof.get("annual_value"))
            if not math.isfinite(reference) or reference < 0:
                raise ValueError("Verified annual dividend amount must be nonnegative")
            preserve = proof.get("preserve_periods")
            if preserve:
                selected = [values.get(p, NAN) for p in preserve]
                candidate = sum(selected)
                if not all(math.isfinite(v) for v in selected) or not math.isclose(
                        candidate, reference, rel_tol=0, abs_tol=proof.get("display_tolerance", 1e-8)):
                    raise ValueError("Official annual dividend does not reconcile with cached precision")
                amounts[component] = candidate
            else:
                # Curated full-year evidence takes one amount, never A + H/Q.
                amounts[component] = reference
            methods[component] = "official_verified_full_year"
            continue
        keys = set(values)
        if keys in FULL_PERIODS and all(math.isfinite(v) and v >= 0 for v in values.values()):
            amounts[component] = sum(values.values())
            methods[component] = "official_verified_periods" if evidence.get("periods") else "FinMind_full_period_set"
        else:
            amounts[component] = NAN
            methods[component] = "overlapping_or_incomplete_periods" if keys else "no_attribution_year_records"
        if component in evidence.get("review_required_components", []):
            methods[component] = "source_conflict_pending_review"
    return amounts, methods
