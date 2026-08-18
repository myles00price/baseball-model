"""
k_notify.py — text callouts for K WATCH leans (owner decision 2026-08-17).

Sends the shared subscriber topic a short callout for each K WATCH lean once
its game's lineups are confirmed. A "lean" here is exactly what lights up on
the board: model edge >= 3 pts vs the best book AND top-5 edge on the slate.
Labeled K WATCH LEAN, never OFFICIAL PLAY — these are not part of the graded
official record; they are graded on the PROPS LEDGER (paper) instead.

State: notified_k_<date>.json (one text per pitcher per day).
Called from notify_pick.py right after the K refresh; safe standalone:
    py -3.11 .\\k_notify.py [YYYY-MM-DD]
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

NTFY_TOPIC = "poons-mlb-picks-k7d24q"
LEAN_PTS = 0.03
LEAN_MAX = 5
BOOK = {"dk": "DK", "fd": "FD", "mgm": "MGM", "czr": "CZR"}


def lv_today():
    return datetime.now(timezone(timedelta(hours=-7))).strftime("%Y-%m-%d")


def fmt(o):
    o = int(o)
    return f"+{o}" if o > 0 else str(o)


def leans(K):
    """Board rule: edge >= LEAN_PTS, top LEAN_MAX by edge, lineups confirmed."""
    cands = [p for p in K.get("pitchers", []) if p.get("best")
             and p["best"].get("edge", 0) >= LEAN_PTS
             and p.get("lineup_src") == "confirmed"]
    cands.sort(key=lambda p: -p["best"]["edge"])
    return cands[:LEAN_MAX]


def body_for(p):
    b = p["best"]
    side = b["side"].upper()
    vs = "vs" if p.get("home") else "@"
    fair = p.get("fair_over") if b["side"] == "over" else p.get("fair_under")
    lines = [
        f"{p['name']} ({p['team']} {vs} {p['opp']})",
        f"K WATCH LEAN: {side} {b['line']} strikeouts",
        f"Best price: {BOOK.get(b['book'], b['book'].upper())} {fmt(b['price'])}"
        + (f" (model fair {fair})" if fair else ""),
        f"Model: {p['exp_k']:.1f} K expected | {b['p_model']*100:.0f}% to hit {side.lower()} | edge +{b['edge']*100:.1f} pts vs book",
        "Lineups confirmed. Display list lean - not an official play; graded on the board's Props Ledger.",
    ]
    return "\n".join(lines)


def main(date_str=None):
    date_str = date_str or lv_today()
    fn = f"k_watch_{date_str}.json"
    if not os.path.exists(fn):
        print(f"k_notify: no {fn}")
        return 0
    K = json.load(open(fn, encoding="utf-8"))
    state_fn = f"notified_k_{date_str}.json"
    try:
        sent = set(json.load(open(state_fn)))
    except Exception:
        sent = set()
    n = 0
    for p in leans(K):
        key = f"{p['id']}"
        if key in sent:
            continue
        try:
            requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=body_for(p).encode("utf-8"),
                          headers={"Title": f"K WATCH lean: {p['name']} {p['best']['side'].upper()} {p['best']['line']}",
                                   "Priority": "default", "Tags": "baseball"}, timeout=15)
            sent.add(key); n += 1
            print(f"k_notify: sent {p['name']} {p['best']['side']} {p['best']['line']}")
        except Exception as e:
            print(f"k_notify: send failed for {p['name']}: {e}")
    json.dump(sorted(sent), open(state_fn, "w"))
    return n


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
