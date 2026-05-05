import requests
from datetime import datetime, timedelta, timezone

ODDS_API_KEY = "719921510f0839e3f61743f271956eea"

url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/"

params = {
    "apiKey": ODDS_API_KEY,
    "regions": "us",
    "markets": "h2h",
    "oddsFormat": "american"
}

response = requests.get(url, params=params)
games = response.json()

# Get tomorrow's date in Las Vegas time (UTC-7)
las_vegas_offset = timezone(timedelta(hours=-7))
tomorrow = (datetime.now(las_vegas_offset) + timedelta(days=1)).date()

print(f"\n=== MLB Games for {tomorrow.strftime('%A %B %d, %Y')} ===\n")

found = 0
for game in games:
    game_time_utc = datetime.strptime(game["commence_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    game_time_lv = game_time_utc.astimezone(las_vegas_offset)

    if game_time_lv.date() == tomorrow:
        found += 1
        home = game["home_team"]
        away = game["away_team"]
        time_str = game_time_lv.strftime("%I:%M %p LV Time")

        print(f"{away} @ {home}  |  {time_str}")
        for bookmaker in game["bookmakers"][:1]:
            for market in bookmaker["markets"]:
                if market["key"] == "h2h":
                    for outcome in market["outcomes"]:
                        print(f"  {outcome['name']}: {outcome['price']}")
        print()

if found == 0:
    print("No games found for tomorrow yet — lines may not be posted.")