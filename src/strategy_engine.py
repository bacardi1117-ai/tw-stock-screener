"""Evaluate configurable QGM and stock strategies from local factor rows."""

from functools import lru_cache
import json
import math
from pathlib import Path

import pandas as pd


DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "strategies.json"
STRATEGIES = tuple(f"strategy_{letter}" for letter in "abcde")


@lru_cache(maxsize=1)
def load_config(path=DEFAULT_CONFIG):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _compare(left, op, right):
    return {"gt": left > right, "gte": left >= right,
            "lt": left < right, "lte": left <= right,
            "eq": left == right}[op]


def _round4(value):
    """Match JavaScript Math.round for nonnegative score values."""
    return math.floor(value * 10000 + 0.5) / 10000


def qgm_scores(row, config=None):
    """Return weighted scores and named rule points using the shared JSON rules."""
    config = config or load_config()
    qgm = config["qgm"]
    weights = [number(qgm[f"{name}_weight"]) for name in ("quality", "growth", "momentum")]
    if any(weight is None or weight < 0 for weight in weights) or abs(sum(weights) - 100) > 1e-8:
        raise ValueError("QGM weights must total 100")
    output = {}
    for category, weight in zip(("quality", "growth", "momentum"), weights):
        rules = qgm[category]
        earned = 0
        maximum = 0
        for rule in rules:
            maximum += max([0] + [tier["points"] for tier in rule.get("tiers", [])]) if rule["kind"] == "tiers" else rule["points"]
            points = 0
            if rule["kind"] == "tiers":
                value = number(row.get(rule["field"]))
                op = "gte" if rule["direction"] == "min" else "lte"
                if value is not None:
                    points = next((tier["points"] for tier in rule["tiers"]
                                   if _compare(value, op, tier["value"])), 0)
            elif rule["kind"] == "compare":
                value = number(row.get(rule["field"]))
                if value is not None and _compare(value, rule["op"], rule["value"]):
                    points = rule["points"]
            elif rule["kind"] == "fields":
                left, right = number(row.get(rule["left"])), number(row.get(rule["right"]))
                if left is not None and right is not None and _compare(left, rule["op"], right):
                    points = rule["points"]
            else:
                raise ValueError(f"Unknown QGM rule: {rule['kind']}")
            output[f"{category}_{rule['id']}"] = points
            earned += points
        output[f"score_{category}"] = _round4(earned / maximum * weight) if maximum else 0
    output["score_total"] = _round4(sum(output[f"score_{name}"] for name in ("quality", "growth", "momentum")))
    return output


def evaluate_strategy(row, strategy):
    if not strategy.get("enabled", True):
        return "unavailable"
    for field in strategy.get("availability_fields", []):
        if number(row.get(field)) is None:
            return "unavailable"
    missing = False
    failed = False
    for condition in strategy["conditions"].values():
        if not condition.get("enabled", True):
            continue
        left = number(row.get(condition["field"]))
        right = number(row.get(condition["right"])) if "right" in condition else number(condition.get("value"))
        if left is None or right is None:
            missing = True
        elif not _compare(left, condition["op"], right):
            failed = True
    if missing:
        return "missing_data"
    return "fail" if failed else "pass"


def evaluate_all(row, config=None):
    config = config or load_config()
    output = {}
    for name in STRATEGIES:
        status = evaluate_strategy(row, config[name])
        output[name] = status
        output[f"{name}_missing_data"] = status == "missing_data"
    return output


def evaluate_frame(frame, config=None):
    """Local-only default results for validation and generated Pages data."""
    config = config or load_config()
    return pd.concat([frame.reset_index(drop=True),
                      pd.DataFrame([evaluate_all(row, config) for row in frame.to_dict("records")])], axis=1)
