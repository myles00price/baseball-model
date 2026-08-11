"""
pen_usage_log.py — nightly collection of per-pitcher usage (pitches thrown,
innings, start vs relief) from free statsapi boxscores. This is the raw
material for the future bullpen-availability / reliever-entry trials
(Trial B): rest days, back-to-backs, workload — the usage data that recent
bullpen ERA cannot see. Collection only; nothing reads this in the live
model until a walk-forward trial earns it in.

Appends to pen_usage.csv (idempotent per date).
Run:  py -3.11 .\\pen_usage_log.py [YYYY-MM-DD | YYYY-MM-DD YYYY-MM-DD]
No args: collects yesterday + today.
"""

import csv
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

OUT = "pen_usage.csv"
FIELDS = ["date", "game_pk", "team", "pid", "name", "started", "ip", "pitches", "batters_faced"]


def _done_dates():
    if not os.path.exists(OUT):
        return set()
    with open(OUT, encoding="utf-8-sig") as f:
        return {r["date"] for r in csv.DictReader(f)}


def collect(date_str):
    """Collect one date's pitcher usage. Skips if already collected."""
    if date_str in _done_dates():
        return 0
    j = requests.get("https://statsapi.mlb.com/api/v1/schedule",
                     params={"sportId": 1, "date": date_str}, timeout=30).json()
    pks = [g["gamePk"] for dd in j.get("dates", []) for g in dd.get("games", [])
           if g.get("status", {}).get("codedGameState") == "F"]
    if not pks:
        return 0
    rows = []
    for pk in pks:
        try:
            b = requests.get(f"https://statsapi.mlb.com/api/v1/game/{pk}/boxscore",
                             timeout=30).json()
        except Exception:
            continue
        for side in ("away", "home"):
            t = b.get("teams", {}).get(side, {})
            team = t.get("team", {}).get("name", "")
            for pdata in t.get("players", {}).values():
                st = pdata.get("stats", {}).get("pitching", {})
                if not st or not st.get("battersFaced"):
                    continue
                rows.append({
                    "date": date_str, "game_pk": pk, "team": team,
                    "pid": pdata.get("person", {}).get("id", ""),
                    "name": pdata.get("person", {}).get("fullName", ""),
                    "started": int(st.get("gamesStarted", 0) or 0),
                    "ip": st.get("inningsPitched", ""),
                    "pitches": st.get("numberOfPitches", st.get("pitchesThrown", "")),
                    "batters_faced": st.get("battersFaced", ""),
                })
        time.sleep(0.05)
    new_file = not os.path.exists(OUT)
    with open(OUT, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        w.writerows(rows)
    print(f"pen usage {date_str}: {len(rows)} pitcher lines from {len(pks)} games")
    return len(rows)


def collect_recent():
    """Yesterday + today (Vegas clock). Safe to call from other scripts."""
    lv = timezone(timedelta(hours=-7))
    today = datetime.now(lv).date()
    for d in (today - timedelta(days=1), today):
        try:
            collect(d.isoformat())
        except Exception as e:
            print(f"{d}: {e} - skipped")


def main():
    lv = timezone(timedelta(hours=-7))
    if len(sys.argv) == 3:  # range backfill
        d0 = date.fromisoformat(sys.argv[1])
        d1 = date.fromisoformat(sys.argv[2])
        total = 0
        while d0 <= d1:
            try:
                total += collect(d0.isoformat())
            except Exception as e:
                print(f"{d0}: {e} - skipped")
            d0 += timedelta(days=1)
        print(f"backfill done: {total} lines")
    elif len(sys.argv) == 2:
        collect(sys.argv[1])
    else:
        collect_recent()


if __name__ == "__main__":
    main()
