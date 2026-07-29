"""
rebuild_clv.py — regrade season CLV from true historical closing lines.

The old CLV pipeline pulled "closing" lines at 10:30 PM keyed by team name,
which could pick up NEXT-day games (2026-07-28 bug). This rebuild uses the
odds API's historical snapshots: for each graded game, the DK line ~10
minutes before that game's actual first pitch — the real close.

Cost: 10 credits per snapshot, cached per unique start time (~6/day).
Writes clv_rebuilt.json and prints old-vs-rebuilt comparison.

Run:  py -3.11 .\\rebuild_clv.py
"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from glob import glob

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from features_v2 import flagged_side

API_KEY = os.environ.get("ODDS_API_KEY", "")
HIST_URL = "https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/odds/"


def implied(o):
    o = float(o)
    return (-o) / (-o + 100) * 100 if o < 0 else 100 / (o + 100) * 100


def schedule_starts(date_str):
    """(away, home) -> ISO start time (earliest game for doubleheaders)."""
    r = requests.get("https://statsapi.mlb.com/api/v1/schedule",
                     params={"sportId": 1, "date": date_str}, timeout=30).json()
    starts = {}
    for d in r.get("dates", []):
        for g in d.get("games", []):
            a = g["teams"]["away"]["team"]["name"]
            h = g["teams"]["home"]["team"]["name"]
            key = (a, h)
            if key not in starts or g["gameDate"] < starts[key]:
                starts[key] = g["gameDate"]
    return starts


_snap_cache = {}


def snapshot(iso_time):
    """Historical odds snapshot at/before iso_time. Cached per unique minute."""
    key = iso_time[:16]
    if key in _snap_cache:
        return _snap_cache[key]
    r = requests.get(HIST_URL, params={
        "apiKey": API_KEY, "regions": "us", "markets": "h2h",
        "oddsFormat": "american", "bookmakers": "draftkings",
        "date": iso_time}, timeout=30)
    data = r.json().get("data", []) if r.status_code == 200 else []
    _snap_cache[key] = data
    time.sleep(0.25)
    return data


def close_for(game_list, away, home):
    """DK closing american odds (away_odds, home_odds) from a snapshot."""
    for ev in game_list:
        if ev.get("home_team") == home and ev.get("away_team") == away:
            for bk in ev.get("bookmakers", []):
                for mkt in bk.get("markets", []):
                    if mkt.get("key") != "h2h":
                        continue
                    prices = {o["name"]: o["price"] for o in mkt.get("outcomes", [])}
                    if away in prices and home in prices:
                        return prices[away], prices[home]
    return None, None


def main():
    out = []
    for f in sorted(glob("picks_2026-*.csv")):
        d = f.replace("picks_", "").replace(".csv", "")
        try:
            starts = schedule_starts(d)
        except Exception:
            continue
        if not starts:
            continue
        n_done = 0
        for row in csv.DictReader(open(f, encoding="utf-8-sig")):
            ap, hp = row["Model Away%"], row["Model Home%"]
            if ap in ("None", "") or hp in ("None", ""):
                continue
            a, h = row["Away"], row["Home"]
            start = starts.get((a, h))
            if not start:
                continue
            snap_t = (datetime.fromisoformat(start.replace("Z", "+00:00"))
                      - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
            ao, ho = close_for(snapshot(snap_t), a, h)
            if ao is None:
                continue
            ap, hp = float(ap), float(hp)
            pick_home = hp > ap
            pick_prob = hp if pick_home else ap
            pick_close = implied(ho) if pick_home else implied(ao)
            rec = {"date": d, "away": a, "home": h,
                   "close_away": ao, "close_home": ho,
                   "clv_pick": round(pick_prob - pick_close, 2)}
            s = flagged_side(row) if "BET" in str(row.get("Flag", "")) else None
            if s:
                bp = ap if s == "away" else hp
                bc = implied(ao) if s == "away" else implied(ho)
                rec["clv_bet"] = round(bp - bc, 2)
            out.append(rec)
            n_done += 1
        print(f"{d}: {n_done} games rebuilt")
    json.dump(out, open("clv_rebuilt.json", "w"), indent=1)

    all_clv = [r["clv_pick"] for r in out]
    bet_clv = [r["clv_bet"] for r in out if "clv_bet" in r]
    print(f"\nREBUILT (true pre-pitch closes, {len(all_clv)} games):")
    print(f"  All picks CLV: {sum(all_clv)/len(all_clv):+.2f}% | beat close "
          f"{sum(1 for c in all_clv if c > 0)}/{len(all_clv)} "
          f"({sum(1 for c in all_clv if c > 0)/len(all_clv)*100:.0f}%)")
    if bet_clv:
        print(f"  Flagged-bet CLV: {sum(bet_clv)/len(bet_clv):+.2f}% | beat close "
              f"{sum(1 for c in bet_clv if c > 0)}/{len(bet_clv)} "
              f"({sum(1 for c in bet_clv if c > 0)/len(bet_clv)*100:.0f}%)")
    try:
        old = json.load(open("clv_log.json"))
        oc = [e["clv"] for e in old if e.get("clv") is not None]
        print(f"\nOLD (contaminated log, {len(oc)} games): avg {sum(oc)/len(oc):+.2f}% | "
              f"beat {sum(1 for c in oc if c > 0)/len(oc)*100:.0f}%")
    except Exception:
        pass


if __name__ == "__main__":
    main()
