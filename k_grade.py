"""k_grade.py — nightly grader for the K WATCH training archive.

Joins each day's k_log_{date}.csv (every probable starter's factors, model
distribution and book prices, frozen each morning by k_model.py) and the
day's k_lock_{date}.csv (the same row re-evaluated at the moment the
opposing lineup first posted, if it did) to the actual boxscore strikeout
totals, and appends the graded rows to k_training_data.csv. Same rules as
hr_grade / hit_grade:

  - only FINAL games are graded; unfinished games retry on later runs
    (the last few days of logs are always re-checked)
  - idempotent: a (date, pitcher_id, pk) triple is graded exactly once
  - a probable who did not start is kept with started=0 (scratches are data)

Also writes k_summary.json for the board: how many starts are graded, MAE
of the expected K, mean predicted vs actual, calibration of P(over the
book's line) by bucket, and the paper record of the model's best-edge side
at the logged book price — morning prices and lineup-lock prices kept
separate, and split by edge size. Honest numbers, published even when bad.
Never texts.

Usage:
    python k_grade.py            # grade any ungraded final games, last 4 days
    python k_grade.py 2026-08-17 # grade one specific date's log
"""

import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from glob import glob

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from k_model import LOG_COLS, CSV_LINES, board_date
from pitcher_stats import parse_ip

API = "https://statsapi.mlb.com/api/v1"
TRAIN_FN = "k_training_data.csv"
SUMMARY_FN = "k_summary.json"
LOCK_COLS = ["lineup_n", "lineup_k", "f_lineup", "pk_pa", "exp_k"] + \
            [f"p_over_{L}" for L in CSV_LINES] + \
            ["cons_line", "p_over_cons", "fair_over", "fair_under",
             "best_side", "best_book", "best_line", "best_price", "best_edge", "odds_at", "built_at"]
OUT_COLS = LOG_COLS + ["src"] + [f"lock_{c}" for c in LOCK_COLS] + \
           ["started", "k_actual", "bf_actual", "ip_actual", "over_cons",
            "best_result", "lock_over_cons", "lock_best_result", "graded_at"]
LOOKBACK_DAYS = 4
EDGE_BUCKETS = (("0-3", 0.0, 0.03), ("3-6", 0.03, 0.06), ("6-10", 0.06, 0.10), ("10+", 0.10, 9.0))


def final_pks(session, date):
    try:
        j = session.get(f"{API}/schedule", params={"sportId": 1, "date": date,
                        "fields": "dates,games,gamePk,status,detailedState"}, timeout=30).json()
    except Exception:
        return set()
    return {g["gamePk"] for day in j.get("dates", []) for g in day.get("games", [])
            if g.get("status", {}).get("detailedState") == "Final"}


def boxscore_pitching(session, pk):
    """{pitcher_id: (started, so, bf, ip)} for everyone who pitched."""
    j = session.get(f"{API}/game/{pk}/boxscore", timeout=30).json()
    out = {}
    for side in ("away", "home"):
        t = j.get("teams", {}).get(side, {})
        first = (t.get("pitchers") or [None])[0]
        for p in t.get("players", {}).values():
            st = p.get("stats", {}).get("pitching", {})
            if not st or not st.get("battersFaced"):
                continue
            pid = p.get("person", {}).get("id")
            started = int(st.get("gamesStarted", 0) or 0) or int(pid == first)
            out[pid] = (started, int(st.get("strikeOuts", 0) or 0),
                        int(st.get("battersFaced", 0) or 0), parse_ip(st.get("inningsPitched", 0)))
    return out


def graded_keys():
    if not os.path.exists(TRAIN_FN):
        return set()
    with open(TRAIN_FN, encoding="utf-8") as f:
        return {(r["date"], r["pitcher_id"], r["pk"]) for r in csv.DictReader(f)}


def _read(fn):
    if not os.path.exists(fn):
        return []
    with open(fn, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _settle(side, line, price, k):
    """W/L for an over/under at a half-line and American price; '' if unpriced."""
    if not side or line in ("", None) or price in ("", None):
        return ""
    line = float(line)
    won = (k > line) if side == "over" else (k < line)
    return "W" if won else "L"


def grade_date(session, date, done, writer):
    log = _read(f"k_log_{date}.csv")
    lock = {(r["pk"], r["pitcher_id"]): r for r in _read(f"k_lock_{date}.csv")}
    rows = {(r["pk"], r["pitcher_id"]): r for r in log}
    # late-add starters exist only in the lock file
    for key, r in lock.items():
        if key not in rows:
            rows[key] = dict(r, _lock_only=True)
    pending = {pk for (pk, pid) in rows if (date, pid, pk) not in done}
    if not pending:
        return 0, 0
    finals = {str(pk) for pk in final_pks(session, date)}
    todo = pending & finals
    if not todo:
        return 0, 0
    box = {}
    for pk in todo:
        try:
            box[pk] = boxscore_pitching(session, int(pk))
        except Exception as e:
            print(f"  boxscore {pk} failed ({e}) - will retry next run")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n = 0
    for (pk, pid), r in rows.items():
        if pk not in box or (date, pid, pk) in done:
            continue
        started, k, bf, ip = box[pk].get(int(pid), (0, 0, 0, 0.0))
        out = {c: r.get(c, "") for c in LOG_COLS}
        out["src"] = "lock-only" if r.get("_lock_only") else "morning"
        lr = lock.get((pk, pid))
        for c in LOCK_COLS:
            out[f"lock_{c}"] = lr.get(c, "") if lr else ""
        out.update({
            "started": started, "k_actual": k, "bf_actual": bf, "ip_actual": round(ip, 1),
            "over_cons": (int(k > float(r["cons_line"])) if r.get("cons_line") else ""),
            "best_result": _settle(r.get("best_side"), r.get("best_line"), r.get("best_price"), k) if started else "",
            "lock_over_cons": (int(k > float(lr["cons_line"])) if lr and lr.get("cons_line") else ""),
            "lock_best_result": (_settle(lr.get("best_side"), lr.get("best_line"), lr.get("best_price"), k)
                                 if (lr and started) else ""),
            "graded_at": stamp,
        })
        writer.writerow(out)
        n += 1
    return n, len(box)


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
    print(f"k_grade: migrated {TRAIN_FN} to {len(OUT_COLS)}-column schema ({len(rows)} rows)")


# ── board summary ────────────────────────────────────────────────────────

def _payout(price):
    o = float(price)
    return o if o > 0 else 10000.0 / abs(o)


def _ledger(rows, prefix):
    """Paper record of the best-edge side at the logged price, by edge bucket."""
    res_col = f"{prefix}best_result"
    edge_col = f"{prefix}best_edge"
    price_col = f"{prefix}best_price"
    tot = {"w": 0, "l": 0, "pnl": 0.0}
    buckets = {b[0]: {"w": 0, "l": 0, "pnl": 0.0} for b in EDGE_BUCKETS}
    for r in rows:
        res = r.get(res_col)
        if res not in ("W", "L"):
            continue
        try:
            edge, price = float(r[edge_col]), float(r[price_col])
        except (ValueError, TypeError, KeyError):
            continue
        pnl = _payout(price) if res == "W" else -100.0
        tot["w" if res == "W" else "l"] += 1
        tot["pnl"] += pnl
        for name, lo, hi in EDGE_BUCKETS:
            if lo <= edge < hi:
                buckets[name]["w" if res == "W" else "l"] += 1
                buckets[name]["pnl"] += pnl
                break
    n = tot["w"] + tot["l"]
    return {"w": tot["w"], "l": tot["l"], "pnl": round(tot["pnl"]),
            "roi": round(tot["pnl"] / (n * 100) * 100, 1) if n else 0.0,
            "buckets": [{"b": name, "w": v["w"], "l": v["l"], "pnl": round(v["pnl"])} for name, v in buckets.items()]}


def write_summary():
    rows = [r for r in _read(TRAIN_FN) if r.get("started") == "1"]
    if not rows:
        return
    ks = [int(r["k_actual"]) for r in rows]
    exp = [float(r["exp_k"]) for r in rows]
    mae = sum(abs(a - b) for a, b in zip(ks, exp)) / len(rows)
    edges = [0, .2, .3, .4, .5, .6, .7, .8, 1.01]
    calib = []
    priced = [r for r in rows if r.get("cons_line") and r.get("p_over_cons")]
    for lo, hi in zip(edges, edges[1:]):
        sub = [r for r in priced if lo <= float(r["p_over_cons"]) < hi]
        if sub:
            calib.append({"lo": lo, "hi": hi, "n": len(sub),
                          "pred": round(100 * sum(float(r["p_over_cons"]) for r in sub) / len(sub), 1),
                          "actual": round(100 * sum(int(r["over_cons"]) for r in sub) / len(sub), 1)})
    # IDEA BOX 2026-08-19: "average miss ON THE LINE" - how far the actual K
    # total lands from the BOOK'S line, and whether it lands on the model's
    # side. mae says the model predicts totals well; these say how that
    # translates at the line, which is what a bet actually experiences.
    line_mae = (sum(abs(int(r["k_actual"]) - float(r["cons_line"])) for r in priced) / len(priced)
                if priced else None)
    side_margin = None
    if priced:
        # signed distance in the direction of the model's lean at the consensus
        # line: positive = actual landed on the model's side, negative = book's
        margins = []
        for r in priced:
            d = int(r["k_actual"]) - float(r["cons_line"])
            margins.append(d if float(r["p_over_cons"]) >= 0.5 else -d)
        side_margin = sum(margins) / len(margins)
    lock_rows = [r for r in rows if r.get("lock_exp_k")]
    lock_mae = (sum(abs(int(r["k_actual"]) - float(r["lock_exp_k"])) for r in lock_rows) / len(lock_rows)
                if lock_rows else None)
    dates = sorted({r["date"] for r in rows})
    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_starts": len(rows), "n_days": len(dates), "first": dates[0], "last": dates[-1],
        "mae": round(mae, 2), "mean_pred": round(sum(exp) / len(exp), 2), "mean_actual": round(sum(ks) / len(ks), 2),
        "naive_mae": None,
        "n_priced": len(priced),
        "over_rate": round(100 * sum(int(r["over_cons"]) for r in priced) / len(priced), 1) if priced else None,
        "line_mae": round(line_mae, 2) if line_mae is not None else None,
        "side_margin": round(side_margin, 2) if side_margin is not None else None,
        "calib": calib,
        "morning": _ledger(rows, ""),
        "lock": _ledger(rows, "lock_"), "n_lock": len(lock_rows), "lock_mae": round(lock_mae, 2) if lock_mae else None,
    }
    with open(SUMMARY_FN, "w") as f:
        json.dump(out, f, indent=1)
    print(f"{SUMMARY_FN}: {len(rows)} graded starts, MAE {mae:.2f}, morning best-edge "
          f"{out['morning']['w']}-{out['morning']['l']} ({out['morning']['roi']:+.1f}%), "
          f"lock {out['lock']['w']}-{out['lock']['l']}")


def run(dates=None):
    session = requests.Session()
    if dates is None:
        today = board_date()
        dates = [(datetime.strptime(today, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d")
                 for i in range(LOOKBACK_DAYS)]
    migrate_schema()
    done = graded_keys()
    new_file = not os.path.exists(TRAIN_FN)
    total = 0
    with open(TRAIN_FN, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        if new_file:
            w.writeheader()
        for d in dates:
            n, pks = grade_date(session, d, done, w)
            if n:
                print(f"{d}: graded {n} starter rows across {pks} final games")
            total += n
    if total:
        print(f"{TRAIN_FN}: +{total} rows")
    else:
        print("k_grade: nothing new to grade")
    try:
        write_summary()
    except Exception as e:
        print(f"k_grade: summary failed ({e})")


if __name__ == "__main__":
    run([sys.argv[1]] if len(sys.argv) > 1 else None)
