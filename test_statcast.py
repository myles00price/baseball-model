from pybaseball import statcast_pitcher, playerid_lookup
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone

if __name__ == '__main__':
    las_vegas_offset = timezone(timedelta(hours=-7))
    tomorrow = (datetime.now(las_vegas_offset) + timedelta(days=1))
    tomorrow_str = tomorrow.strftime("%Y-%m-%d")
    season_start = f"{tomorrow.year}-04-01"

    # Pull tomorrow's schedule
    schedule = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={"sportId": 1, "date": tomorrow_str, "hydrate": "probablePitcher"}
    ).json()

    def get_statcast_stats(last, first):
        try:
            lookup = playerid_lookup(last, first)
            if lookup.empty:
                return None, f"{first} {last} | Not found"
            pid = lookup.iloc[0]['key_mlbam']
            data = statcast_pitcher(season_start, tomorrow_str, player_id=int(pid))
            if data.empty:
                return pid, f"{first} {last} | No data yet"
            velo = data['release_speed'].mean()
            spin = data['release_spin_rate'].mean()
            whiff = (data['description'] == 'swinging_strike').mean() * 100
            pitches = len(data)
            return pid, f"{first} {last} | Velo: {velo:.1f} | Spin: {spin:.0f} | Whiff: {whiff:.1f}% | Pitches: {pitches}"
        except:
            return None, f"{first} {last} | Error"

    print(f"\n=== Tomorrow's Starters — Statcast Stats ===\n")
    for date in schedule.get("dates", []):
        for game in date.get("games", []):
            home = game["teams"]["home"]["team"]["name"]
            away = game["teams"]["away"]["team"]["name"]
            home_p = game["teams"]["home"].get("probablePitcher", {})
            away_p = game["teams"]["away"].get("probablePitcher", {})

            print(f"{away} @ {home}")
            for p in [away_p, home_p]:
                name = p.get("fullName", "TBD")
                if name == "TBD":
                    print(f"  TBD")
                else:
                    parts = name.split()
                    _, stats = get_statcast_stats(parts[-1], parts[0])
                    print(f"  {stats}")
            print()