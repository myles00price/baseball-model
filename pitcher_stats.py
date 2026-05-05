import requests

LEAGUE_AVG_ERA = 4.50
LEAGUE_AVG_WHIP = 1.30
LEAGUE_AVG_K9 = 8.5
LEAGUE_AVG_BB9 = 3.2
RELIABLE_IP = 200

def fetch_pitcher_stats(player_id, season):
    try:
        data = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
            params={"stats": "season", "season": season, "group": "pitching"}
        ).json()
        splits = data["stats"][0]["splits"]
        if not splits:
            return None
        s = splits[0]["stat"]
        ip = float(s.get("inningsPitched", 0))
        if ip < 1:
            return None
        return {
            "era":  float(s.get("era", LEAGUE_AVG_ERA)),
            "whip": float(s.get("whip", LEAGUE_AVG_WHIP)),
            "k9":   float(s.get("strikeoutsPer9Inn", LEAGUE_AVG_K9)),
            "bb9":  float(s.get("walksPer9Inn", LEAGUE_AVG_BB9)),
            "ip":   ip
        }
    except:
        return None

def fetch_career_stats(player_id):
    try:
        data = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
            params={"stats": "career", "group": "pitching"}
        ).json()
        splits = data["stats"][0]["splits"]
        if not splits:
            return None
        s = splits[0]["stat"]
        ip = float(s.get("inningsPitched", 0))
        if ip < 1:
            return None
        return {
            "era":  float(s.get("era", LEAGUE_AVG_ERA)),
            "whip": float(s.get("whip", LEAGUE_AVG_WHIP)),
            "k9":   float(s.get("strikeoutsPer9Inn", LEAGUE_AVG_K9)),
            "bb9":  float(s.get("walksPer9Inn", LEAGUE_AVG_BB9)),
            "ip":   ip
        }
    except:
        return None

def fetch_pitcher_handedness(player_id):
    try:
        data = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}"
        ).json()
        hand = data["people"][0]["pitchHand"]["code"]
        return hand  # "L" or "R"
    except:
        return "R"  # default to right

def get_blended_pitcher_stats(full_name, season, playerid_lookup):
    if not full_name or full_name == "TBD":
        return None, None
    try:
        parts = full_name.split()
        first, last = parts[0], parts[-1]
        lookup = playerid_lookup(last, first)
        if lookup.empty:
            return None, None
        pid = int(lookup.iloc[0]['key_mlbam'])

        # Get handedness
        hand = fetch_pitcher_handedness(pid)

        # Get current season stats
        current = fetch_pitcher_stats(pid, season)

        # Get career stats as anchor
        career = fetch_career_stats(pid)

        # If no data at all use league averages
        if not current and not career:
            return {
                "era":  LEAGUE_AVG_ERA,
                "whip": LEAGUE_AVG_WHIP,
                "k9":   LEAGUE_AVG_K9,
                "bb9":  LEAGUE_AVG_BB9,
                "hand": hand
            }, pid

        # If no current season fall back to career
        if not current:
            career["hand"] = hand
            return career, pid

        # If no career use current only
        if not career:
            current["hand"] = hand
            return current, pid

        # Blend: weight current by IP vs reliable threshold
        reliability = min(current["ip"] / RELIABLE_IP, 1.0)
        prior_weight = 1.0 - reliability

        blended = {
            "era":  round(current["era"]  * reliability + career["era"]  * prior_weight, 3),
            "whip": round(current["whip"] * reliability + career["whip"] * prior_weight, 3),
            "k9":   round(current["k9"]   * reliability + career["k9"]   * prior_weight, 3),
            "bb9":  round(current["bb9"]  * reliability + career["bb9"]  * prior_weight, 3),
            "hand": hand,
            "ip":   current["ip"],
            "reliability": round(reliability * 100, 1)
        }
        return blended, pid

    except:
        return None, None