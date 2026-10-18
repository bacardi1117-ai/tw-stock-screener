"""Publish only the local daily fields needed by the static backtest page.

This script does not fetch market data or touch the existing ingestion pipeline.
"""

import csv
import hashlib
import gzip
import json
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "prices"
STOCKS = ROOT / "data" / "market" / "stocks.csv"
TARGET = ROOT / "docs" / "data" / "backtest"
FIELDS = ("date", "stock_id", "open", "high", "low", "close", "volume")


def main() -> None:
    with STOCKS.open("r", encoding="utf-8-sig", newline="") as stream:
        names = {
            row["stock_id"]: {"name": row["stock_name"], "market": row["market"]}
            for row in csv.DictReader(stream)
            if re.fullmatch(r"\d{4}", row["stock_id"])
        }
    sources = sorted(SOURCE.glob("[0-9][0-9][0-9][0-9].csv"))
    if not sources:
        raise FileNotFoundError("No local daily price CSV exists")
    TARGET.mkdir(parents=True, exist_ok=True)
    years, dates, included, invalid = [], set(), set(), []
    for source in sources:
        target = TARGET / source.name
        temporary = target.with_suffix(".tmp")
        seen = set()
        count = 0
        first = last = None
        with source.open("r", encoding="utf-8-sig", newline="") as input_stream, \
                temporary.open("w", encoding="utf-8", newline="") as output_stream:
            reader = csv.DictReader(input_stream)
            if not set(FIELDS).issubset(reader.fieldnames or []):
                raise ValueError(f"Missing daily fields in {source.name}")
            writer = csv.DictWriter(output_stream, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            for row in reader:
                sid = row["stock_id"].strip()
                if sid not in names:
                    continue
                day = date.fromisoformat(row["date"])
                if day.year != int(source.stem):
                    raise ValueError(f"Date outside {source.name}")
                key = (row["date"], sid)
                if key in seen:
                    raise ValueError(f"Duplicate daily bar: {key}")
                seen.add(key)
                try:
                    values = [float(row[field]) for field in ("open", "high", "low", "close")]
                    volume = float(row["volume"])
                    valid = (all(math.isfinite(v) and v > 0 for v in values) and
                             values[1] >= max(values) and values[2] <= min(values) and
                             math.isfinite(volume) and volume >= 0 and volume.is_integer())
                except (ValueError, TypeError):
                    valid = False
                if not valid:
                    invalid.append({"date": row["date"], "stock_id": sid, "reason": "invalid_ohlcv"})
                    continue  # Suspended/no-quote rows are never invented or forward-filled.
                writer.writerow({field: row[field] for field in FIELDS})
                dates.add(row["date"])
                included.add(sid)
                first = min(first, row["date"]) if first else row["date"]
                last = max(last, row["date"]) if last else row["date"]
                count += 1
        temporary.replace(target)
        compressed = target.with_suffix(".csv.gz")
        gz_tmp = compressed.with_suffix(".gz.tmp")
        gz_tmp.write_bytes(gzip.compress(target.read_bytes(), mtime=0))
        gz_tmp.replace(compressed)
        years.append({"year": int(source.stem), "file": source.name, "rows": count,
                      "start": first, "end": last,
                      "bytes": target.stat().st_size, "compressed_file": compressed.name,
                      "compressed_bytes": compressed.stat().st_size,
                      "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    ordered_dates = sorted(dates)
    cutoff = date.fromisoformat(ordered_dates[-1])
    try:
        anniversary = cutoff.replace(year=cutoff.year - 1).isoformat()
    except ValueError:
        anniversary = cutoff.replace(year=cutoff.year - 1, day=28).isoformat()
    recent_start = next(day for day in ordered_dates if day > anniversary)
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "volume_unit": "shares",
        "lot_size_shares": 1000,
        "price_adjustment": "none",
        "source": "locally stored TWSE and TPEx ordinary-stock daily OHLCV",
        "start": min(dates), "end": max(dates),
        "trading_dates": ordered_dates,
        "warmup_sessions": 120,
        "backtest_start": ordered_dates[120] if len(ordered_dates) > 120 else None,
        "recent_year_start": recent_start,
        "recent_year_warmup_sessions": ordered_dates.index(recent_start),
        "recent_year_complete": ordered_dates[0] <= anniversary and ordered_dates.index(recent_start) >= 120,
        "stock_count": len(included),
        "stocks": {sid: names[sid] for sid in sorted(included)},
        "years": years,
    }
    temporary = TARGET / "manifest.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
                         encoding="utf-8")
    temporary.replace(TARGET / "manifest.json")
    audit_path = ROOT / "data/state/backtest_price_exclusions.json"
    audit_path.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
    print(f"Published {sum(item['rows'] for item in years)} local rows, "
          f"{len(dates)} sessions, {len(included)} stocks; no network requests")


if __name__ == "__main__":
    main()
