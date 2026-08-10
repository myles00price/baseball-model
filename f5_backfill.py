"""
f5_backfill.py — backfills first-5-inning outcomes for every game in
training_data.csv (keyed by MLB gamePk) via free statsapi linescores.
Incremental: dates already in f5_outcomes.csv are skipped, so the weekly
retrain can call this to top up the current season cheaply.

Output: f5_outcomes.csv  (game_id, date, away_f5, home_f5, f5_home_win)
        f5_home_win: 1 home led after 5, 0 away led, blank = tied.

Run:  py -3.11 .\\f5_backfill.py
"""

import csv
import os
import sys
import time

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

OUT = "f5_outcomes.csv"


def fetch_date(d):
    j = requests.get("https://statsapi.mlb.com/api/v1/schedule",
                     params={"sportId": 1, "date": d, "hydrate": "linescore"},
                     timeout=30).json()
    rows = []
    for dd in j.get("dates", []):
        for g in dd.get("games", []):
            if g.get("status", {}).get("codedGameState") != "F":
                continue
            inns = g.get("linescore", {}).get("innings", [])
            if len(inns) < 5:
                continue
            a5 = sum(x.get("away", {}).get("runs", 0) or 0 for x in inns[:5])
            h5 = sum(x.get("home", {}).get("runs", 0) or 0 for x in inns[:5])
            rows.append({"game_id": g["gamePk"], "date": d, "away_f5": a5, "home_f5": h5,
                         "f5_home_win": "" if a5 == h5 else (1 if h5 > a5 else 0)})
    return rows


def main():
    need = {}
    with open("training_data.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            need.setdefault(r["date"], set()).add(r["game_id"])

    done_dates = set()
    existing = []
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8-sig") as f:
            existing = list(csv.DictReader(f))
        done_dates = {r["date"] for r in existing}

    todo = sorted(d for d in need if d not in done_dates)
    print(f"{len(need)} training dates; {len(todo)} to fetch")
    out = existing
    for i, d in enumerate(todo):
        try:
            out.extend(fetch_date(d))
        except Exception as e:
            print(f"  {d}: {e} — skipped")
        if i % 50 == 0:
            print(f"  {i}/{len(todo)}...")
        time.sleep(0.1)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["game_id", "date", "away_f5", "home_f5", "f5_home_win"])
        w.writeheader()
        w.writerows(out)
    ids = {str(r["game_id"]) for r in out}
    match = sum(1 for d in need for g in need[d] if g in ids)
    total = sum(len(v) for v in need.values())
    print(f"wrote {len(out)} rows -> {OUT}; training coverage {match}/{total}")


if __name__ == "__main__":
    main()
