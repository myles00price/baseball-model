import requests

data = requests.get(
    "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/",
    params={
        "apiKey": "719921510f0839e3f61743f271956eea",
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "american",
        "dateFormat": "iso"
    }
).json()

for game in data[:3]:
    print(f"\n{game['away_team']} @ {game['home_team']}")
    print(f"Commence: {game['commence_time']}")
    print(f"Bookmakers: {[bk['key'] for bk in game['bookmakers']]}")
    for bk in game["bookmakers"][:1]:
        for market in bk["markets"]:
            if market["key"] == "h2h":
                print(f"Last update: {market['last_update']}")
                for outcome in market["outcomes"]:
                    print(f"  {outcome['name']}: {outcome['price']}")