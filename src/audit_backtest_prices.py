"""Describe saved price coverage without API calls or inferred listing dates."""
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from backtest_history import ROOT, CACHE, PROGRESS, valid_values, write_json


def main():
    manifest=json.loads((ROOT/"docs/data/backtest/manifest.json").read_text(encoding="utf-8"))
    state=json.loads(PROGRESS.read_text(encoding="utf-8"))
    current=pd.read_csv(ROOT/"data/market/stocks.csv",dtype={"stock_id":str})
    ids=set(current.stock_id); dates=manifest["trading_dates"]; date_set=set(dates)
    frames=[]; annual={}
    for item in manifest["years"]:
        frame=pd.read_csv(ROOT/f"data/prices/{item['year']}.csv",dtype={"stock_id":str})
        frame=frame[frame.stock_id.isin(ids)]
        good=frame.apply(lambda r:valid_values(r),axis=1)
        annual[str(item["year"])]=dict(rows=len(frame),stocks=int(frame.stock_id.nunique()),
            trading_dates=int(frame.date.nunique()),duplicates=int(frame.duplicated(["date","stock_id"]).sum()),
            invalid_ohlcv=int((~good).sum()),zero_volume=int((frame.volume==0).sum()),
            public_rows=item["rows"],public_bytes=item["bytes"],compressed_bytes=item["compressed_bytes"])
        frames.append(frame[good])
    all_rows=pd.concat(frames,ignore_index=True)
    seen={sid:set(group.date) for sid,group in all_rows.groupby("stock_id")}
    reasons=Counter(); cases=[]
    annual_missing={str(y["year"]):Counter() for y in manifest["years"]}
    for row in current.to_dict("records"):
        sid=row["stock_id"]; available=seen.get(sid,set()); missing=date_set-available
        if not available:
            counts={"no_quotes_in_entire_period":len(missing)}
            first=last=None
        else:
            first,last=min(available),max(available)
            counts={"before_first_observed_quote":sum(day<first for day in missing),
                    "after_last_observed_quote":sum(day>last for day in missing),
                    "internal_quote_gap":sum(first<day<last for day in missing)}
        reasons.update(counts)
        for day in missing:
            kind=("no_quotes_in_entire_period" if not available else
                  "before_first_observed_quote" if day<first else
                  "after_last_observed_quote" if day>last else "internal_quote_gap")
            annual_missing[day[:4]][kind]+=1
        if missing: cases.append({**row,"first_observed":first,"last_observed":last,
                                  "missing_sessions":len(missing),"missing_dates":";".join(sorted(missing)),**counts})
    for year, counts in annual_missing.items(): annual[year]["missing_quote_events"]=dict(counts)
    pd.DataFrame(cases).to_csv(ROOT/"data/state/price_history_missing.csv",index=False,encoding="utf-8-sig")
    # The full per-stock dates are in the CSV, keeping JSON examples compact.
    for row in cases: row.pop("missing_dates")
    # Original raw quotes are a local audit aid, not a deployment dependency.
    baseline_path=CACHE/"baseline_2026.csv"
    changed=None
    added_original=None
    if baseline_path.exists():
        baseline=pd.read_csv(baseline_path,dtype={"stock_id":str})
        final=pd.read_csv(ROOT/"data/prices/2026.csv",dtype={"stock_id":str})
        check=baseline.merge(final,on=["date","stock_id"],suffixes=("_old","_new"),how="left",validate="one_to_one")
        changed=0
        for field in ["open","high","low","close","volume"]:
            old=check[field+"_old"]; new=check[field+"_new"]
            changed+=int((~((old-new).abs().lt(1e-6)|(old.isna()&new.isna()))).sum())
        oldkeys=set(zip(baseline.date,baseline.stock_id))
        additions=final[["date","stock_id"]].apply(lambda r:(r.date,r.stock_id) not in oldkeys,axis=1)
        added_original=final[additions & final.date.between(baseline.date.min(),baseline.date.max())]
    source_counts=Counter(v["status"] for v in state["dates"].values())
    no_data=sorted({k.split(":")[0] for k,v in state["dates"].items() if v["status"]=="no_market_rows"})
    asymmetric=[]
    for day in dates:
        statuses={m:state["dates"].get(f"{day}:{m}",{}).get("status") for m in ("TWSE","TPEx")}
        if set(statuses.values())!={"saved"}: asymmetric.append({"date":day,**statuses})
    report={"cutoff":manifest["end"],"recent_year_start":manifest["recent_year_start"],
        "earliest_with_120_warmup":manifest["backtest_start"],
        "year_warmup_sessions":manifest["recent_year_warmup_sessions"],"annual":annual,
        "source_statuses":dict(source_counts),"official_no_market_weekdays":no_data,
        "asymmetric_source_dates":asymmetric,"missing_quote_events":dict(reasons),
        "stocks_with_missing_quotes":len(cases),"major_cases":sorted(cases,key=lambda r:-r["missing_sessions"])[:20],
        "major_internal_cases":sorted([r for r in cases if r.get("internal_quote_gap",0)],key=lambda r:-r["internal_quote_gap"])[:10],
        "major_after_last_cases":sorted([r for r in cases if r.get("after_last_observed_quote",0)],key=lambda r:-r["after_last_observed_quote"])[:10],
        "original_numeric_fields_changed":changed,
        "original_baseline_available":baseline_path.exists(),
        "added_in_original_period":len(added_original) if added_original is not None else None,
        "added_original_stock_count":int(added_original.stock_id.nunique()) if added_original is not None else None,
        "added_original_cases":added_original.head(20).to_dict("records") if added_original is not None else [],
        "reason_note":"Before/after observed quotes do not confirm listing/delisting dates. Internal gaps may be suspension, no trade or source omission; no prices are fabricated."}
    write_json(ROOT/"data/state/price_history_audit.json",report)
    print(json.dumps({k:v for k,v in report.items() if k not in ("major_cases","major_internal_cases","major_after_last_cases","added_original_cases")},ensure_ascii=False))


if __name__=="__main__":main()
