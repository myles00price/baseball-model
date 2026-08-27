"""
k_close.py — closing-line capture for K WATCH (CLV, owner request 2026-08-19).

For each game starting within the next ~75 minutes whose closing K prices
haven't been captured, fetches pitcher_strikeouts one final time (1 credit
per game) and stores the snapshot in k_close_{date}.json. k_grade then
scores CLV: the model's lean at its logged lock price vs the same side/line
at close. CLV is the professional's metric - it shows whether the lean was
ahead of the market long before win/loss records stabilize.

Hooked into notify_pick (day cycles) and settle_notify (evening SettleWatch
cycles). Standalone:  py -3.11 .\k_close.py [YYYY-MM-DD]
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

WINDOW_MIN = 75


def lv_today():
    return datetime.now(timezone(timedelta(hours=-7))).strftime("%Y-%m-%d")


def capture(date_str=None):
    date_str = date_str or lv_today()
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        return 0
    fn = f"k_close_{date_str}.json"
    try:
        store = json.load(open(fn, encoding="utf-8"))
    except Exception:
        store = {}
    try:
        from k_model import fetch_schedule  # game list w/ pk + start time
        import requests as rq
        sched = rq.get("https://statsapi.mlb.com/api/v1/schedule",
                       params={"sportId": 1, "date": date_str}, timeout=20).json()
    except Exception:
        return 0
    now = datetime.now(timezone.utc)
    todo = []
    for dd in sched.get("dates", []):
        for g in dd.get("games", []):
            pk = str(g["gamePk"])
            if pk in store:
                continue
            if g.get("status", {}).get("abstractGameState") != "Preview":
                continue
            try:
                start = datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00"))
            except Exception:
                continue
            mins = (start - now).total_seconds() / 60
            if 0 <= mins <= WINDOW_MIN:
                todo.append((pk, g["teams"]["away"]["team"]["name"],
                             g["teams"]["home"]["team"]["name"]))
    if not todo:
        return 0
    # event ids from the odds api events list (free)
    try:
        evs = requests.get("https://api.the-odds-api.com/v4/sports/baseball_mlb/events",
                           params={"apiKey": key}, timeout=20).json()
    except Exception:
        return 0
    from features_v2 import commence_lv_date
    emap = {}
    for e in evs:
        if commence_lv_date(e.get("commence_time")) == date_str:
            emap.setdefault(f"{e['away_team']}@{e['home_team']}", []).append(e)
    n = 0
    for pk, away, home in todo:
        cands = sorted(emap.get(f"{away}@{home}", []), key=lambda e: e["commence_time"])
        if not cands:
            continue
        eid = cands[0]["id"]  # DH: nearest upcoming event is fine at close time
        try:
            r = requests.get(f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{eid}/odds",
                             params={"apiKey": key, "regions": "us",
                                     "markets": "pitcher_strikeouts,h2h",
                                     "oddsFormat": "american",
                                     "bookmakers": "draftkings,fanduel,betmgm,williamhill_us"},
                             timeout=20).json()
        except Exception:
            continue
        snap = {}
        ml = {}
        for bk in r.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk["key"] == "h2h":
                    # ML close for true-CLV (2026-08-27: the 7/29 closing-line fix
                    # silently produced NO closing lines for a month - the API
                    # drops finished games by grade time; capture close here,
                    # pre-pitch, where the game still exists)
                    for o in mk["outcomes"]:
                        ml.setdefault(o["name"], {})[bk["key"]] = o["price"]
                    continue
                if mk["key"] != "pitcher_strikeouts":
                    continue
                for o in mk["outcomes"]:
                    nm = o.get("description", "")
                    snap.setdefault(nm, {}).setdefault(bk["key"], {})[
                        f"{o['name'].lower()}_{o.get('point')}"] = o["price"]
        store[pk] = {"at": datetime.now(timezone.utc).strftime("%H:%MZ"), "prices": snap, "ml": ml, "away": away, "home": home}
        n += 1
    if n:
        json.dump(store, open(fn, "w", encoding="utf-8"), indent=1)
        print(f"k_close: captured closing K prices for {n} game(s)")
    return n


if __name__ == "__main__":
    capture(sys.argv[1] if len(sys.argv) > 1 else None)
