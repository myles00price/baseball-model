import subprocess
import requests
import csv
import os
import json
from datetime import datetime, timedelta, timezone

def get_lv_today():
    lv = timezone(timedelta(hours=-7))
    return datetime.now(lv).strftime("%Y-%m-%d")

def count_confirmed_lineups(date_str):
    try:
        data = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": date_str, "hydrate": "lineups"},
            timeout=10
        ).json()
        confirmed = 0
        for d in data.get("dates", []):
            for g in d.get("games", []):
                lineups = g.get("lineups", {})
                if lineups.get("homePlayers") or lineups.get("awayPlayers"):
                    confirmed += 1
        return confirmed
    except:
        return 0

def get_current_probables(date_str):
    """Pull current probable pitchers from MLB API"""
    try:
        data = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": date_str, "hydrate": "probablePitcher"},
            timeout=10
        ).json()
        probables = {}
        for d in data.get("dates", []):
            for g in d.get("games", []):
                home = g["teams"]["home"]["team"]["name"]
                away = g["teams"]["away"]["team"]["name"]
                home_p = g["teams"]["home"].get("probablePitcher", {}).get("fullName", "TBD")
                away_p = g["teams"]["away"].get("probablePitcher", {}).get("fullName", "TBD")
                probables[home] = home_p
                probables[away] = away_p
        return probables
    except:
        return {}

def get_saved_probables(date_str):
    """Read pitchers from the picks CSV saved by master.py"""
    filename = f"picks_{date_str}.csv"
    if not os.path.exists(filename):
        return {}
    saved = {}
    try:
        with open(filename, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                away = row.get("Away", "")
                home = row.get("Home", "")
                away_sp = row.get("Away SP", "TBD")
                home_sp = row.get("Home SP", "TBD")
                if away: saved[away] = away_sp
                if home: saved[home] = home_sp
    except:
        pass
    return saved

def check_pitcher_scratches(date_str):
    """Compare current probables vs what was saved in picks CSV"""
    current = get_current_probables(date_str)
    saved = get_saved_probables(date_str)
    scratches = []
    for team, current_pitcher in current.items():
        saved_pitcher = saved.get(team, "")
        if not saved_pitcher or saved_pitcher in ("TBD", ""):
            continue
        if current_pitcher in ("TBD", ""):
            continue
        if current_pitcher != saved_pitcher:
            scratches.append({
                "team": team,
                "original": saved_pitcher,
                "current": current_pitcher
            })
    return scratches

def save_scratch_alerts(scratches, date_str):
    """Save scratch alerts to JSON for dashboard to read"""
    filename = f"scratches_{date_str}.json"
    with open(filename, "w") as f:
        json.dump({
            "date": date_str,
            "updated": datetime.now().strftime("%I:%M %p"),
            "scratches": scratches
        }, f, indent=2)
    print(f"Scratch alerts saved to {filename}")

def read_last_confirmed():
    try:
        with open("last_confirmed.txt") as f:
            return int(f.read().strip())
    except:
        return 0

def write_last_confirmed(n):
    with open("last_confirmed.txt", "w") as f:
        f.write(str(n))

def git_push(message="lineup update"):
    subprocess.run(
        f'cd C:\\Users\\Poons\\baseball-model && git add . && git commit -m "{message}" && git push',
        shell=True
    )

if __name__ == "__main__":
    today = get_lv_today()
    print(f"Checking lineups and pitchers for {today}...")

    # ── Check for pitcher scratches
    scratches = check_pitcher_scratches(today)
    if scratches:
        print(f"\n⚠️  PITCHER SCRATCH DETECTED:")
        for s in scratches:
            print(f"  {s['team']}: {s['original']} → {s['current']}")
        save_scratch_alerts(scratches, today)
        git_push("pitcher scratch alert")
    else:
        print("No pitcher scratches detected.")

    # ── Check for new lineups
    current = count_confirmed_lineups(today)
    last = read_last_confirmed()

    if current > last:
        print(f"\nNew lineups confirmed: {current} (was {last}) — running master.py and pushing")
        subprocess.run(["py", "-3.11", "C:\\Users\\Poons\\baseball-model\\master.py"])
        git_push("lineup update")
        write_last_confirmed(current)
    else:
        print(f"No new lineups ({current} confirmed) — skipping push")