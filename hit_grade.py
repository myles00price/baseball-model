"""hit_grade.py — nightly grader for the HIT WATCH training archive.

Joins each day's hit_log_{date}.csv (every eligible hitter's factors, model
probabilities, and book prices, written by hit_model.py each morning) to
the actual boxscore outcomes, and appends the graded rows to
hit_training_data.csv — one growing file, the dataset a real trained hit
model will learn from. Same rules as hr_grade.py:

  - only FINAL games are graded; unfinished games are retried on later runs
    (the last few days of logs are always re-checked)
  - idempotent: a (date, game_pk) pair is graded exactly once
  - DNP rows are kept with played=0

Outcome columns appended to hit_model.LOG_COLS:
  played (0/1), pa_actual, ab_actual, h_actual, hit_yes (0/1),
  hit2_yes (0/1), graded_at

Runs as part of the nightly BaseballCheckResults chain (called from
daily_results_notify.py, same pattern as hr_grade). Never texts.

Usage:
    python hit_grade.py            # grade any ungraded final games, last 4 days
    python hit_grade.py 2026-08-16 # grade one specific date's log
"""

import csv
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from hit_model import LOG_COLS, board_date

API = "https://statsapi.mlb.com/api/v1"
TRAIN_FN = "hit_training_data.csv"
OUT_COLS = LOG_COLS + ["played", "pa_actual", "ab_actual", "h_actual",
                       "hit_yes", "hit2_yes", "graded_at"]
LOOKBACK_DAYS = 4


def final_pks(session, date):
    try:
        j = session.get(f"{API}/schedule",
                        params={"sportId": 1, "date": date,
                                "fields": "dates,games,gamePk,status,detailedState"},
                        timeout=30).json()
    except Exception:
        return set()
    out = set()
    for day in j.get("dates", []):
        for g in day.get("games", []):
            if g.get("status", {}).get("detailedState") == "Final":
                out.add(g["gamePk"])
    return out


def boxscore_batting(session, pk):
    """{player_id: (pa, ab, h)} for everyone who batted in a game."""
    j = session.get(f"{API}/game/{pk}/boxscore", timeout=30).json()
    out = {}
    for side in ("away", "home"):
        players = j.get("teams", {}).get(side, {}).get("players", {})
        for key, p in players.items():
            st = p.get("stats", {}).get("batting", {})
            if not st:
                continue
            pa = st.get("plateAppearances")
            if pa is None:
                pa = (int(st.get("atBats", 0)) + int(st.get("baseOnBalls", 0))
                      + int(st.get("hitByPitch", 0)) + int(st.get("sacFlies", 0))
                      + int(st.get("sacBunts", 0)))
            out[p.get("person", {}).get("id")] = (
                int(pa), int(st.get("atBats", 0)), int(st.get("hits", 0)))
    return out


def graded_keys():
    if not os.path.exists(TRAIN_FN):
        return set()
    with open(TRAIN_FN, encoding="utf-8") as f:
        return {(r["date"], r["pk"]) for r in csv.DictReader(f)}


def grade_date(session, date, done, writer):
    """Grade one date's log. Returns (rows_written, hitters_with_hit, pks_graded)."""
    fn = f"hit_log_{date}.csv"
    if not os.path.exists(fn):
        return 0, 0, 0
    with open(fn, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    pending_pks = {r["pk"] for r in rows if (date, r["pk"]) not in done}
    if not pending_pks:
        return 0, 0, 0
    finals = {str(pk) for pk in final_pks(session, date)}
    todo = pending_pks & finals
    if not todo:
        return 0, 0, 0
    box = {}
    for pk in todo:
        try:
            box[pk] = boxscore_batting(session, pk)
        except Exception as e:
            print(f"  boxscore {pk} failed ({e}) - will retry next run")
            todo.discard(pk)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n = hits = 0
    for r in rows:
        pk = r["pk"]
        if pk not in box:
            continue
        pa, ab, h = box[pk].get(int(r["player_id"]), (0, 0, 0))
        out = {c: r.get(c, "") for c in LOG_COLS}
        out.update({"played": int(pa > 0), "pa_actual": pa, "ab_actual": ab,
                    "h_actual": h, "hit_yes": int(h > 0), "hit2_yes": int(h > 1),
                    "graded_at": stamp})
        writer.writerow(out)
        n += 1
        hits += h > 0
    return n, hits, len(box)


def migrate_schema():
    if not os.path.exists(TRAIN_FN):
        return
    with open(TRAIN_FN, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames == OUT_COLS:
            return
        rows = list(reader)
    with open(TRAIN_FN, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in OUT_COLS})
    print(f"hit_grade: migrated {TRAIN_FN} to {len(OUT_COLS)}-column schema "
          f"({len(rows)} rows)")


def run(dates=None):
    session = requests.Session()
    if dates is None:
        today = board_date()
        dates = [(datetime.strptime(today, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d")
                 for i in range(LOOKBACK_DAYS)]
    migrate_schema()
    done = graded_keys()
    new_file = not os.path.exists(TRAIN_FN)
    total = total_hits = 0
    with open(TRAIN_FN, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        if new_file:
            w.writeheader()
        for d in dates:
            n, hits, pks = grade_date(session, d, done, w)
            if n:
                print(f"{d}: graded {n} hitter rows across {pks} final games "
                      f"({hits} recorded a hit)")
            total += n
            total_hits += hits
    if total:
        with open(TRAIN_FN, encoding="utf-8") as f:
            all_n = sum(1 for _ in f) - 1
        print(f"hit_training_data.csv: +{total} rows ({total_hits} with a hit) -> {all_n} total")
    else:
        print("hit_grade: nothing new to grade")


if __name__ == "__main__":
    run([sys.argv[1]] if len(sys.argv) > 1 else None)
