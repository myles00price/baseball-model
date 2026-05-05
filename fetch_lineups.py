import requests
from datetime import datetime, timedelta, timezone

def get_batter_stats(player_id, season):
    try:
        data = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
            params={"stats": "season", "season": season, "group": "hitting"}
        ).json()
        splits = data["stats"][0]["splits"]
        if not splits:
            return None
        s = splits[0]["stat"]
        ops = float(s.get("ops", 0))
        avg = float(s.get("avg", 0))
        hr  = int(s.get("homeRuns", 0))
        return {"ops": ops, "avg": avg, "hr": hr}
    except:
        return None

def get_lineup_strength(player_list, season):
    ops_scores = []
    for p in player_list:
        pid  = p.get("id")
        stats = get_batter_stats(pid, season)
        if stats and stats["ops"] > 0:
            ops_scores.append(stats["ops"])
    if not ops_scores:
        return None
    return round(sum(ops_scores) / len(ops_scores), 3)

def get_todays_lineups(date_str, season):
    data = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={"sportId": 1, "date": date_str, "hydrate": "lineups"}
    ).json()

    lineups = {}
    for d in data.get("dates", []):
        for g in d.get("games", []):
            home = g["teams"]["home"]["team"]["name"]
            away = g["teams"]["away"]["team"]["name"]
            lineup_data = g.get("lineups", {})
            home_players = lineup_data.get("homePlayers", [])
            away_players = lineup_data.get("awayPlayers", [])

            if not home_players and not away_players:
                continue

            print(f"  Pulling lineup stats: {away} @ {home}...")
            home_ops = get_lineup_strength(home_players, season)
            away_ops = get_lineup_strength(away_players, season)

            lineups[home] = {"lineup_ops": home_ops}
            lineups[away] = {"lineup_ops": away_ops}

    return lineups

if __name__ == "__main__":
    lv = timezone(timedelta(hours=-7))
    today = datetime.now(lv)
    today_str = today.strftime("%Y-%m-%d")
    season = today.year

    print(f"Fetching lineup strength for {today_str}...\n")
    lineups = get_todays_lineups(today_str, season)

    print(f"\n=== Lineup Strength (OPS based) ===\n")
    for team, data in lineups.items():
        ops = data["lineup_ops"]
        bar = "█" * int((ops or 0) * 20)
        print(f"  {team:<30} OPS: {ops or 'N/A'} {bar}")