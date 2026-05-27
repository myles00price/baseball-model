import requests
import pandas as pd
import pickle
import numpy as np
import time
import os
from datetime import datetime, timedelta, timezone
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, brier_score_loss

FEATURES = [
    "home_era", "home_whip", "home_k9", "home_bb9",
    "away_era", "away_whip", "away_k9", "away_bb9",
    "home_ops", "home_kpct", "away_ops", "away_kpct",
    "era_diff", "k9_diff", "ops_diff"
]

# ── Recency weights ───────────────────────────────────────────
# 2026 games are 3x more important than historical
# 2025 games are 1.5x, everything older is 1x
SEASON_WEIGHTS = {
    2026: 3.0,
    2025: 1.5,
}
DEFAULT_WEIGHT = 1.0

def get_sample_weight(season):
    return SEASON_WEIGHTS.get(int(season), DEFAULT_WEIGHT)

def get_last_week_games():
    lv = timezone(timedelta(hours=-7))
    end   = datetime.now(lv)
    start = end - timedelta(days=7S)
    print(f"Pulling games from {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}...")

    games = []
    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        data = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": date_str, "hydrate": "linescore"},
            timeout=30
        ).json()
        for date in data.get("dates", []):
            for game in date.get("games", []):
                if game.get("status", {}).get("abstractGameState") != "Final":
                    continue
                home = game["teams"]["home"]["team"]["name"]
                away = game["teams"]["away"]["team"]["name"]
                home_score = game["teams"]["home"].get("score", 0)
                away_score = game["teams"]["away"].get("score", 0)
                games.append({
                    "game_id":    game["gamePk"],
                    "date":       date_str,
                    "home_team":  home,
                    "away_team":  away,
                    "home_score": home_score,
                    "away_score": away_score,
                })
        current += timedelta(days=1)

    print(f"Found {len(games)} completed games")
    return games

def get_pitcher_stats(player_id, season):
    try:
        data = requests.get(
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

def get_boxscore_pitchers(game_id):
    try:
        data = requests.get(
            f"https://statsapi.mlb.com/api/v1/game/{game_id}/boxscore",
            timeout=30
        ).json()
        home_sp = data["teams"]["home"]["pitchers"][0] if data["teams"]["home"]["pitchers"] else None
        away_sp = data["teams"]["away"]["pitchers"][0] if data["teams"]["away"]["pitchers"] else None
        home_batters = data["teams"]["home"]["batters"]
        away_batters = data["teams"]["away"]["batters"]
        return home_sp, away_sp, home_batters, away_batters
    except:
        return None, None, [], []

def get_batter_ops(player_id, season):
    try:
        data = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
            params={"stats": "season", "season": season, "group": "hitting"},
            timeout=30
        ).json()
        splits = data["stats"][0]["splits"]
        if not splits:
            return None
        ops = float(splits[0]["stat"].get("ops", 0))
        return ops if ops > 0 else None
    except:
        return None

def get_lineup_ops(batters, season):
    ops_list = []
    for pid in batters[:9]:
        ops = get_batter_ops(pid, season)
        if ops:
            ops_list.append(ops)
    if not ops_list:
        return None
    return round(sum(ops_list) / len(ops_list), 3)

def get_team_stats(season):
    data = requests.get(
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

def build_new_rows(games, season):
    team_stats = get_team_stats(season)
    new_rows = []

    for i, game in enumerate(games):
        if i % 10 == 0:
            print(f"  Processing game {i}/{len(games)}...")
        try:
            home_sp_id, away_sp_id, home_batters, away_batters = get_boxscore_pitchers(game["game_id"])
            home_p = get_pitcher_stats(home_sp_id, season)
            away_p = get_pitcher_stats(away_sp_id, season)
            if not home_p or not away_p:
                continue

            home_lineup_ops = get_lineup_ops(home_batters, season)
            away_lineup_ops = get_lineup_ops(away_batters, season)
            home_off = team_stats.get(game["home_team"], {})
            away_off = team_stats.get(game["away_team"], {})
            home_ops  = home_lineup_ops if home_lineup_ops else home_off.get("ops", 0.72)
            away_ops  = away_lineup_ops if away_lineup_ops else away_off.get("ops", 0.72)
            home_kpct = home_off.get("kpct", 20)
            away_kpct = away_off.get("kpct", 20)
            home_win  = 1 if game["home_score"] > game["away_score"] else 0

            new_rows.append({
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
                "era_diff":  away_p["era"] - home_p["era"],
                "k9_diff":   home_p["k9"]  - away_p["k9"],
                "ops_diff":  home_ops - away_ops,
            })
        except:
            continue

    print(f"Built {len(new_rows)} new training rows")
    return new_rows

def retrain_model(df):
    print("\nRetraining model...")

    current_season = datetime.now().year

    # ── Sample weights — 2026 games count 3x, 2025 count 1.5x ──
    df["weight"] = df["season"].apply(get_sample_weight)

    # ── Train on ALL data with weights, test on current season ──
    X_all   = df[FEATURES]
    y_all   = df["home_win"]
    w_all   = df["weight"]

    test_mask  = df["season"] == current_season
    train_mask = ~test_mask

    # If not enough current season data, use all for both
    if test_mask.sum() < 50:
        X_train, y_train, w_train = X_all, y_all, w_all
        X_test,  y_test           = X_all, y_all
    else:
        X_train = df.loc[train_mask, FEATURES]
        y_train = df.loc[train_mask, "home_win"]
        w_train = df.loc[train_mask, "weight"]
        X_test  = df.loc[test_mask, FEATURES]
        y_test  = df.loc[test_mask, "home_win"]

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled  = scaler.transform(X_test)

    # Train with sample weights
    lr = LogisticRegression(max_iter=1000)
    # CalibratedClassifierCV doesn't directly support sample_weight in fit
    # So we fit the base LR with weights, then calibrate
    lr.fit(X_train_scaled, y_train, sample_weight=w_train)
    model = CalibratedClassifierCV(lr, cv=5)
    model.fit(X_train_scaled, y_train)

    preds = model.predict(X_test_scaled)
    probs = model.predict_proba(X_test_scaled)[:, 1]
    acc   = accuracy_score(y_test, preds)
    brier = brier_score_loss(y_test, probs)

    # Weight breakdown for transparency
    n_2026 = (df["season"] == current_season).sum()
    n_hist = (df["season"] < current_season).sum()
    eff_2026 = n_2026 * SEASON_WEIGHTS.get(current_season, 1.0)
    eff_hist = sum(
        (df["season"] == s).sum() * SEASON_WEIGHTS.get(s, DEFAULT_WEIGHT)
        for s in df["season"].unique() if s < current_season
    )

    print(f"  Accuracy: {acc:.3f} ({acc*100:.1f}%)")
    print(f"  Brier Score: {brier:.4f}")
    print(f"  Training rows: {len(X_train)}")
    print(f"  Test rows: {len(X_test)} ({current_season} season only)")
    print(f"  Weight split: {current_season} = {eff_2026:.0f} effective rows | Historical = {eff_hist:.0f} effective rows")

    with open("model.pkl", "wb") as f:
        pickle.dump(model, f)
    with open("scaler.pkl", "wb") as f:
        pickle.dump(scaler, f)

    print("  Model saved!")
    return acc, brier

def run_weekly_retrain():
    print("\n" + "=" * 55)
    print("  WEEKLY MODEL RETRAINING")
    print("=" * 55)
    print(f"  Running: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55 + "\n")

    season = datetime.now().year

    # Step 1 — Get last week's games
    games = get_last_week_games()
    if not games:
        print("No games found — skipping retrain")
        return

    # Step 2 — Build new rows
    print("\nBuilding new training rows...")
    new_rows = build_new_rows(games, season)
    if not new_rows:
        print("No new rows built — skipping retrain")
        return

    # Step 3 — Load existing training data
    existing_file = "training_data.csv"
    if os.path.exists(existing_file):
        existing_df = pd.read_csv(existing_file)
        print(f"Loaded {len(existing_df)} existing training rows")
    else:
        existing_df = pd.DataFrame()

    # Step 4 — Add new rows, deduplicate
    new_df = pd.DataFrame(new_rows)
    if not existing_df.empty:
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        if "game_id" in combined.columns:
            combined = combined.drop_duplicates(subset=["game_id"])
    else:
        combined = new_df

    combined.to_csv(existing_file, index=False)
    print(f"Training data updated: {len(combined)} total rows (+{len(new_rows)} new)")

    # Step 5 — Retrain with recency weights
    acc, brier = retrain_model(combined)

    # Step 6 — Log the retrain
    log_entry = {
        "date":        datetime.now().strftime("%Y-%m-%d"),
        "new_games":   len(new_rows),
        "total_games": len(combined),
        "accuracy":    round(acc, 4),
        "brier":       round(brier, 4)
    }
    log_file = "retrain_log.csv"
    log_df = pd.DataFrame([log_entry])
    if os.path.exists(log_file):
        existing_log = pd.read_csv(log_file)
        log_df = pd.concat([existing_log, log_df], ignore_index=True)
    log_df.to_csv(log_file, index=False)

    print(f"\n✅ Retrain complete!")
    print(f"   New games added: {len(new_rows)}")
    print(f"   Total training games: {len(combined)}")
    print(f"   New accuracy: {acc*100:.1f}%")
    print(f"   2026 data weighted 3x, 2025 weighted 1.5x")

if __name__ == "__main__":
    run_weekly_retrain()