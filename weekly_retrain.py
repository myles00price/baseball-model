import requests
import pandas as pd
import pickle
import numpy as np
import time
import os
from datetime import datetime, timedelta, timezone
from xgboost import XGBClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, brier_score_loss

# ─────────────────────────────────────────────────────────────
# weekly_retrain.py — ERA/WHIP RESTORED alongside FIP.
#
# Why: the FIP-only swap (old Problems 2+5) regressed accuracy
# from 63.6% → 57.5% across two algorithms. FIP is a projection
# stat that deliberately discards realized run-prevention (hits,
# defense) — bad for single-game prediction. ERA + WHIP carry
# that signal. We keep all three; XGBoost handles the correlation
# that made this a bad idea under logistic regression.
#
# Feature set is now a SUPERSET of the known-good 63.6% set, plus
# FIP. Worst case it matches 63.6% and FIP is ignored.
#
# Still in place: platoon-adjusted OPS (good, independent),
# XGBoost + isotonic calibration, wider 30–70 caps (master.py).
#
# Requires training_data.csv to have era/whip AND fip columns —
# run rebuild_features.py once before this.
# ─────────────────────────────────────────────────────────────

FEATURES = [
    "home_era", "home_whip", "home_fip", "home_k9", "home_bb9",
    "away_era", "away_whip", "away_fip", "away_k9", "away_bb9",
    "home_ops", "home_kpct", "away_ops", "away_kpct",
    "era_diff", "fip_diff", "k9_diff", "ops_diff"
]

XGB_PARAMS = {
    "n_estimators":     300,
    "max_depth":        3,
    "learning_rate":    0.05,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,
    "reg_lambda":       1.0,
    "reg_alpha":        0.0,
    "gamma":            0.0,
    "objective":        "binary:logistic",
    "eval_metric":      "logloss",
    "importance_type":  "gain",
    "n_jobs":           -1,
    "random_state":     42,
}

SEASON_WEIGHTS = {
    2026: 3.0,
    2025: 1.5,
}
DEFAULT_WEIGHT = 1.0

FIP_CONSTANT = 3.10

def get_sample_weight(season):
    return SEASON_WEIGHTS.get(int(season), DEFAULT_WEIGHT)

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

def get_last_week_games():
    lv = timezone(timedelta(hours=-7))
    end   = datetime.now(lv)
    start = end - timedelta(days=7)
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
    """
    Returns {era, whip, fip, k9, bb9} for a pitcher's season. FIP is computed
    from raw counting stats: (13*HR + 3*BB - 2*K) / IP + 3.10. Returns None
    if the pitcher has no data or fewer than 1 IP for that season.
    """
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
        ip = parse_ip(s.get("inningsPitched", 0))
        if ip < 1:
            return None
        hr = int(s.get("homeRuns", 0))
        bb = int(s.get("baseOnBalls", 0))
        k  = int(s.get("strikeOuts", 0))
        fip = (13 * hr + 3 * bb - 2 * k) / ip + FIP_CONSTANT
        return {
            "era":  float(s.get("era", 4.50)),
            "whip": float(s.get("whip", 1.30)),
            "fip":  round(fip, 3),
            "k9":   float(s.get("strikeoutsPer9Inn", 8.0)),
            "bb9":  float(s.get("walksPer9Inn", 3.0)),
        }
    except:
        return None

def get_pitcher_hand(player_id):
    """Returns 'L' or 'R' for the pitcher's throwing hand, or None."""
    try:
        data = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}",
            timeout=30
        ).json()
        return data["people"][0].get("pitchHand", {}).get("code")
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

def get_batter_ops(player_id, season, vs_hand=None):
    """
    Season OPS for a batter. If vs_hand ('L' or 'R') is provided, returns
    platoon-split OPS via sitCodes (vl/vr). Falls back to full-season OPS
    if the split is missing or zero (e.g. small sample).
    """
    try:
        if vs_hand in ("L", "R"):
            sit_code = "vl" if vs_hand == "L" else "vr"
            data = requests.get(
                f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
                params={
                    "stats": "statSplits",
                    "season": season,
                    "group": "hitting",
                    "sitCodes": sit_code,
                },
                timeout=30,
            ).json()
            splits = data.get("stats", [{}])[0].get("splits", [])
            if splits:
                ops = float(splits[0]["stat"].get("ops", 0))
                if ops > 0:
                    return ops
            # split missing/zero → fall through to season OPS

        data = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
            params={"stats": "season", "season": season, "group": "hitting"},
            timeout=30,
        ).json()
        splits = data["stats"][0]["splits"]
        if not splits:
            return None
        ops = float(splits[0]["stat"].get("ops", 0))
        return ops if ops > 0 else None
    except:
        return None

def get_lineup_ops(batters, season, vs_hand=None):
    ops_list = []
    for pid in batters[:9]:
        ops = get_batter_ops(pid, season, vs_hand=vs_hand)
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

            # Platoon adjustment — each lineup's OPS is looked up vs the OPPOSING pitcher's hand
            home_pitcher_hand = get_pitcher_hand(home_sp_id)
            away_pitcher_hand = get_pitcher_hand(away_sp_id)
            home_lineup_ops = get_lineup_ops(home_batters, season, vs_hand=away_pitcher_hand)
            away_lineup_ops = get_lineup_ops(away_batters, season, vs_hand=home_pitcher_hand)

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
                "home_fip":  home_p["fip"],
                "home_k9":   home_p["k9"],
                "home_bb9":  home_p["bb9"],
                "away_era":  away_p["era"],
                "away_whip": away_p["whip"],
                "away_fip":  away_p["fip"],
                "away_k9":   away_p["k9"],
                "away_bb9":  away_p["bb9"],
                "home_ops":  home_ops,
                "home_kpct": home_kpct,
                "away_ops":  away_ops,
                "away_kpct": away_kpct,
                "era_diff":  away_p["era"] - home_p["era"],
                "fip_diff":  away_p["fip"] - home_p["fip"],
                "k9_diff":   home_p["k9"]  - away_p["k9"],
                "ops_diff":  home_ops - away_ops,
            })
        except:
            continue

    print(f"Built {len(new_rows)} new training rows")
    return new_rows

def _extract_importances(model):
    """Average XGBoost gain importances across the calibrated CV folds."""
    ests = []
    for cc in getattr(model, "calibrated_classifiers_", []):
        est = getattr(cc, "estimator", None)
        if est is None:
            est = getattr(cc, "base_estimator", None)
        if est is not None and hasattr(est, "feature_importances_"):
            ests.append(est.feature_importances_)
    if not ests:
        return None
    return np.mean(ests, axis=0)

def retrain_model(df):
    print("\nRetraining model (XGBoost + isotonic calibration)...")

    current_season = datetime.now().year

    df["weight"] = df["season"].apply(get_sample_weight)

    X_all   = df[FEATURES]
    y_all   = df["home_win"]
    w_all   = df["weight"]

    test_mask  = df["season"] == current_season
    train_mask = ~test_mask

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

    xgb = XGBClassifier(**XGB_PARAMS)
    model = CalibratedClassifierCV(xgb, method="isotonic", cv=5)
    model.fit(X_train_scaled, y_train, sample_weight=w_train)

    preds = model.predict(X_test_scaled)
    probs = model.predict_proba(X_test_scaled)[:, 1]
    acc   = accuracy_score(y_test, preds)
    brier = brier_score_loss(y_test, probs)

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

    importances = _extract_importances(model)
    if importances is not None:
        print("\n  Feature importance (XGBoost gain, avg across folds):")
        for feat, imp in sorted(zip(FEATURES, importances), key=lambda x: -x[1]):
            bar = "█" * int(imp / max(importances) * 20)
            print(f"    {feat:10s} {imp:.4f}  {bar}")

    with open("model.pkl", "wb") as f:
        pickle.dump(model, f)
    with open("scaler.pkl", "wb") as f:
        pickle.dump(scaler, f)

    print("\n  Model saved!")
    return acc, brier

def run_weekly_retrain():
    print("\n" + "=" * 55)
    print("  WEEKLY MODEL RETRAINING")
    print("=" * 55)
    print(f"  Running: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55 + "\n")

    season = datetime.now().year

    games = get_last_week_games()
    if not games:
        print("No games found — skipping retrain")
        return

    print("\nBuilding new training rows...")
    new_rows = build_new_rows(games, season)
    if not new_rows:
        print("No new rows built — skipping retrain")
        return

    existing_file = "training_data.csv"
    if os.path.exists(existing_file):
        existing_df = pd.read_csv(existing_file)
        print(f"Loaded {len(existing_df)} existing training rows")
    else:
        existing_df = pd.DataFrame()

    new_df = pd.DataFrame(new_rows)
    if not existing_df.empty:
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        if "game_id" in combined.columns:
            combined = combined.drop_duplicates(subset=["game_id"])
    else:
        combined = new_df

    # Safety check — every FEATURES column must be present and non-null.
    # Catches the case where rebuild_features.py wasn't run (missing era/whip/fip).
    missing_cols = [c for c in FEATURES if c not in combined.columns]
    if missing_cols:
        print(f"\n❌ training_data.csv is missing columns: {missing_cols}")
        print("   Run rebuild_features.py first.")
        return
    null_rows = combined[FEATURES].isna().any(axis=1).sum()
    if null_rows > 0:
        print(f"\n❌ {null_rows} rows have nulls in feature columns — run rebuild_features.py first")
        return

    combined.to_csv(existing_file, index=False)
    print(f"Training data updated: {len(combined)} total rows (+{len(new_rows)} new)")

    acc, brier = retrain_model(combined)

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