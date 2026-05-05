import requests
import pandas as pd
import time
import os
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Session with automatic retries
def make_session():
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

SESSION = make_session()

def get_game_ids(season):
    print(f"Pulling {season} game IDs...")
    data = SESSION.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={"sportId": 1, "season": season, "gameType": "R"},
        timeout=30
    ).json()
    games = []
    for date in data.get("dates", []):
        for game in date.get("games", []):
            if game.get("status", {}).get("abstractGameState") == "Final":
                games.append({
                    "game_id":    game["gamePk"],
                    "date":       date["date"],
                    "home_team":  game["teams"]["home"]["team"]["name"],
                    "away_team":  game["teams"]["away"]["team"]["name"],
                    "home_score": game["teams"]["home"].get("score", 0),
                    "away_score": game["teams"]["away"].get("score", 0),
                })
    print(f"  Found {len(games)} games")
    return games

def get_boxscore(game_id):
    try:
        data = SESSION.get(
            f"https://statsapi.mlb.com/api/v1/game/{game_id}/boxscore",
            timeout=30
        ).json()
        return data
    except Exception as e:
        print(f"    Boxscore error {game_id}: {e}")
        return None

def get_batter_season_stats(player_id, season):
    try:
        data = SESSION.get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
            params={"stats": "season", "season": season, "group": "hitting"},
            timeout=30
        ).json()
        splits = data["stats"][0]["splits"]
        if not splits:
            return None
        s = splits[0]["stat"]
        ops = float(s.get("ops", 0))
        if ops == 0:
            return None
        return ops
    except:
        return None

def get_lineup_ops_from_boxscore(boxscore, side, season):
    try:
        batters = boxscore["teams"][side]["batters"]
        ops_list = []
        for pid in batters[:9]:
            ops = get_batter_season_stats(pid, season)
            if ops:
                ops_list.append(ops)
        if not ops_list:
            return None
        return round(sum(ops_list) / len(ops_list), 3)
    except:
        return None

def get_pitcher_stats(player_id, season):
    try:
        data = SESSION.get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
            params={"stats": "season", "season": season, "group": "pitching"},
            timeout=30
        ).json()
        splits = data["stats"][0]["splits"]
        if not splits:
            return None
        s = splits[0]["stat"]
        ip = float(s.get("inningsPitched", 0))
        if ip < 1:
            return None
        return {
            "era":  float(s.get("era", 4.50)),
            "whip": float(s.get("whip", 1.30)),
            "k9":   float(s.get("strikeoutsPer9Inn", 8.0)),
            "bb9":  float(s.get("walksPer9Inn", 3.0)),
        }
    except:
        return None

def get_team_stats(season):
    data = SESSION.get(
        "https://statsapi.mlb.com/api/v1/teams/stats",
        params={"season": season, "sportId": 1, "group": "hitting", "stats": "season"},
        timeout=30
    ).json()
    team_stats = {}
    for team in data["stats"][0]["splits"]:
        name = team["team"]["name"]
        s = team["stat"]
        team_stats[name] = {
            "ops":  float(s.get("ops", 0)),
            "kpct": round(int(s.get("strikeOuts", 0)) / max(int(s.get("plateAppearances", 1)), 1) * 100, 1),
        }
    return team_stats

if __name__ == "__main__":
    existing_file = "training_data.csv"
    checkpoint_file = "training_checkpoint.csv"

    # Load existing completed seasons
    if os.path.exists(existing_file):
        existing_df = pd.read_csv(existing_file)
        all_rows = existing_df.to_dict("records")
        done_seasons = existing_df["season"].unique().tolist()
        print(f"Loaded {len(all_rows)} existing rows from seasons: {done_seasons}")
    else:
        all_rows = []
        done_seasons = []

    for season in [2023, 2024, 2025]:
        if season in done_seasons:
            print(f"Skipping {season} — already processed")
            continue

        print(f"\n=== Processing {season} ===")

        # Load checkpoint for partial season progress
        checkpoint_rows = []
        done_game_ids = set()
        if os.path.exists(checkpoint_file):
            cp = pd.read_csv(checkpoint_file)
            season_cp = cp[cp["season"] == season]
            if not season_cp.empty:
                checkpoint_rows = season_cp.to_dict("records")
                done_game_ids = set(season_cp["game_id"].tolist()) if "game_id" in season_cp.columns else set()
                print(f"  Resuming from checkpoint: {len(checkpoint_rows)} games already done")

        try:
            games = get_game_ids(season)
            team_stats = get_team_stats(season)
        except Exception as e:
            print(f"  Failed to get game list: {e}")
            continue

        season_rows = list(checkpoint_rows)

        for i, game in enumerate(games):
            if game["game_id"] in done_game_ids:
                continue

            if i % 50 == 0:
                print(f"  Game {i}/{len(games)}... ({len(season_rows)} rows so far)")

            try:
                boxscore = get_boxscore(game["game_id"])
                if not boxscore:
                    continue

                home_pitchers = boxscore["teams"]["home"]["pitchers"]
                away_pitchers = boxscore["teams"]["away"]["pitchers"]
                home_sp_id = home_pitchers[0] if home_pitchers else None
                away_sp_id = away_pitchers[0] if away_pitchers else None

                home_p = get_pitcher_stats(home_sp_id, season)
                away_p = get_pitcher_stats(away_sp_id, season)

                if not home_p or not away_p:
                    continue

                home_lineup_ops = get_lineup_ops_from_boxscore(boxscore, "home", season)
                away_lineup_ops = get_lineup_ops_from_boxscore(boxscore, "away", season)

                home_off = team_stats.get(game["home_team"], {})
                away_off = team_stats.get(game["away_team"], {})

                home_ops  = home_lineup_ops if home_lineup_ops else home_off.get("ops", 0.72)
                away_ops  = away_lineup_ops if away_lineup_ops else away_off.get("ops", 0.72)
                home_kpct = home_off.get("kpct", 20)
                away_kpct = away_off.get("kpct", 20)

                home_win = 1 if game["home_score"] > game["away_score"] else 0

                row = {
                    "season":    season,
                    "game_id":   game["game_id"],
                    "date":      game["date"],
                    "home_team": game["home_team"],
                    "away_team": game["away_team"],
                    "home_win":  home_win,
                    "home_era":  home_p["era"],
                    "home_whip": home_p["whip"],
                    "home_k9":   home_p["k9"],
                    "home_bb9":  home_p["bb9"],
                    "away_era":  away_p["era"],
                    "away_whip": away_p["whip"],
                    "away_k9":   away_p["k9"],
                    "away_bb9":  away_p["bb9"],
                    "home_ops":  home_ops,
                    "home_kpct": home_kpct,
                    "away_ops":  away_ops,
                    "away_kpct": away_kpct,
                    "era_diff":  away_p["era"]  - home_p["era"],
                    "k9_diff":   home_p["k9"]   - away_p["k9"],
                    "ops_diff":  home_ops - away_ops,
                }
                season_rows.append(row)
                done_game_ids.add(game["game_id"])

                # Save checkpoint every 100 games
                if len(season_rows) % 100 == 0:
                    cp_df = pd.DataFrame(season_rows)
                    cp_df["season"] = season
                    cp_df.to_csv(checkpoint_file, index=False)

            except Exception as e:
                print(f"    Error on game {game['game_id']}: {e}")
                time.sleep(5)
                continue

        # Season complete — add to main data
        all_rows.extend(season_rows)
        df = pd.DataFrame(all_rows)
        df.to_csv(existing_file, index=False)
        print(f"  Season {season} done! Total rows: {len(df)}")

        # Clear checkpoint for this season
        if os.path.exists(checkpoint_file):
            os.remove(checkpoint_file)

        time.sleep(2)

    df = pd.DataFrame(all_rows)
    df.to_csv(existing_file, index=False)
    print(f"\nDone! Saved {len(df)} total games to training_data.csv") 