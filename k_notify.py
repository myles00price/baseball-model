"""
k_notify.py — K WATCH plays: same lifecycle as main plays (owner decision
2026-08-17).

  overnight / morning : EARLY LEANS - probable starters with posted K lines
                        whose model edge is >= 3 pts vs the best book, top-5
                        on the slate (the exact rows that light on the board)
  lineup lock         : 🔒 K PLAY text, once per pitcher per day, when BOTH
                        lineups in his game are confirmed and he is still a lean
  settle              : settle_notify texts 💰 CASHED / ✗ LOST off the boxscore

K plays are graded on THE PROPS LEDGER (paper, public), separate from the
main official record - the text says so.

State: notified_k_<date>.json (pitcher ids texted at lock).
    py -3.11 .\\k_notify.py [YYYY-MM-DD]      # lock texts for the date
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


def load_watch(date_str):
    fn = f"k_watch_{date_str}.json"
    if not os.path.exists(fn):
        return None
    try:
        return json.load(open(fn, encoding="utf-8"))
    except Exception:
        return None


def leans(K, confirmed_only=False):
    """Board rule: posted line, edge >= LEAN_PTS, top LEAN_MAX by edge.
    confirmed_only: restrict to starters whose game lineups are confirmed."""
    cands = [p for p in K.get("pitchers", []) if p.get("best")
             and p["best"].get("edge", 0) >= LEAN_PTS
             and p.get("cons_line") is not None]
    cands.sort(key=lambda p: -p["best"]["edge"])
    top = cands[:LEAN_MAX]
    if confirmed_only:
        top = [p for p in top if p.get("lineup_src") == "confirmed"]
    return top


def lean_lines(date_str):
    """Short early-lean bullets for the nightly / morning texts."""
    K = load_watch(date_str)
    if not K:
        return []
    out = []
    for p in leans(K):
        b = p["best"]
        vs = "vs" if p.get("home") else "@"
        out.append(f"{p['name']} ({p['team']} {vs} {p['opp']}) {b['side'].upper()} {b['line']} K"
                   f" - {BOOK.get(b['book'], b['book'].upper())} {fmt(b['price'])}, edge +{b['edge']*100:.1f} pts")
    return out


def body_for(p):
    b = p["best"]
    side = b["side"].upper()
    vs = "vs" if p.get("home") else "@"
    fair = p.get("fair_over") if b["side"] == "over" else p.get("fair_under")
    return "\n".join([
        f"{p['name']} ({p['team']} {vs} {p['opp']})",
        f"** K PLAY: {side} {b['line']} strikeouts **",
        f"Best price: {BOOK.get(b['book'], b['book'].upper())} {fmt(b['price'])}"
        + (f" (model fair {fair})" if fair else ""),
        f"Model: {p['exp_k']:.1f} K expected | {b['p_model']*100:.0f}% {side.lower()} | edge +{b['edge']*100:.1f} pts vs book",
        "Lineups confirmed. Graded on the board's Props Ledger (separate from the main record).",
    ])


def both_lineups_pks(date_str):
    """gamePks where BOTH lineups are posted (owner rule 2026-08-19: a K PLAY
    locks only when the pitcher's own lineup is in too - the model's
    'confirmed' already means the OPPOSING lineup he faces; his own team's
    posting confirms the game is set and he is actually taking the ball)."""
    try:
        j = requests.get("https://statsapi.mlb.com/api/v1/schedule",
                         params={"sportId": 1, "date": date_str, "hydrate": "lineups"},
                         timeout=20).json()
    except Exception:
        return set()
    out = set()
    for dd in j.get("dates", []):
        for g in dd.get("games", []):
            lu = g.get("lineups", {})
            if lu.get("homePlayers") and lu.get("awayPlayers"):
                out.add(g["gamePk"])
    return out


def main(date_str=None):
    """Lock texts: each top lean whose game has BOTH lineups confirmed, once."""
    date_str = date_str or lv_today()
    K = load_watch(date_str)
    if not K:
        print(f"k_notify: no k_watch_{date_str}.json")
        return 0
    both = both_lineups_pks(date_str)
    state_fn = f"notified_k_{date_str}.json"
    try:
        sent = set(json.load(open(state_fn)))
    except Exception:
        sent = set()
    n = 0
    for p in leans(K, confirmed_only=True):
        key = str(p["id"])
        if key in sent:
            continue
        if p.get("pk") not in both:
            print(f"k_notify: {p['name']} waiting - opposing lineup in, own lineup not yet posted")
            continue
        try:
            requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=body_for(p).encode("utf-8"),
                          headers={"Title": f"K PLAY locked: {p['name']} {p['best']['side'].upper()} {p['best']['line']}",
                                   "Priority": "high", "Tags": "baseball,moneybag"}, timeout=15)
            sent.add(key); n += 1
            print(f"k_notify: K PLAY {p['name']} {p['best']['side']} {p['best']['line']}")
        except Exception as e:
            print(f"k_notify: send failed for {p['name']}: {e}")
    json.dump(sorted(sent), open(state_fn, "w"))
    return n


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
