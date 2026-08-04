import requests

RELIABLE_PA = 150


def _best_split(splits):
    """Traded players: prefer the combined split (no 'team' key), else the
    stint with the most plate appearances — never blindly splits[0]."""
    totals = [x for x in splits if "team" not in x]
    if totals:
        return totals[0]
    return max(splits, key=lambda x: int(x.get("stat", {}).get("plateAppearances", 0) or 0))

def fetch_batter_splits(player_id, season, hand):
    """Fetch batter OPS vs specific pitcher hand (L or R)"""
    sit_code = "vl" if hand == "L" else "vr"
    
    def get_ops(stat_type, extra_params={}):
        try:
            params = {"group": "hitting", **extra_params}
            if stat_type == "season":
                params["stats"] = "statSplits"
                params["season"] = season
                params["sitCodes"] = sit_code
            else:
                params["stats"] = "careerStatSplits"
                params["sitCodes"] = sit_code
            
            data = requests.get(
                f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
                params=params
            ).json()
            
            cands = []
            for split in data.get("stats", []):
                for s in split.get("splits", []):
                    stat = s.get("stat", {})
                    if float(stat.get("ops", 0)) > 0:
                        cands.append(s)
            if cands:
                stat = _best_split(cands).get("stat", {})
                return float(stat.get("ops", 0)), int(stat.get("plateAppearances", 0))
            return None, 0
        except:
            return None, 0

    current_ops, current_pa = get_ops("season")
    career_ops, career_pa   = get_ops("career")

    # Fallback to overall OPS if no split data
    if not current_ops and not career_ops:
        try:
            data = requests.get(
                f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
                params={"stats": "season", "season": season, "group": "hitting"}
            ).json()
            splits = data["stats"][0]["splits"]
            if splits:
                s = _best_split(splits)["stat"]
                return float(s.get("ops", 0.720)), 0
        except:
            return 0.720, 0
        return 0.720, 0

    # If no current season split use career
    if not current_ops:
        return career_ops, 0

    # If no career use current
    if not career_ops:
        return current_ops, current_pa

    # Blend current season toward career based on PA
    reliability = min(current_pa / RELIABLE_PA, 1.0)
    blended = (current_ops * reliability) + (career_ops * (1 - reliability))
    return round(blended, 3), current_pa

def get_platoon_lineup_ops(player_list, season, pitcher_hand):
    """Calculate platoon-adjusted lineup OPS vs pitcher hand"""
    ops_scores = []
    for p in player_list:
        pid  = p.get("id")
        if not pid:
            continue
        ops, pa = fetch_batter_splits(pid, season, pitcher_hand)
        if ops and ops > 0:
            ops_scores.append(ops)
    
    if not ops_scores:
        return None
    return round(sum(ops_scores) / len(ops_scores), 3)

def get_basic_lineup_ops(player_list, season):
    """Fallback — basic lineup OPS when pitcher hand unknown"""
    ops_scores = []
    for p in player_list:
        pid = p.get("id")
        if not pid:
            continue
        try:
            data = requests.get(
                f"https://statsapi.mlb.com/api/v1/people/{pid}/stats",
                params={"stats": "season", "season": season, "group": "hitting"}
            ).json()
            splits = data["stats"][0]["splits"]
            if splits:
                ops = float(_best_split(splits)["stat"].get("ops", 0))
                if ops > 0:
                    ops_scores.append(ops)
        except:
            continue
    if not ops_scores:
        return None
    return round(sum(ops_scores) / len(ops_scores), 3)
