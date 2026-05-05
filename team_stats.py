import requests

def get_team_stats(season):
    print("Pulling team offensive stats from MLB API...")
    
    url = f"https://statsapi.mlb.com/api/v1/teams/stats"
    params = {
        "season": season,
        "sportId": 1,
        "group": "hitting",
        "stats": "season"
    }
    
    data = requests.get(url, params=params).json()
    
    team_stats = {}
    for team in data["stats"][0]["splits"]:
        name = team["team"]["name"]
        s = team["stat"]
        team_stats[name] = {
            "avg":  float(s.get("avg", 0)),
            "ops":  float(s.get("ops", 0)),
            "kpct": round(int(s.get("strikeOuts", 0)) / max(int(s.get("plateAppearances", 1)), 1) * 100, 1),
            "runs": float(s.get("runs", 0))
        }
    
    return team_stats

if __name__ == '__main__':
    stats = get_team_stats(2026)
    for team, s in list(stats.items())[:5]:
        print(f"{team}: AVG: {s['avg']} | OPS: {s['ops']} | K%: {s['kpct']}% | Runs: {s['runs']}")