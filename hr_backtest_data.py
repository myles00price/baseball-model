"""hr_backtest_data.py — point-in-time dataset for backtesting the HR model.

Pulls Statcast pitch data one day at a time (pybaseball — Model venv ONLY,
never the shared interpreter) and aggregates each day to three compact CSVs:

  hr_bt_batters.csv : batter, date, game_pk, team-side info, pa, hr,
                      pa/hr split by opposing pitcher hand
  hr_bt_pitchers.csv: pitcher, date, bf, hr allowed, hand
  hr_bt_games.csv   : game_pk, date, home/away team, starter ids+hands
                      (starter = pitcher of each half's first PA — actual,
                      not probable; tiny scratch-day approximation)

Cumulative sums over dates < D reproduce "season-to-date as of D" for every
input the live model uses (except arsenal profiles and weather) with zero
future leakage. hr_backtest.py consumes these.

Raw pitch rows are aggregated and discarded per-day, so memory stays flat.
Resume-safe: dates already present in the output are skipped.

Run:
    C:\\Users\\Poons\\Model\\.venv\\Scripts\\python.exe hr_backtest_data.py
    (optional: start_date end_date args)
"""

import os
import sys
from datetime import date, timedelta

import pandas as pd

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

BAT_FN = "hr_bt_batters.csv"
PIT_FN = "hr_bt_pitchers.csv"
GAME_FN = "hr_bt_games.csv"
SEASON_START = "2026-03-25"


def done_dates(fn):
    if not os.path.exists(fn):
        return set()
    return set(pd.read_csv(fn, usecols=["date"])["date"].unique())


def process_day(d, cache={}):
    from pybaseball import statcast
    df = statcast(start_dt=d, end_dt=d)
    if df is None or df.empty:
        return None
    pa = df[df["events"].notna() & (df["events"] != "")].copy()
    if pa.empty:
        return None
    pa["hr"] = (pa["events"] == "home_run").astype(int)
    pa["date"] = d

    # batter side: Top half -> away team bats
    pa["bat_team"] = pa["away_team"].where(pa["inning_topbot"] == "Top", pa["home_team"])

    bat = (pa.groupby(["batter", "date", "game_pk", "bat_team", "home_team"])
             .agg(pa_n=("hr", "size"), hr=("hr", "sum"))
             .reset_index())
    # vs-hand PA/HR needs a two-key aggregation; do it explicitly
    vs = (pa.groupby(["batter", "date", "game_pk", "p_throws"])
            .agg(n=("hr", "size"), h=("hr", "sum")).reset_index())
    vl = vs[vs["p_throws"] == "L"].set_index(["batter", "date", "game_pk"])
    vr = vs[vs["p_throws"] == "R"].set_index(["batter", "date", "game_pk"])
    bat = bat.set_index(["batter", "date", "game_pk"])
    bat["pa_vl"] = vl["n"].reindex(bat.index).fillna(0).astype(int)
    bat["hr_vl"] = vl["h"].reindex(bat.index).fillna(0).astype(int)
    bat["pa_vr"] = vr["n"].reindex(bat.index).fillna(0).astype(int)
    bat["hr_vr"] = vr["h"].reindex(bat.index).fillna(0).astype(int)
    bat = bat.reset_index()

    pit = (pa.groupby(["pitcher", "date"])
             .agg(bf=("hr", "size"), hr_allowed=("hr", "sum"),
                  hand=("p_throws", "first")).reset_index())

    # starters: pitcher of each half-inning's first PA
    games = []
    for pk, g in pa.groupby("game_pk"):
        g = g.sort_values("at_bat_number")
        top = g[g["inning_topbot"] == "Top"]
        bot = g[g["inning_topbot"] == "Bot"]
        games.append({
            "game_pk": pk, "date": d,
            "home_team": g["home_team"].iloc[0], "away_team": g["away_team"].iloc[0],
            "home_sp": int(top["pitcher"].iloc[0]) if len(top) else 0,
            "home_sp_hand": top["p_throws"].iloc[0] if len(top) else "",
            "away_sp": int(bot["pitcher"].iloc[0]) if len(bot) else 0,
            "away_sp_hand": bot["p_throws"].iloc[0] if len(bot) else "",
        })
    return bat, pit, pd.DataFrame(games)


def append(fn, df):
    df.to_csv(fn, mode="a", header=not os.path.exists(fn), index=False)


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else SEASON_START
    end = sys.argv[2] if len(sys.argv) > 2 else \
        (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    have = done_dates(GAME_FN)
    d = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    n_days = 0
    while d <= stop:
        ds = d.strftime("%Y-%m-%d")
        d += timedelta(days=1)
        if ds in have:
            continue
        try:
            out = process_day(ds)
        except Exception as e:
            print(f"{ds}: FAILED ({e}) - continuing")
            continue
        if out is None:
            continue
        bat, pit, games = out
        append(BAT_FN, bat)
        append(PIT_FN, pit)
        append(GAME_FN, games)
        n_days += 1
        print(f"{ds}: {len(games)} games, {len(bat)} batter-rows", flush=True)
    print(f"done: {n_days} new days")


if __name__ == "__main__":
    main()
