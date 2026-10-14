"""Small CSV helpers shared by monthly and quarterly fundamentals."""

import logging

import pandas as pd


LOGGER = logging.getLogger(__name__)


def read_years(directory, columns):
    frames = []
    for path in sorted(directory.glob("[0-9][0-9][0-9][0-9].csv")):
        frame = pd.read_csv(path, dtype={"stock_id": str})
        for column in columns:
            if column not in frame:
                frame[column] = pd.NA
        frames.append(frame[columns])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)


def write_years(frame, directory, columns):
    if frame.empty:
        return
    directory.mkdir(parents=True, exist_ok=True)
    for year, group in frame.groupby("year"):
        path = directory / f"{int(year)}.csv"
        group[columns].to_csv(path, index=False, encoding="utf-8-sig")


def changed(old, new, fields):
    for field in fields:
        before, after = old.get(field), new.get(field)
        if pd.isna(before) and pd.isna(after):
            continue
        if pd.isna(before) != pd.isna(after) or before != after:
            return True
    return False


def safe_percent(current, base):
    current = pd.to_numeric(current, errors="coerce")
    base = pd.to_numeric(base, errors="coerce")
    if pd.isna(current) or pd.isna(base) or base <= 0:
        return float("nan")
    return (current / base - 1) * 100


def safe_ratio(numerator, denominator):
    numerator = pd.to_numeric(numerator, errors="coerce")
    denominator = pd.to_numeric(denominator, errors="coerce")
    if pd.isna(numerator) or pd.isna(denominator) or denominator <= 0:
        return float("nan")
    return numerator / denominator * 100
