"""hit_backtest_data.py — point-in-time dataset for backtesting the hit model.

Pulls every final regular-season boxscore of the season from the free MLB
Stats API (no pybaseball needed) and flattens it to three compact CSVs:

  hit_bt_batters.csv : batter, date, game_pk, team, home_team, slot,
                       pa, ab, h, hr, bb, so, hbp
  hit_bt_pitchers.csv: pitcher, date, game_pk, team, is_starter, bf, ab,
                       h_allowed, hr_allowed, so, hand
  hit_bt_games.csv   : game_pk, date, home/away team, actual starters + hands

Cumulative sums over dates < D reproduce "season-to-date as of D" for every
input the live hit model uses, with zero future leakage. hit_backtest.py
consumes these.

Resume-safe: game_pks already present in hit_bt_games.csv are skipped.

Run:
    C:\\Users\\Poons\\Model\\.venv\\Scripts\\python.exe hit_backtest_data.py
    (optional: start_date end_date args)
"""

import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

API = "https://statsapi.mlb.com/api/v1"
SEASON = 2026
SEASON_START = "2026-03-25"
BAT_FN = "hit_bt_batters.csv"
PIT_FN = "hit_bt_pitchers.csv"
GAME_FN = "hit_bt_games.csv"
BAT_COLS = ["batter", "name", "date", "game_pk", "team", "home_team", "is_home",
            "slot", "pa", "ab", "h", "hr", "bb", "so", "hbp"]
PIT_COLS = ["pitcher", "name", "date", "game_pk", "team", "is_starter", "bf",
            "ab", "h_allowed", "hr_allowed", "so", "hand"]
GAME_COLS = ["game_pk", "date", "home_team", "away_team", "home_sp",
             "home_sp_hand", "away_sp", "away_sp_hand"]


def done_pks():
    if not os.path.exists(GAME_FN):
        return set()
    with open(GAME_FN, encoding="utf-8") as f:
        return {int(r["game_pk"]) for r in csv.DictReader(f)}


def schedule(session, start, end):
    j = session.get(f"{API}/schedule", params={
        "sportId": 1, "gameTypes": "R", "startDate": start, "endDate": end,
    }, timeout=60).json()
    out = []
    for day in j.get("dates", []):
        for g in day.get("games", []):
            if g.get("status", {}).get("codedGameState") != "F":
                continue
            out.append((g["gamePk"], day["date"]))
    return out


def pitcher_hands(session, ids):
    hands = {}
    ids = [str(i) for i in ids]
    for i in range(0, len(ids), 50):
        j = session.get(f"{API}/people", params={"personIds": ",".join(ids[i:i + 50])},
                        timeout=30).json()
        for p in j.get("people", []):
            hands[p["id"]] = p.get("pitchHand", {}).get("code", "")
    return hands


def process_game(session, pk, d):
    j = session.get(f"{API}/game/{pk}/boxscore", timeout=30).json()
    teams = j["teams"]
    home_abbr = teams["home"]["team"]["abbreviation"]
    away_abbr = teams["away"]["team"]["abbreviation"]
    bats, pits = [], []
    game = {"game_pk": pk, "date": d, "home_team": home_abbr, "away_team": away_abbr,
            "home_sp": 0, "home_sp_hand": "", "away_sp": 0, "away_sp_hand": ""}
    for side in ("home", "away"):
        t = teams[side]
        abbr = t["team"]["abbreviation"]
        for pid in t.get("batters", []):
            p = t["players"].get(f"ID{pid}", {})
            st = p.get("stats", {}).get("batting", {})
            pa = int(st.get("plateAppearances", 0) or 0)
            if pa == 0:
                continue
            bo = p.get("battingOrder")
            slot = int(bo) // 100 if bo else 0
            bats.append({
                "batter": pid, "name": p.get("person", {}).get("fullName", ""),
                "date": d, "game_pk": pk, "team": abbr, "home_team": home_abbr,
                "is_home": int(side == "home"), "slot": slot,
                "pa": pa, "ab": int(st.get("atBats", 0) or 0),
                "h": int(st.get("hits", 0) or 0), "hr": int(st.get("homeRuns", 0) or 0),
                "bb": int(st.get("baseOnBalls", 0) or 0), "so": int(st.get("strikeOuts", 0) or 0),
                "hbp": int(st.get("hitByPitch", 0) or 0),
            })
        for i, pid in enumerate(t.get("pitchers", [])):
            p = t["players"].get(f"ID{pid}", {})
            st = p.get("stats", {}).get("pitching", {})
            bf = int(st.get("battersFaced", 0) or 0)
            if i == 0:
                game[f"{side}_sp"] = pid
            pits.append({
                "pitcher": pid, "name": p.get("person", {}).get("fullName", ""),
                "date": d, "game_pk": pk, "team": abbr, "is_starter": int(i == 0),
                "bf": bf, "ab": int(st.get("atBats", 0) or 0),
                "h_allowed": int(st.get("hits", 0) or 0),
                "hr_allowed": int(st.get("homeRuns", 0) or 0),
                "so": int(st.get("strikeOuts", 0) or 0), "hand": "",
            })
    return bats, pits, game


def append(fn, cols, rows):
    new = not os.path.exists(fn)
    with open(fn, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if new:
            w.writeheader()
        w.writerows(rows)


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else SEASON_START
    end = sys.argv[2] if len(sys.argv) > 2 else \
        (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    session = requests.Session()
    have = done_pks()
    todo = [(pk, d) for pk, d in schedule(session, start, end) if pk not in have]
    print(f"{len(todo)} final games to pull ({start}..{end}), {len(have)} already done")
    if not todo:
        return

    def work(item):
        pk, d = item
        for attempt in range(3):
            try:
                return process_game(session, pk, d)
            except Exception as e:
                err = e
        print(f"game {pk} FAILED ({err})")
        return None

    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, r in enumerate(ex.map(work, todo), 1):
            if r:
                results.append(r)
            if i % 100 == 0:
                print(f"  {i}/{len(todo)}", flush=True)

    # throwing hands for every pitcher seen (one pass, chunked)
    pids = {p["pitcher"] for _, pits, _ in results for p in pits}
    hands = pitcher_hands(session, sorted(pids))
    bat_rows, pit_rows, game_rows = [], [], []
    for bats, pits, game in results:
        for p in pits:
            p["hand"] = hands.get(p["pitcher"], "")
        game["home_sp_hand"] = hands.get(game["home_sp"], "")
        game["away_sp_hand"] = hands.get(game["away_sp"], "")
        bat_rows += bats
        pit_rows += pits
        game_rows.append(game)
    # keep files date-ordered for readability
    game_rows.sort(key=lambda g: (g["date"], g["game_pk"]))
    bat_rows.sort(key=lambda b: (b["date"], b["game_pk"]))
    pit_rows.sort(key=lambda p: (p["date"], p["game_pk"]))
    append(BAT_FN, BAT_COLS, bat_rows)
    append(PIT_FN, PIT_COLS, pit_rows)
    append(GAME_FN, GAME_COLS, game_rows)
    print(f"done: {len(game_rows)} games, {len(bat_rows)} batter-games, "
          f"{len(pit_rows)} pitcher-games")


if __name__ == "__main__":
    main()
