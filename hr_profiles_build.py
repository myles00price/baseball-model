"""hr_profiles_build.py — Statcast pitch-arsenal profiles for the HR model.

Pulls two Baseball Savant leaderboards via pybaseball and caches them as
hr_profiles.json for hr_model.py's arsenal matchup factor:

  - batter performance vs each pitch type (BA/SLG/PA -> per-type ISO,
    the power proxy: where does this hitter do his damage?)
  - pitcher pitch-usage mix (what will he actually throw tonight?)

hr_model.py combines them: expected ISO for batter b vs pitcher p =
sum over pitch types of usage_p(t) x shrunk ISO_b(t), divided by the
batter's own overall ISO -> a tight-capped multiplier.

IMPORTANT: pybaseball is NOT installed in the shared production
interpreter (pythoncore-3.11-64) and must never be — this script runs
under the Model repo's venv:

    C:\\Users\\Poons\\Model\\.venv\\Scripts\\python.exe hr_profiles_build.py

hr_model.py invokes it exactly that way (subprocess) when the cache is
missing or stale; a failed build just means the arsenal factor stays 1.0.
"""

import json
import sys
from datetime import datetime, timezone

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

SEASON = 2026
OUT = "hr_profiles.json"
USAGE_COLS = ("ff", "si", "fc", "sl", "ch", "cu", "fs", "kn", "st", "sv")


def main():
    from pybaseball import (statcast_batter_pitch_arsenal,
                            statcast_pitcher_pitch_arsenal)

    b = statcast_batter_pitch_arsenal(SEASON, minPA=10)
    u = statcast_pitcher_pitch_arsenal(SEASON, minP=100, arsenal_type="n_")

    batters = {}
    for pid, grp in b.groupby("player_id"):
        types = {}
        tot_pa = 0
        iso_pa = 0.0
        for r in grp.itertuples():
            pa = int(r.pa)
            if pa <= 0:
                continue
            iso = max(float(r.slg) - float(r.ba), 0.0)
            types[str(r.pitch_type)] = {"iso": round(iso, 3), "pa": pa}
            tot_pa += pa
            iso_pa += iso * pa
        if tot_pa < 50:
            continue
        batters[str(int(pid))] = {"iso": round(iso_pa / tot_pa, 3), "types": types}

    pitchers = {}
    for r in u.itertuples():
        usage = {}
        for c in USAGE_COLS:
            v = getattr(r, f"n_{c}", None)
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if v == v and v > 0:  # NaN-safe
                usage[c.upper()] = round(v / 100, 3)
        if usage:
            pitchers[str(int(r.pitcher))] = {"usage": usage}

    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": SEASON,
        "batters": batters,
        "pitchers": pitchers,
    }
    with open(OUT, "w") as f:
        json.dump(out, f)
    print(f"{OUT}: {len(batters)} batters, {len(pitchers)} pitchers")


if __name__ == "__main__":
    main()
