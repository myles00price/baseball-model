import requests
from datetime import datetime, timedelta, timezone

lv = timezone(timedelta(hours=-7))
today = datetime.now(lv).strftime("%Y-%m-%d")

data = requests.get(
    "https://statsapi.mlb.com/api/v1/schedule",
    params={"sportId": 1, "date": today, "hydrate": "lineups"}
).json()

for d in data.get("dates", []):
    for g in d.get("games", []):
        home = g["teams"]["home"]["team"]["name"]
        away = g["teams"]["away"]["team"]["name"]
        lineups = g.get("lineups", {})
        home_lineup = lineups.get("homePlayers", [])
        away_lineup = lineups.get("awayPlayers", [])
        if not home_lineup:
            continue
        print(f"\n{away} @ {home}")
        print(f"  Away lineup:")
        for p in away_lineup:
            print(f"    {p.get('fullName')} (id: {p.get('id')})")
        print(f"  Home lineup:")
        for p in home_lineup:
            print(f"    {p.get('fullName')} (id: {p.get('id')})")
            