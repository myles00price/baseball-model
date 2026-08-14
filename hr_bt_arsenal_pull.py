"""hr_bt_arsenal_pull.py — point-in-time arsenal data for the HR backtest.

Second pass over daily Statcast (pybaseball, Model venv ONLY): aggregates
each day to
  hr_bt_bat_arsenal.csv : batter, date, pitch_type, ab, h, tb
                          (PA-ending pitches only -> per-type ISO)
  hr_bt_pit_usage.csv   : pitcher, date, pitch_type, n (ALL pitches)

Cumulating rows with date < D reproduces "profiles as of D" with no
future leakage — the honest version of what hr_profiles_build.py's
season-aggregate leaderboards can't give us. Statcast pitch-type codes
are mapped to the live profile families (KC/CS -> CU, FO -> FS).

Resume-safe. Run:
    C:\\Users\\Poons\\Model\\.venv\\Scripts\\python.exe hr_bt_arsenal_pull.py
"""

import os
import sys
from datetime import date, timedelta

import pandas as pd

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

BAT_FN = "hr_bt_bat_arsenal.csv"
USE_FN = "hr_bt_pit_usage.csv"
SEASON_START = "2026-03-25"

TYPE_MAP = {"KC": "CU", "CS": "CU", "FO": "FS"}
HIT_TB = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
NON_AB = {"walk", "intent_walk", "hit_by_pitch", "sac_fly", "sac_bunt",
          "catcher_interf", "sac_fly_double_play", "sac_bunt_double_play"}


def done_dates(fn):
    if not os.path.exists(fn):
        return set()
    return set(pd.read_csv(fn, usecols=["date"])["date"].unique())


def process_day(d):
    from pybaseball import statcast
    df = statcast(start_dt=d, end_dt=d)
    if df is None or df.empty:
        return None
    df = df[df["pitch_type"].notna()].copy()
    df["pt"] = df["pitch_type"].replace(TYPE_MAP)

    use = (df.groupby(["pitcher", "pt"]).size().reset_index(name="n"))
    use["date"] = d

    pa = df[df["events"].notna() & (df["events"] != "")].copy()
    pa = pa[~pa["events"].isin(NON_AB)]
    pa["h"] = pa["events"].isin(HIT_TB).astype(int)
    pa["tb"] = pa["events"].map(HIT_TB).fillna(0).astype(int)
    bat = (pa.groupby(["batter", "pt"])
             .agg(ab=("h", "size"), h=("h", "sum"), tb=("tb", "sum"))
             .reset_index())
    bat["date"] = d
    return bat, use


def append(fn, df):
    df.to_csv(fn, mode="a", header=not os.path.exists(fn), index=False)


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else SEASON_START
    end = sys.argv[2] if len(sys.argv) > 2 else \
        (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    have = done_dates(USE_FN)
    d = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    while d <= stop:
        ds = d.strftime("%Y-%m-%d")
        d += timedelta(days=1)
        if ds in have:
            continue
        try:
            out = process_day(ds)
        except Exception as e:
            print(f"{ds}: FAILED ({e})")
            continue
        if out is None:
            continue
        bat, use = out
        append(BAT_FN, bat)
        append(USE_FN, use)
        print(f"{ds}: {len(bat)} batter-type rows, {len(use)} usage rows", flush=True)
    print("done")


if __name__ == "__main__":
    main()
