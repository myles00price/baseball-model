"""hr_miss_audit_pull.py — every home run in a window, with pitch details.

Pulls raw Statcast (pybaseball, Model venv ONLY) for a date range and
keeps only home-run events, one row each: batter, pitcher, date, game_pk,
pitch type/name, release speed, spin, plate location (plate_x, plate_z,
zone 1-14), count, inning, launch speed/angle, distance, batter/pitcher
hands. Written to hr_audit_events.csv for hr_miss_audit.py.

Run:  C:\\Users\\Poons\\Model\\.venv\\Scripts\\python.exe hr_miss_audit_pull.py START END
"""

import os
import sys
from datetime import date, timedelta

import pandas as pd

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

OUT = "hr_audit_events.csv"
KEEP = ["game_date", "game_pk", "batter", "pitcher", "player_name", "stand", "p_throws",
        "pitch_type", "pitch_name", "release_speed", "release_spin_rate",
        "plate_x", "plate_z", "zone", "sz_top", "sz_bot", "balls", "strikes",
        "inning", "inning_topbot", "outs_when_up", "launch_speed", "launch_angle",
        "hit_distance_sc", "home_team", "away_team", "des"]


def main():
    from pybaseball import statcast
    start = sys.argv[1]
    end = sys.argv[2]
    if os.path.exists(OUT):
        os.remove(OUT)
    d = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    n = 0
    while d <= stop:
        ds = d.strftime("%Y-%m-%d")
        d += timedelta(days=1)
        try:
            df = statcast(start_dt=ds, end_dt=ds)
        except Exception as e:
            print(f"{ds}: FAILED {e}")
            continue
        if df is None or df.empty:
            continue
        hr = df[df["events"] == "home_run"]
        cols = [c for c in KEEP if c in hr.columns]
        hr[cols].to_csv(OUT, mode="a", index=False, header=not os.path.exists(OUT))
        n += len(hr)
        print(f"{ds}: {len(hr)} HR", flush=True)
    print(f"done: {n} home runs -> {OUT}")


if __name__ == "__main__":
    main()
