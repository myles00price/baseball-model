"""hr_grade.py — nightly grader for the LONG BALL WATCH training archive.

Joins each day's hr_log_{date}.csv (every eligible hitter's factors, model
probability, and book prices, written by hr_model.py each morning) to the
actual boxscore outcomes, and appends the graded rows to
hr_training_data.csv — one growing file, the dataset a real trained HR
model will learn from.

Rules:
  - only FINAL games are graded; unfinished games are retried on later runs
    (the last few days of logs are always re-checked)
  - idempotent: a (date, game_pk) pair is graded exactly once
  - DNP rows are kept with played=0 — scratches and off-days are real
    outcomes of a pre-lineup prediction and a future model should know
    how often they happen

Outcome columns appended to hr_model.LOG_COLS:
  played (0/1), pa_actual, hr_actual, hr_yes (0/1), graded_at

Runs as part of the nightly BaseballCheckResults chain (called from
daily_results_notify.py, same pattern as pen_usage_log). Never texts.

Usage:
    python hr_grade.py            # grade any ungraded final games, last 4 days
    python hr_grade.py 2026-08-12 # grade one specific date's log
"""

import csv
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from hr_model import LOG_COLS, board_date

API = "https://statsapi.mlb.com/api/v1"
TRAIN_FN = "hr_training_data.csv"
OUT_COLS = LOG_COLS + ["played", "pa_actual", "hr_actual", "hr_yes", "graded_at"]
LOOKBACK_DAYS = 4


def final_pks(session, date):
    """Set of gamePks that are Final for a date."""
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
    """{player_id: (pa, hr)} for everyone who batted in a game."""
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
            out[p.get("person", {}).get("id")] = (int(pa), int(st.get("homeRuns", 0)))
    return out


def graded_keys():
    """{(date, pk)} already present in the training file."""
    if not os.path.exists(TRAIN_FN):
        return set()
    with open(TRAIN_FN, encoding="utf-8") as f:
        return {(r["date"], r["pk"]) for r in csv.DictReader(f)}


def grade_date(session, date, done, writer):
    """Grade one date's log. Returns (rows_written, hr_hits, pks_graded)."""
    fn = f"hr_log_{date}.csv"
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
        pa, hr = box[pk].get(int(r["player_id"]), (0, 0))
        out = {c: r.get(c, "") for c in LOG_COLS}
        out.update({"played": int(pa > 0), "pa_actual": pa, "hr_actual": hr,
                    "hr_yes": int(hr > 0), "graded_at": stamp})
        writer.writerow(out)
        n += 1
        hits += hr > 0
    return n, hits, len(box)


def migrate_schema():
    """If hr_model.LOG_COLS grew, rewrite the training file with the new
    header, blank-filling old rows. Keeps one consistent schema."""
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
    print(f"hr_grade: migrated {TRAIN_FN} to {len(OUT_COLS)}-column schema "
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
                      f"({hits} homered)")
            total += n
            total_hits += hits
    if total:
        with open(TRAIN_FN, encoding="utf-8") as f:
            all_n = sum(1 for _ in f) - 1
        print(f"hr_training_data.csv: +{total} rows ({total_hits} HR) -> {all_n} total")
    else:
        print("hr_grade: nothing new to grade")


if __name__ == "__main__":
    run([sys.argv[1]] if len(sys.argv) > 1 else None)
