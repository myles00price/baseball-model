import requests
import json
import os
from datetime import datetime, timedelta, timezone

LINES_FILE = "saved_lines.json"

def save_current_lines(date_str):
    """Save current lines as opening lines for a given date"""
    data = requests.get(
        "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/",
        params={
            "apiKey": "719921510f0839e3f61743f271956eea",
            "regions": "us",
            "markets": "h2h",
            "oddsFormat": "american",
            "bookmakers": "draftkings,betmgm",
            "dateFormat": "iso"
        }
    ).json()

    lines = {}
    lv = timezone(timedelta(hours=-7))

    for game in data:
        # Only save lines for the target date
        commence = datetime.fromisoformat(
            game["commence_time"].replace("Z", "+00:00")
        ).astimezone(lv)
        if commence.strftime("%Y-%m-%d") != date_str:
            continue

        home = game["home_team"]
        away = game["away_team"]
        key = f"{away}@{home}"

        lines[key] = {
            "home": home,
            "away": away,
            "saved_at": datetime.now(lv).isoformat(),
            "odds": {}
        }

        for bk in game["bookmakers"]:
            for market in bk["markets"]:
                if market["key"] == "h2h":
                    for outcome in market["outcomes"]:
                        team = outcome["name"]
                        if team not in lines[key]["odds"]:
                            lines[key]["odds"][team] = {}
                        lines[key]["odds"][team][bk["key"]] = outcome["price"]

    # Load existing saved lines
    all_lines = {}
    if os.path.exists(LINES_FILE):
        with open(LINES_FILE, "r") as f:
            all_lines = json.load(f)

    # Add new lines — don't overwrite if already saved for this date
    for key, val in lines.items():
        if key not in all_lines:
            all_lines[key] = val
            print(f"  Saved opening line: {key}")

    with open(LINES_FILE, "w") as f:
        json.dump(all_lines, f, indent=2)

    print(f"Opening lines saved for {len(lines)} games on {date_str}")
    return lines

def get_line_movement(date_str):
    """Compare saved opening lines to current lines"""
    if not os.path.exists(LINES_FILE):
        return {}

    with open(LINES_FILE, "r") as f:
        saved = json.load(f)

    # Get current lines
    data = requests.get(
        "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/",
        params={
            "apiKey": "719921510f0839e3f61743f271956eea",
            "regions": "us",
            "markets": "h2h",
            "oddsFormat": "american",
            "bookmakers": "draftkings,betmgm",
            "dateFormat": "iso"
        }
    ).json()

    lv = timezone(timedelta(hours=-7))
    current = {}
    for game in data:
        commence = datetime.fromisoformat(
            game["commence_time"].replace("Z", "+00:00")
        ).astimezone(lv)
        if commence.strftime("%Y-%m-%d") != date_str:
            continue
        home = game["home_team"]
        away = game["away_team"]
        key = f"{away}@{home}"
        current[key] = {}
        for bk in game["bookmakers"]:
            for market in bk["markets"]:
                if market["key"] == "h2h":
                    for outcome in market["outcomes"]:
                        team = outcome["name"]
                        if team not in current[key]:
                            current[key][team] = {}
                        current[key][team][bk["key"]] = outcome["price"]

    # Calculate movement
    movement = {}
    for key, cur in current.items():
        if key not in saved:
            continue
        opening = saved[key]["odds"]
        home = saved[key]["home"]
        away = saved[key]["away"]
        movement[key] = {"home": home, "away": away, "teams": {}}

        for team in [home, away]:
            open_dk  = opening.get(team, {}).get("draftkings")
            cur_dk   = cur.get(team, {}).get("draftkings")

            if open_dk and cur_dk:
                # Convert to implied probability
                def to_prob(o):
                    o = float(o)
                    return (-o / (-o + 100) * 100) if o < 0 else (100 / (o + 100) * 100)

                open_prob = to_prob(open_dk)
                cur_prob  = to_prob(cur_dk)
                move      = round(cur_prob - open_prob, 1)

                movement[key]["teams"][team] = {
                    "open_odds":  open_dk,
                    "current_odds": cur_dk,
                    "open_prob":  round(open_prob, 1),
                    "current_prob": round(cur_prob, 1),
                    "movement":   move,
                    "direction":  "SHARP ↑" if move > 2 else "SHARP ↓" if move < -2 else "FLAT →"
                }

    return movement

def display_movement(movement):
    """Print line movement summary"""
    if not movement:
        print("No line movement data available")
        return
    print("\n=== Line Movement Summary ===\n")
    for key, data in movement.items():
        home = data["home"]
        away = data["away"]
        print(f"{away} @ {home}")
        for team, info in data["teams"].items():
            print(f"  {team:<30} {info['open_odds']:>6} → {info['current_odds']:>6} "
                  f"({info['movement']:+.1f}%) {info['direction']}")
        print()

if __name__ == "__main__":
    lv = timezone(timedelta(hours=-7))
    tomorrow = (datetime.now(lv) + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Saving opening lines for {tomorrow}...")
    save_current_lines(tomorrow)