"""
settle_notify.py — texts subscribers the moment an OFFICIAL PLAY settles.

Official play = flagged row whose game key is in notified_<date>.json (it was
texted at lineup lock). When its game is Final:
    💰 CASHED · Cardinals -116 · final 2-1 · today 2-0
    ✗ LOST   · Marlins +224 · final 5-6 · today 2-1
Wins and losses both go out (the record is public either way); one text per
play per day (state: notified_settle_<date>.json). Doubleheader-safe via
check_results.result_for_row.

Runs: SettleWatch task every 15 min 4-11:45 PM (only fires when the machine
is on), from notify_pick after each watcher cycle (day games), and as a
catch-up at the top of the 10:30 PM grade.
    py -3.11 .\\settle_notify.py [YYYY-MM-DD]
"""

import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from features_v2 import flagged_side, key_from_row
from check_results import get_game_results, result_for_row

NTFY_TOPIC = "poons-mlb-picks-k7d24q"


def lv_today():
    return datetime.now(timezone(timedelta(hours=-7))).strftime("%Y-%m-%d")


def fmt(o):
    try:
        o = int(float(o))
    except (TypeError, ValueError):
        return str(o)
    return f"+{o}" if o > 0 else str(o)


def payout(o):
    o = float(o)
    return o if o > 0 else 10000.0 / abs(o)


def settle_k(date_str):
    """K PLAYS (texted at lock, ids in notified_k_<date>.json): when the game
    is Final, text 💰 CASHED / ✗ LOST off the boxscore K total. Once each."""
    try:
        ids = set(json.load(open(f"notified_k_{date_str}.json")))
    except Exception:
        return 0
    if not ids:
        return 0
    try:
        K = json.load(open(f"k_watch_{date_str}.json", encoding="utf-8"))
    except Exception:
        return 0
    state_fn = f"notified_ksettle_{date_str}.json"
    try:
        done = set(json.load(open(state_fn)))
    except Exception:
        done = set()
    plays = [p for p in K.get("pitchers", []) if str(p.get("id")) in ids and p.get("best")]
    if not plays:
        return 0
    try:
        sched = requests.get("https://statsapi.mlb.com/api/v1/schedule",
                             params={"sportId": 1, "date": date_str}, timeout=30).json()
    except Exception:
        return 0
    final_pks = {g["gamePk"] for dd in sched.get("dates", []) for g in dd.get("games", [])
                 if g.get("status", {}).get("abstractGameState") == "Final"}
    n = 0
    for p in plays:
        key = str(p["id"])
        if key in done or p.get("pk") not in final_pks:
            continue
        try:
            box = requests.get(f"https://statsapi.mlb.com/api/v1/game/{p['pk']}/boxscore", timeout=30).json()
        except Exception:
            continue
        so = None
        for side in ("away", "home"):
            st = box.get("teams", {}).get(side, {}).get("players", {}).get(f"ID{p['id']}", {}).get("stats", {}).get("pitching")
            if st and st.get("battersFaced") is not None:
                so = int(st.get("strikeOuts", 0) or 0)
        if so is None:
            # texted play, game final, pitcher never appeared -> no action (line voids)
            done.add(key)
            continue
        b = p["best"]
        won = so > b["line"] if b["side"] == "over" else so < b["line"]
        head = "💰 CASHED" if won else "✗ LOST"
        body = (f"{head} · K PLAY {p['name']} {b['side'].upper()} {b['line']} · finished with {so} K\n"
                f"Graded on the board's Props Ledger.")
        try:
            requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode("utf-8"),
                          headers={"Title": f"K PLAY {'cashed' if won else 'lost'}: {p['name']}",
                                   "Priority": "high" if won else "default",
                                   "Tags": "baseball" + (",moneybag" if won else "")}, timeout=15)
            done.add(key); n += 1
            print(f"settle K: {head} {p['name']} {b['side']} {b['line']} -> {so} K")
        except Exception as e:
            print(f"settle K: send failed for {p['name']}: {e}")
    json.dump(sorted(done), open(state_fn, "w"))
    return n


def main(date_str=None):
    date_str = date_str or lv_today()
    # settle_k() disabled 2026-08-19 with the K PLAY pull (display-only again)
    try:  # K closing-line capture for CLV (evening games, SettleWatch cycles)
        import k_close
        k_close.capture(date_str)
    except Exception as e:
        print(f"k_close failed: {e}")
    fn = f"picks_{date_str}.csv"
    if not os.path.exists(fn):
        return 0
    try:
        texted = {k for k in json.load(open(f"notified_{date_str}.json")) if not k.startswith("_")}
    except Exception:
        texted = set()
    if not texted:
        return 0
    state_fn = f"notified_settle_{date_str}.json"
    try:
        done = set(json.load(open(state_fn)))
    except Exception:
        done = set()
    rows = list(csv.DictReader(open(fn, encoding="utf-8-sig")))
    plays = [r for r in rows if "BET" in str(r.get("Flag", "")) and key_from_row(r) in texted]
    if not plays:
        return 0
    try:
        R = get_game_results(date_str)
    except Exception as e:
        print(f"settle: results unavailable ({e})")
        return 0
    # settle every play first (for the running day tally), then text new ones
    settled = []
    for r in plays:
        s = flagged_side(r)
        if not s:
            continue
        res = result_for_row(R, r)
        if not res:
            continue
        team = r["Away"] if s == "away" else r["Home"]
        odds = r["DK Away Odds"] if s == "away" else r["DK Home Odds"]
        won = team == res["winner"]
        settled.append((key_from_row(r), team, odds, won,
                        f"{res['away_score']}-{res['home_score']}"))
    if not settled:
        return 0
    n = 0
    for key, team, odds, won, score in settled:
        if key in done:
            continue
        w = sum(1 for x in settled if x[3]); l = len(settled) - w
        pnl = sum(payout(x[2]) if x[3] else -100.0 for x in settled)
        head = "💰 CASHED" if won else "✗ LOST"
        body = (f"{head} · {team} {fmt(odds)} · final {score}\n"
                f"Today: {w}-{l} ({pnl:+.0f} at $100 flat)")
        try:
            requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode("utf-8"),
                          headers={"Title": f"MLB play {'cashed' if won else 'lost'}: {team}",
                                   "Priority": "high" if won else "default",
                                   "Tags": "baseball" + (",moneybag" if won else "")}, timeout=15)
            done.add(key); n += 1
            print(f"settle: {head} {team} {fmt(odds)} {score}")
        except Exception as e:
            print(f"settle: send failed for {team}: {e}")
    json.dump(sorted(done), open(state_fn, "w"))
    return n


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
