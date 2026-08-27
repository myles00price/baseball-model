"""
clv_backfill.py — repair the silent CLV blackout (7/29 - present).

The 7/29 'fake closing lines' fix date-filtered the closing fetch; by the
10:30 PM grade the odds API has already dropped that day's finished games,
so every CLV entry since 7/29 was written with clv=None. Caught by the
owner 2026-08-27 (the beat rate had read 69% for a month).

This fills the null entries with TRUE pre-pitch closes via the historical
snapshot endpoint (10 credits per unique start minute, cached), same method
as rebuild_clv.py. Forward capture is now handled by k_close.py (ML close
snapshotted ~1h pre-pitch); check_results reads that first from today on.
    py -3.11 .\clv_backfill.py
"""
import csv, json, sys
from datetime import datetime, timedelta
from glob import glob
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
from rebuild_clv import schedule_starts, snapshot, close_for, implied

log = json.load(open("clv_log.json"))
nulls = [e for e in log if e.get("clv") is None]
print(f"{len(nulls)} null entries to repair")
starts_cache = {}
fixed = 0
for e in nulls:
    d = e["date"]
    if d not in starts_cache:
        try:
            starts_cache[d] = schedule_starts(d)
        except Exception:
            starts_cache[d] = {}
    start = starts_cache[d].get((e["away"], e["home"]))
    if not start:
        continue
    snap_t = (datetime.fromisoformat(start.replace("Z", "+00:00"))
              - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        ao, ho = close_for(snapshot(snap_t), e["away"], e["home"])
    except Exception:
        continue
    if ao is None:
        continue
    pick_home = e["model_pick"] == e["home"]
    ci = implied(ho) if pick_home else implied(ao)
    e["closing_odds"] = ho if pick_home else ao
    e["closing_implied"] = ci
    e["clv"] = round(float(e["model_prob"]) - ci, 2)
    e["clv_positive"] = e["clv"] > 0
    if e.get("opening_implied") is not None:
        e["open_close_drift"] = round(ci - float(e["opening_implied"]), 1)
    fixed += 1
json.dump(log, open("clv_log.json", "w"), indent=2)
nn = [x for x in log if x.get("clv") is not None]
v2 = [x for x in nn if x["date"] >= "2026-07-16"]
beat = sum(1 for x in v2 if x["clv"] > 0)
print(f"repaired {fixed} | v2-window now {beat}/{len(v2)} = {beat/len(v2)*100:.0f}% beat, "
      f"avg {sum(x['clv'] for x in v2)/len(v2):+.2f}%")
