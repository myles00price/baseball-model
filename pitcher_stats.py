import requests

# ─────────────────────────────────────────────────────────────
# pitcher_stats.py — FIP added to the Bayesian blend.
# Same weighted-average pattern as era/whip/k9/bb9. FIP is what
# the model now consumes; era/whip are kept in the output dict
# for any display code that still references them.
#
# Also fixes: IP parsing. MLB stores "182.1" meaning 182 + 1/3
# innings, not 182.1. Matters now because FIP divides by IP.
# ─────────────────────────────────────────────────────────────

LEAGUE_AVG_ERA  = 4.50
LEAGUE_AVG_WHIP = 1.30
LEAGUE_AVG_K9   = 8.5
LEAGUE_AVG_BB9  = 3.2
LEAGUE_AVG_FIP  = 4.20
RELIABLE_IP     = 200

FIP_CONSTANT = 3.10  # must match weekly_retrain.py


def parse_ip(ip_value):
    """MLB stores innings pitched as e.g. '182.1' meaning 182 + 1/3 innings."""
    if ip_value is None:
        return 0.0
    try:
        s = str(ip_value)
        if "." in s:
            whole, frac = s.split(".")
            return float(whole) + (int(frac) / 3.0)
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def compute_fip(hr, bb, k, ip):
    """FIP = (13*HR + 3*BB - 2*K) / IP + 3.10"""
    if ip < 1:
        return LEAGUE_AVG_FIP
    return round((13 * hr + 3 * bb - 2 * k) / ip + FIP_CONSTANT, 3)


def season_total_split(splits):
    """Traded players get one split PER TEAM STINT from the season endpoint.
    Prefer the combined season split (no 'team' key); if the API only gives
    stints, take the largest sample rather than splits[0] (which after a
    trade can be a 3-inning new-team stint)."""
    totals = [x for x in splits if "team" not in x]
    if totals:
        return totals[0]
    return max(splits, key=lambda x: parse_ip(x.get("stat", {}).get("inningsPitched", 0)))


def fetch_pitcher_stats(player_id, season):
    try:
        data = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
            params={"stats": "season", "season": season, "group": "pitching"}
        ).json()
        splits = data["stats"][0]["splits"]
        if not splits:
            return None
        s = season_total_split(splits)["stat"]
        ip = parse_ip(s.get("inningsPitched", 0))
        if ip < 1:
            return None
        hr = int(s.get("homeRuns", 0))
        bb = int(s.get("baseOnBalls", 0))
        k  = int(s.get("strikeOuts", 0))
        return {
            "era":  float(s.get("era", LEAGUE_AVG_ERA)),
            "whip": float(s.get("whip", LEAGUE_AVG_WHIP)),
            "k9":   float(s.get("strikeoutsPer9Inn", LEAGUE_AVG_K9)),
            "bb9":  float(s.get("walksPer9Inn", LEAGUE_AVG_BB9)),
            "fip":  compute_fip(hr, bb, k, ip),
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
        s = season_total_split(splits)["stat"]
        ip = parse_ip(s.get("inningsPitched", 0))
        if ip < 1:
            return None
        hr = int(s.get("homeRuns", 0))
        bb = int(s.get("baseOnBalls", 0))
        k  = int(s.get("strikeOuts", 0))
        return {
            "era":  float(s.get("era", LEAGUE_AVG_ERA)),
            "whip": float(s.get("whip", LEAGUE_AVG_WHIP)),
            "k9":   float(s.get("strikeoutsPer9Inn", LEAGUE_AVG_K9)),
            "bb9":  float(s.get("walksPer9Inn", LEAGUE_AVG_BB9)),
            "fip":  compute_fip(hr, bb, k, ip),
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


def resolve_pid(full_name, playerid_lookup, season=None):
    """MLBAM id for a pitcher name. playerid_lookup can return several
    players with the same name (2026-08-17: 'Luis Castillo' returned a
    1996-2010 infielder first, so the real Castillo showed 0% reliability
    with league-average stats). Prefer the most recently active player,
    then the one active this season."""
    parts = full_name.split()
    first, last = parts[0], parts[-1]
    lookup = playerid_lookup(last, first)
    if lookup.empty:
        return None
    df = lookup.dropna(subset=["key_mlbam"]).copy()
    if df.empty:
        return None
    if "mlb_played_last" in df.columns:
        df["_last"] = df["mlb_played_last"].fillna(0)
        if season is not None and (df["_last"] >= season - 1).any():
            df = df[df["_last"] >= season - 1]
        df = df.sort_values("_last", ascending=False)
    return int(df.iloc[0]["key_mlbam"])


def get_blended_pitcher_stats(full_name, season, playerid_lookup, pid=None):
    """Blended season/career pitcher stats. Pass `pid` (the MLB id from the
    schedule's probablePitcher) to skip the name lookup entirely — that is
    the authoritative path; the name lookup is only a fallback."""
    if not full_name or full_name == "TBD":
        return None, None
    try:
        if pid is None:
            pid = resolve_pid(full_name, playerid_lookup, season)
        if pid is None:
            return None, None
        pid = int(pid)

        # Get handedness
        hand = fetch_pitcher_handedness(pid)

        # Get current season stats
        current = fetch_pitcher_stats(pid, season)

        # Get career stats as anchor
        career = fetch_career_stats(pid)

        # If no data at all use league averages
        if not current and not career:
            # every path must carry "reliability" (audit 2026-08-27: fallback
            # dicts without it read as 0% downstream, so one HTTP hiccup on a
            # veteran silently flipped his reliability gate)
            print(f"  WARNING: no stats at all for pid {pid} - league-average "
                  f"fallback, reliability 0")
            return {
                "era":  LEAGUE_AVG_ERA,
                "whip": LEAGUE_AVG_WHIP,
                "k9":   LEAGUE_AVG_K9,
                "bb9":  LEAGUE_AVG_BB9,
                "fip":  LEAGUE_AVG_FIP,
                "hand": hand,
                "reliability": 0.0
            }, pid

        # If no current season fall back to career
        if not current:
            print(f"  WARNING: no current-season stats for pid {pid} - "
                  f"career fallback")
            career["hand"] = hand
            career["reliability"] = round(
                min(career.get("ip", 0) / RELIABLE_IP, 1.0) * 100, 1)
            return career, pid

        # If no career use current only
        if not career:
            current["hand"] = hand
            current["reliability"] = round(
                min(current.get("ip", 0) / RELIABLE_IP, 1.0) * 100, 1)
            return current, pid

        # Blend: weight current by IP vs reliable threshold
        reliability = min(current["ip"] / RELIABLE_IP, 1.0)
        prior_weight = 1.0 - reliability

        blended = {
            "era":  round(current["era"]  * reliability + career["era"]  * prior_weight, 3),
            "whip": round(current["whip"] * reliability + career["whip"] * prior_weight, 3),
            "k9":   round(current["k9"]   * reliability + career["k9"]   * prior_weight, 3),
            "bb9":  round(current["bb9"]  * reliability + career["bb9"]  * prior_weight, 3),
            "fip":  round(current["fip"]  * reliability + career["fip"]  * prior_weight, 3),
            "hand": hand,
            "ip":   current["ip"],
            "reliability": round(reliability * 100, 1)
        }
        return blended, pid

    except:
        return None, None