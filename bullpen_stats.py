import requests
from datetime import datetime, timedelta

def get_bullpen_stats(season, days=7):
    """Pull bullpen stats for all teams over last N days"""
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Season stats for save/blown save context
    season_data = requests.get(
        "https://statsapi.mlb.com/api/v1/teams/stats",
        params={"season": season, "sportId": 1, "group": "pitching", "stats": "season"}
    ).json()

    # Recent stats for hot/cold bullpen
    recent_data = requests.get(
        "https://statsapi.mlb.com/api/v1/teams/stats",
        params={
            "season": season,
            "sportId": 1,
            "group": "pitching",
            "stats": "byDateRange",
            "startDate": start,
            "endDate": end
        }
    ).json()

    bullpen = {}

    # Build season lookup
    season_lookup = {}
    for team in season_data["stats"][0]["splits"]:
        name = team["team"]["name"]
        s = team["stat"]
        season_lookup[name] = {
            "saves":        int(s.get("saves", 0)),
            "blown_saves":  int(s.get("blownSaves", 0)),
            "holds":        int(s.get("holds", 0)),
            "era_season":   float(s.get("era", 4.50)),
            "whip_season":  float(s.get("whip", 1.30)),
        }

    # Build recent lookup
    for team in recent_data["stats"][0]["splits"]:
        name = team["team"]["name"]
        s = team["stat"]
        season = season_lookup.get(name, {})

        era_recent  = float(s.get("era", 4.50))
        whip_recent = float(s.get("whip", 1.30))
        ip_recent   = float(s.get("inningsPitched", 0))
        saves       = season.get("saves", 0)
        blown       = season.get("blown_saves", 0)

        # Bullpen score — lower is better for opponent
        # Combines recent ERA, WHIP and save conversion rate
        save_pct = saves / max(saves + blown, 1)

        # Weighted bullpen quality score (0-10 scale, lower = better bullpen)
        era_score   = min(era_recent / 4.50, 2.0)  # normalized to league avg
        whip_score  = min(whip_recent / 1.30, 2.0)
        save_score  = 1 - save_pct  # lower save% = worse bullpen

        bullpen_score = round((era_score * 0.5 + whip_score * 0.3 + save_score * 0.2), 3)

        bullpen[name] = {
            "era_recent":    round(era_recent, 2),
            "whip_recent":   round(whip_recent, 2),
            "ip_recent":     round(ip_recent, 1),
            "era_season":    season.get("era_season", 4.50),
            "saves":         saves,
            "blown_saves":   blown,
            "save_pct":      round(save_pct * 100, 1),
            "bullpen_score": bullpen_score  # lower = better bullpen
        }

    return bullpen

def bullpen_display(name, stats):
    """Format bullpen info for display"""
    if not stats:
        return "N/A"
    return (f"ERA(7d): {stats['era_recent']} | "
            f"WHIP(7d): {stats['whip_recent']} | "
            f"Sv/BSv: {stats['saves']}/{stats['blown_saves']} | "
            f"Score: {stats['bullpen_score']}")

if __name__ == "__main__":
    print("Pulling bullpen stats...")
    stats = get_bullpen_stats(2026)
    
    # Sort by bullpen score (best to worst)
    sorted_teams = sorted(stats.items(), key=lambda x: x[1]["bullpen_score"])
    
    print("\n=== Bullpen Rankings (Best to Worst) ===\n")
    for i, (team, s) in enumerate(sorted_teams, 1):
        print(f"  {i:>2}. {team:<30} ERA(7d): {s['era_recent']:>5} | "
              f"WHIP: {s['whip_recent']:>5} | "
              f"Sv/BSv: {s['saves']}/{s['blown_saves']} | "
              f"Score: {s['bullpen_score']}")
              