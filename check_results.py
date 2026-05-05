import requests
import csv
import os
from datetime import datetime, timedelta, timezone

def get_game_results(date_str):
    """Pull final scores for a given date from MLB API"""
    schedule = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={
            "sportId": 1,
            "date": date_str,
            "hydrate": "linescore"
        }
    ).json()

    results = {}
    for date in schedule.get("dates", []):
        for game in date.get("games", []):
            status = game.get("status", {}).get("abstractGameState")
            if status != "Final":
                continue
            home = game["teams"]["home"]["team"]["name"]
            away = game["teams"]["away"]["team"]["name"]
            home_score = game["teams"]["home"].get("score", 0)
            away_score = game["teams"]["away"].get("score", 0)
            winner = home if home_score > away_score else away
            results[f"{away}@{home}"] = {
                "home": home,
                "away": away,
                "home_score": home_score,
                "away_score": away_score,
                "winner": winner
            }
    return results

def check_picks(date_str):
    filename = f"picks_{date_str}.csv"
    if not os.path.exists(filename):
        print(f"No picks file found for {date_str}")
        return

    print(f"\n=== Results Check for {date_str} ===\n")

    results = get_game_results(date_str)
    if not results:
        print("Games not final yet — check back later!")
        return

    picks = []
    with open(filename, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            picks.append(row)

    total = 0
    correct = 0
    bet_total = 0
    bet_correct = 0

    for pick in picks:
        away = pick["Away"]
        home = pick["Home"]
        key = f"{away}@{home}"
        
        away_prob = pick["Model Away%"]
        home_prob = pick["Model Home%"]
        flag = pick["Flag"]

        if away_prob == "None" or home_prob == "None":
            continue

        # Model's predicted winner
        model_winner = away if float(away_prob) > float(home_prob) else home

        result = results.get(key)
        if not result:
            # Try reversed key
            result = results.get(f"{home}@{away}")
        
        if not result:
            print(f"  {away} @ {home} — No result found yet")
            continue

        actual_winner = result["winner"]
        score = f"{result['away_score']}-{result['home_score']}"
        correct_flag = "✓" if model_winner == actual_winner else "✗"
        
        total += 1
        if model_winner == actual_winner:
            correct += 1

        if flag == "** BET **":
            bet_total += 1
            if model_winner == actual_winner:
                bet_correct += 1

        print(f"  {correct_flag} {away} @ {home}")
        print(f"     Score: {score} | Winner: {actual_winner}")
        print(f"     Model picked: {model_winner} ({away_prob}% vs {home_prob}%)")
        if flag == "** BET **":
            result_str = "WIN" if model_winner == actual_winner else "LOSS"
            print(f"     *** FLAGGED BET — {result_str} ***")
        print()

    print("=" * 50)
    if total > 0:
        print(f"Overall: {correct}/{total} correct ({correct/total*100:.1f}%)")
    if bet_total > 0:
        print(f"Flagged bets: {bet_correct}/{bet_total} correct ({bet_correct/bet_total*100:.1f}%)")
    else:
        print("No flagged bets today")

if __name__ == '__main__':
    # Check yesterday's picks
    las_vegas_offset = timezone(timedelta(hours=-7))
    yesterday = (datetime.now(las_vegas_offset) - timedelta(days=1)).strftime("%Y-%m-%d")
    
    print(f"Checking results for: {yesterday}")
check_picks("2026-05-01")