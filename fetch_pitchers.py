import requests
import pandas as pd
from pybaseball import pitching_stats_bref
from datetime import datetime, timedelta, timezone

las_vegas_offset = timezone(timedelta(hours=-7))
tomorrow = (datetime.now(las_vegas_offset) + timedelta(days=1))
tomorrow_str = tomorrow.strftime("%Y-%m-%d")

print(f"Fetching probable starters for {tomorrow_str}...\n")

mlb_url = "https://statsapi.mlb.com/api/v1/schedule"
params = {
    "sportId": 1,
    "date": tomorrow_str,
    "hydrate": "probablePitcher"
}
response = requests.get(mlb_url, params=params)
schedule = response.json()

print("Pulling pitcher stats from Baseball Reference...")
year = tomorrow.year
br_stats = pitching_stats_bref(year)
br_stats["Name"] = br_stats["Name"].str.strip()

print(f"\n=== Probable Starters & Stats for {tomorrow_str} ===\n")

def get_pitcher_stats(pitcher_name, br_stats):
    if pitcher_name == "TBD":
        return "TBD"
    match = br_stats[br_stats["Name"].str.lower() == pitcher_name.lower()]
    if match.empty:
        last_name = pitcher_name.split()[-1]
        match = br_stats[br_stats["Name"].str.contains(last_name, case=False, na=False)]
    if not match.empty:
        row = match.iloc[0]
        era  = round(row["ERA"], 2) if "ERA" in row else "N/A"
        k9   = round(row["SO9"], 2) if "SO9" in row else "N/A"
        bb9  = round(row["BB9"], 2) if "BB9" in row else "N/A"
        whip = round(row["WHIP"], 2) if "WHIP" in row else "N/A"
        ip   = round(row["IP"], 1) if "IP" in row else "N/A"
        return f"{pitcher_name} | ERA: {era} | K/9: {k9} | BB/9: {bb9} | WHIP: {whip} | IP: {ip}"
    else:
        return f"{pitcher_name} | No stats yet"

for date in schedule.get("dates", []):
    for game in date.get("games", []):
        home = game["teams"]["home"]["team"]["name"]
        away = game["teams"]["away"]["team"]["name"]
        home_pitcher = game["teams"]["home"].get("probablePitcher", {}).get("fullName", "TBD")
        away_pitcher = game["teams"]["away"].get("probablePitcher", {}).get("fullName", "TBD")
        print(f"{away} @ {home}")
        print(f"  Away SP: {get_pitcher_stats(away_pitcher, br_stats)}")
        print(f"  Home SP: {get_pitcher_stats(home_pitcher, br_stats)}")
        print()