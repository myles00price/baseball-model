import csv
from glob import glob
from datetime import datetime, timedelta, timezone

def get_game_results(date_str):
    import requests
    try:
        schedule = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": date_str, "hydrate": "linescore"},
            timeout=10
        ).json()
        results = {}
        for date in schedule.get("dates", []):
            for game in date.get("games", []):
                if game.get("status", {}).get("abstractGameState") != "Final":
                    continue
                home = game["teams"]["home"]["team"]["name"]
                away = game["teams"]["away"]["team"]["name"]
                home_score = game["teams"]["home"].get("score", 0)
                away_score = game["teams"]["away"].get("score", 0)
                winner = home if home_score > away_score else away
                results[home] = {"winner": winner}
                results[away] = {"winner": winner}
        return results
    except:
        return {}

zone_bets = zone_wins = 0
pnl = 0.0

for filename in sorted(glob("picks_2026-*.csv")):
    date_str = filename.replace("picks_", "").replace(".csv", "")
    results = get_game_results(date_str)
    try:
        with open(filename, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                flag = row.get("Flag", "")
                if "BET" not in str(flag):
                    continue
                edge = row.get("DK Edge Away", "N/A")
                try:
                    e = abs(float(edge.replace("%","").replace("** BET **","").replace("+","").strip()))
                    if 6 <= e <= 10:
                        away = row.get("Away", "")
                        home = row.get("Home", "")
                        away_prob = float(row.get("Model Away%", 0))
                        home_prob = float(row.get("Model Home%", 0))
                        model_pick = away if away_prob > home_prob else home
                        result = results.get(home) or results.get(away)
                        if not result:
                            continue
                        won = result["winner"] == model_pick
                        zone_bets += 1
                        if won:
                            zone_wins += 1
                            pnl += 100
                        else:
                            pnl -= 100
                        print(f"{date_str} | {away} @ {home} | {'WIN' if won else 'LOSS'} | edge={e:.1f}%")
                except:
                    pass
    except:
        pass

print(f"\nTotal: {zone_wins}/{zone_bets} ({zone_wins/zone_bets*100:.1f}%)")
print(f"P&L (flat $100): ${pnl:+.0f}")