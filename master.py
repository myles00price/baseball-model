import requests
import pandas as pd
from pybaseball import statcast_pitcher, playerid_lookup
from datetime import datetime, timedelta, timezone
import csv
import pickle
import numpy as np
import warnings
warnings.filterwarnings("ignore")
import os

from pitcher_stats import get_blended_pitcher_stats
from lineup_stats import get_platoon_lineup_ops
from bullpen_stats import get_bullpen_stats
from line_tracker import save_current_lines, get_line_movement

# ─────────────────────────────────────────────────────────────
# master.py — Problems 2 + 3 (+ 5) applied:
#   2) Pitcher stat = FIP (not ERA/WHIP) — matches weekly_retrain.py
#   3) Probability caps widened: 35–65 → 30–70 in all four spots
#      (predict, park factor, bullpen adj, home boost)
#   5) Feature list trimmed: era/whip dropped, FIP + K/9 + BB/9 kept
#
# Requires pitcher_stats.get_blended_pitcher_stats() to return "fip"
# in its dict (alongside k9, bb9, hand, reliability). Update that
# module before deploying or this will KeyError on home_stats["fip"].
# ─────────────────────────────────────────────────────────────

PARK_FACTORS = {
    "Colorado Rockies":        118,
    "Cincinnati Reds":         106,
    "Philadelphia Phillies":   105,
    "Boston Red Sox":          104,
    "Chicago Cubs":            104,
    "Texas Rangers":           103,
    "Baltimore Orioles":       102,
    "Atlanta Braves":          102,
    "New York Yankees":        101,
    "Milwaukee Brewers":       100,
    "Toronto Blue Jays":       100,
    "Minnesota Twins":         100,
    "Detroit Tigers":          100,
    "Houston Astros":          99,
    "Kansas City Royals":      99,
    "Washington Nationals":    99,
    "Chicago White Sox":       99,
    "Cleveland Guardians":     98,
    "Tampa Bay Rays":          98,
    "Pittsburgh Pirates":      98,
    "St. Louis Cardinals":     98,
    "Arizona Diamondbacks":    97,
    "New York Mets":           97,
    "Los Angeles Angels":      97,
    "Miami Marlins":           96,
    "Los Angeles Dodgers":     96,
    "Seattle Mariners":        96,
    "San Francisco Giants":    95,
    "Athletics":               95,
    "San Diego Padres":        94,
}

def apply_park_factor(home_prob, home_team):
    factor = PARK_FACTORS.get(home_team, 100)
    multiplier = 0.6 if home_team == "Colorado Rockies" else 0.3
    adjustment = ((factor - 100) / 100) * (home_prob - 50) * multiplier
    home_prob = home_prob - adjustment
    return round(max(30, min(70, home_prob)), 1)

def apply_bullpen_adjustment(home_prob, home_bullpen, away_bullpen):
    if not home_bullpen or not away_bullpen:
        return home_prob
    score_diff = away_bullpen["bullpen_score"] - home_bullpen["bullpen_score"]
    adjustment = max(-5, min(5, score_diff * 10))
    home_prob = home_prob + adjustment
    return round(max(30, min(70, home_prob)), 1)

def get_team_stats(season):
    data = requests.get(
        "https://statsapi.mlb.com/api/v1/teams/stats",
        params={"season": season, "sportId": 1, "group": "hitting", "stats": "season"}
    ).json()
    team_stats = {}
    for team in data["stats"][0]["splits"]:
        name = team["team"]["name"]
        s = team["stat"]
        team_stats[name] = {
            "ops":  float(s.get("ops", 0)),
            "kpct": round(int(s.get("strikeOuts", 0)) / max(int(s.get("plateAppearances", 1)), 1) * 100, 1),
            "runs": float(s.get("runs", 0))
        }
    return team_stats

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
            lineups[home] = home_players if home_players else []
            lineups[away] = away_players if away_players else []
    return lineups

def load_model():
    with open("model.pkl", "rb") as f:
        model = pickle.load(f)
    with open("scaler.pkl", "rb") as f:
        scaler = pickle.load(f)
    return model, scaler

def predict_home_win_prob(
    home_fip, home_k9, home_bb9,
    away_fip, away_k9, away_bb9,
    home_ops, home_kpct, away_ops, away_kpct
):
    """
    Feature order MUST match weekly_retrain.py FEATURES:
      home_fip, home_k9, home_bb9,
      away_fip, away_k9, away_bb9,
      home_ops, home_kpct, away_ops, away_kpct,
      fip_diff, k9_diff, ops_diff
    """
    model, scaler = load_model()
    fip_diff = away_fip - home_fip
    k9_diff  = home_k9  - away_k9
    ops_diff = home_ops - away_ops
    features = np.array([[
        home_fip, home_k9, home_bb9,
        away_fip, away_k9, away_bb9,
        home_ops, home_kpct, away_ops, away_kpct,
        fip_diff, k9_diff, ops_diff
    ]])
    features_scaled = scaler.transform(features)
    prob = model.predict_proba(features_scaled)[0][1]
    prob = max(0.30, min(0.70, prob))
    return round(prob * 100, 1)

def american_to_prob(odds):
    try:
        odds = float(odds)
        if odds < 0:
            return round((-odds) / (-odds + 100) * 100, 1)
        else:
            return round(100 / (odds + 100) * 100, 1)
    except:
        return None

def edge(model_p, market_p, reliable=True):
    if model_p and market_p:
        e = round(model_p - market_p, 1)
        flag = " ** BET **" if (6 <= e <= 10 and reliable) else ""
        return f"{e:+.1f}%{flag}"
    return "N/A"

def save_picks_to_csv(picks, date_str):
    filename = f"picks_{date_str}.csv"
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Date", "Away", "Home",
            "Model Away%", "Model Home%",
            "DK Away Odds", "DK Home Odds",
            "MGM Away Odds", "MGM Home Odds",
            "DK Edge Away", "MGM Edge Away",
            "DK Edge Home", "MGM Edge Home",
            "Away SP", "Away Hand", "Away Reliability%",
            "Away SP Velo", "Away SP Spin", "Away SP Whiff",
            "Home SP", "Home Hand", "Home Reliability%",
            "Home SP Velo", "Home SP Spin", "Home SP Whiff",
            "Away Lineup OPS", "Home Lineup OPS",
            "Away BP ERA(7d)", "Home BP ERA(7d)",
            "Away Line Move", "Home Line Move",
            "Sharp Signal",
            "Lineup Source", "Park Factor", "Flag"
        ])
        for pick in picks:
            writer.writerow([str(p) for p in pick])
    print(f"\nPicks saved to {filename}")

def run_model(target_date, save_csv=True):
    las_vegas_offset = timezone(timedelta(hours=-7))
    target = target_date
    target_str = target.strftime("%Y-%m-%d")
    season = target.year
    season_start = f"{season}-04-01"

    print(f"Loading data for {target_str}...\n")

    # Pull odds
    odds_resp = requests.get(
        "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/",
        params={
            "apiKey": os.environ.get("ODDS_API_KEY", "719921510f0839e3f61743f271956eea"),
            "regions": "us",
            "markets": "h2h",
            "oddsFormat": "american",
            "bookmakers": "draftkings,williamhill_us,betmgm"
        }
    ).json()

    odds_lookup = {}
    for game in odds_resp:
        for bookmaker in game["bookmakers"]:
            bk = bookmaker["key"]
            for market in bookmaker["markets"]:
                if market["key"] == "h2h":
                    for outcome in market["outcomes"]:
                        team = outcome["name"]
                        if team not in odds_lookup:
                            odds_lookup[team] = {}
                        odds_lookup[team][bk] = outcome["price"]

    # Pull schedule
    schedule = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={"sportId": 1, "date": target_str, "hydrate": "probablePitcher"}
    ).json()

    # Pull team stats
    team_stats = get_team_stats(season)

    # Pull confirmed lineups
    print("Pulling confirmed lineups...")
    lineups = get_todays_lineups(target_str, season)
    confirmed = sum(1 for v in lineups.values() if v)
    print(f"Lineups confirmed for {confirmed} teams")

    # Pull bullpen stats
    print("Pulling bullpen stats...")
    bullpen = get_bullpen_stats(season)
    print(f"Bullpen data loaded for {len(bullpen)} teams")

    # Save opening lines and get movement
    print("Pulling line movement...")
    save_current_lines(target_str)
    movement = get_line_movement(target_str)
    print(f"Line movement data for {len(movement)} games\n")

    def get_pitcher_whiff(full_name):
        if not full_name or full_name == "TBD":
            return None, None, None, "TBD"
        try:
            parts = full_name.split()
            first, last = parts[0], parts[-1]
            lookup = playerid_lookup(last, first)
            if lookup.empty:
                return None, None, None, f"{full_name} | Not found"
            pid = int(lookup.iloc[0]['key_mlbam'])
            data = statcast_pitcher(season_start, target_str, player_id=pid)
            if data.empty:
                return None, None, None, f"{full_name} | No data yet"
            velo  = round(data['release_speed'].mean(), 1)
            spin  = round(data['release_spin_rate'].mean(), 0)
            whiff = round((data['description'] == 'swinging_strike').mean() * 100, 1)
            return velo, spin, whiff, f"{full_name} | Velo: {velo} | Spin: {spin:.0f} | Whiff: {whiff:.1f}%"
        except:
            return None, None, None, f"{full_name} | Error"

    print("=" * 75)
    print(f"  MLB MODEL REPORT — {target_str}")
    print("=" * 75)

    picks = []

    # Load existing picks CSV to freeze Live/Final games
    existing_picks = {}
    existing_csv = f"picks_{target_str}.csv"
    if os.path.exists(existing_csv):
        import csv as csv_module
        with open(existing_csv, encoding="utf-8-sig") as f:
            for row in csv_module.DictReader(f):
                key = f"{row['Away']}@{row['Home']}"
                existing_picks[key] = row
        print(f"Loaded {len(existing_picks)} existing picks to freeze Live/Final games\n")

    for date in schedule.get("dates", []):
        for game in date.get("games", []):
            game_status = game.get("status", {}).get("abstractGameState", "")
            home = game["teams"]["home"]["team"]["name"]
            away = game["teams"]["away"]["team"]["name"]
            game_key = f"{away}@{home}"

            # Freeze Live and Final games — use existing pick unchanged
            if game_status in ["Live", "Final"]:
                if game_key in existing_picks:
                    row = existing_picks[game_key]
                    picks.append([row.get(col, "") for col in [
                        "Date", "Away", "Home",
                        "Model Away%", "Model Home%",
                        "DK Away Odds", "DK Home Odds",
                        "MGM Away Odds", "MGM Home Odds",
                        "DK Edge Away", "MGM Edge Away",
                        "DK Edge Home", "MGM Edge Home",
                        "Away SP", "Away Hand", "Away Reliability%",
                        "Away SP Velo", "Away SP Spin", "Away SP Whiff",
                        "Home SP", "Home Hand", "Home Reliability%",
                        "Home SP Velo", "Home SP Spin", "Home SP Whiff",
                        "Away Lineup OPS", "Home Lineup OPS",
                        "Away BP ERA(7d)", "Home BP ERA(7d)",
                        "Away Line Move", "Home Line Move",
                        "Sharp Signal", "Lineup Source", "Park Factor", "Flag"
                    ]])
                    status_label = "🔴 LIVE" if game_status == "Live" else "✅ FINAL"
                    print(f"  {status_label} — {away} @ {home} [FROZEN — using pre-game pick]")
                continue
            home_p = game["teams"]["home"].get("probablePitcher", {}).get("fullName", "TBD")
            away_p = game["teams"]["away"].get("probablePitcher", {}).get("fullName", "TBD")

            # Blended pitcher stats — must return {"fip", "k9", "bb9", "hand", "reliability"}
            home_stats, home_pid = get_blended_pitcher_stats(home_p, season, playerid_lookup)
            away_stats, away_pid = get_blended_pitcher_stats(away_p, season, playerid_lookup)

            home_hand = home_stats["hand"] if home_stats else "R"
            away_hand = away_stats["hand"] if away_stats else "R"
            home_rel  = home_stats.get("reliability", 0) if home_stats else 0
            away_rel  = away_stats.get("reliability", 0) if away_stats else 0

            # Pitcher whiff stats — now returns velo, spin, whiff separately
            away_velo, away_spin, away_whiff, away_str = get_pitcher_whiff(away_p)
            home_velo, home_spin, home_whiff, home_str = get_pitcher_whiff(home_p)

            home_players = lineups.get(home, [])
            away_players = lineups.get(away, [])

            if home_players and away_players:
                home_lineup_ops = get_platoon_lineup_ops(away_players, season, home_hand)
                away_lineup_ops = get_platoon_lineup_ops(home_players, season, away_hand)
                lineup_source = "CONFIRMED+PLATOON"
            elif home_players or away_players:
                home_lineup_ops = get_platoon_lineup_ops(away_players, season, home_hand) if away_players else None
                away_lineup_ops = get_platoon_lineup_ops(home_players, season, away_hand) if home_players else None
                lineup_source = "PARTIAL"
            else:
                home_lineup_ops = None
                away_lineup_ops = None
                lineup_source = "ESTIMATED"

            home_off = team_stats.get(home, {})
            away_off = team_stats.get(away, {})
            home_ops  = home_lineup_ops if home_lineup_ops else home_off.get("ops", 0.72)
            away_ops  = away_lineup_ops if away_lineup_ops else away_off.get("ops", 0.72)
            home_kpct = home_off.get("kpct", 20)
            away_kpct = away_off.get("kpct", 20)

            park_factor = PARK_FACTORS.get(home, 100)
            home_bull = bullpen.get(home)
            away_bull = bullpen.get(away)

            # Line movement
            game_key = f"{away}@{home}"
            move_data = movement.get(game_key, {})
            away_move = move_data.get("teams", {}).get(away, {})
            home_move = move_data.get("teams", {}).get(home, {})

            away_prob = None
            home_prob = None
            try:
                if home_stats and away_stats:
                    home_prob = predict_home_win_prob(
                        home_stats["fip"], home_stats["k9"], home_stats["bb9"],
                        away_stats["fip"], away_stats["k9"], away_stats["bb9"],
                        home_ops, home_kpct,
                        away_ops, away_kpct
                    )
                    home_prob = min(70, home_prob + 0.5)  # home field boost, capped at new ceiling
                    home_prob = apply_park_factor(home_prob, home)
                    home_prob = apply_bullpen_adjustment(home_prob, home_bull, away_bull)
                    away_prob = round(100 - home_prob, 1)
            except:
                pass

            dk_away  = american_to_prob(odds_lookup.get(away, {}).get("draftkings"))
            mgm_away = american_to_prob(odds_lookup.get(away, {}).get("betmgm"))
            dk_home  = american_to_prob(odds_lookup.get(home, {}).get("draftkings"))
            mgm_home = american_to_prob(odds_lookup.get(home, {}).get("betmgm"))

            min_reliability = min(home_rel, away_rel)
            reliable = min_reliability >= 8 and home != "Colorado Rockies"

            # Sharp signal
            sharp_signal = "N/A"
            if away_move and home_move and away_prob and home_prob:
                model_favors = away if away_prob > home_prob else home
                away_movement = away_move.get("movement", 0)
                home_movement = home_move.get("movement", 0)
                away_mov = abs(away_movement)
                home_mov = abs(home_movement)
                if max(away_mov, home_mov) < 1.5:
                    sharp_signal = "N/A"
                else:
                    market_moving_toward = away if away_movement > home_movement else home
                    if model_favors == market_moving_toward:
                        sharp_signal = "CONFIRMED ✓"
                    else:
                        sharp_signal = "FADE ✗"

            print(f"\n{away} @ {home} [{lineup_source}] [Park: {park_factor}]")
            print(f"  {away_p} ({away_hand}) rel:{away_rel}% | {home_p} ({home_hand}) rel:{home_rel}%")
            print(f"  Platoon OPS — {away}: {away_ops:.3f} vs {home_hand}HP | {home}: {home_ops:.3f} vs {away_hand}HP")
            if home_bull and away_bull:
                print(f"  Away BP: ERA(7d): {away_bull['era_recent']} | "
                      f"Sv/BSv: {away_bull['saves']}/{away_bull['blown_saves']} | "
                      f"Score: {away_bull['bullpen_score']}")
                print(f"  Home BP: ERA(7d): {home_bull['era_recent']} | "
                      f"Sv/BSv: {home_bull['saves']}/{home_bull['blown_saves']} | "
                      f"Score: {home_bull['bullpen_score']}")
            if away_move and home_move:
                print(f"  Line Move — "
                      f"{away}: {away_move.get('open_odds')} → {away_move.get('current_odds')} "
                      f"({away_move.get('movement', 0):+.1f}%) {away_move.get('direction', '')} | "
                      f"{home}: {home_move.get('open_odds')} → {home_move.get('current_odds')} "
                      f"({home_move.get('movement', 0):+.1f}%) {home_move.get('direction', '')} | "
                      f"Sharp: {sharp_signal}")
            print(f"  {'Team':<30} {'Model%':>7} {'DK Imp%':>8} {'MGM Imp%':>9} {'DK Edge':>8} {'MGM Edge':>9}")
            print(f"  {'-'*70}")
            print(f"  {away:<30} {str(away_prob)+'%' if away_prob else 'N/A':>7} "
                  f"{str(dk_away)+'%' if dk_away else 'N/A':>8} "
                  f"{str(mgm_away)+'%' if mgm_away else 'N/A':>9} "
                  f"{edge(away_prob, dk_away, reliable):>8} {edge(away_prob, mgm_away, reliable):>9}")
            print(f"  {home:<30} {str(home_prob)+'%' if home_prob else 'N/A':>7} "
                  f"{str(dk_home)+'%' if dk_home else 'N/A':>8} "
                  f"{str(mgm_home)+'%' if mgm_home else 'N/A':>9} "
                  f"{edge(home_prob, dk_home, reliable):>8} {edge(home_prob, mgm_home, reliable):>9}")
            print(f"  Away SP: {away_str}")
            print(f"  Home SP: {home_str}")
            print("-" * 75)

            bet_flag = "** BET **" if (reliable and any(
                "BET" in str(edge(p, m, reliable))
                for p, m in [(away_prob, dk_away), (away_prob, mgm_away),
                             (home_prob, dk_home), (home_prob, mgm_home)]
            )) else ""

            picks.append([
                target_str, away, home,
                away_prob, home_prob,
                odds_lookup.get(away, {}).get("draftkings", "N/A"),
                odds_lookup.get(home, {}).get("draftkings", "N/A"),
                odds_lookup.get(away, {}).get("betmgm", "N/A"),
                odds_lookup.get(home, {}).get("betmgm", "N/A"),
                edge(away_prob, dk_away, reliable), edge(away_prob, mgm_away, reliable),
                edge(home_prob, dk_home, reliable), edge(home_prob, mgm_home, reliable),
                away_p, away_hand, away_rel,
                away_velo, away_spin, away_whiff,
                home_p, home_hand, home_rel,
                home_velo, home_spin, home_whiff,
                away_ops, home_ops,
                away_bull["era_recent"] if away_bull else "N/A",
                home_bull["era_recent"] if home_bull else "N/A",
                away_move.get("movement", "N/A") if away_move else "N/A",
                home_move.get("movement", "N/A") if home_move else "N/A",
                sharp_signal,
                lineup_source, park_factor, bet_flag
            ])

    if save_csv:
        save_picks_to_csv(picks, target_str)

if __name__ == '__main__':
    las_vegas_offset = timezone(timedelta(hours=-7))
    tomorrow = datetime.now(las_vegas_offset) + timedelta(days=1)
    run_model(tomorrow, save_csv=True)