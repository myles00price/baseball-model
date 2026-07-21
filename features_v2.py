"""
features_v2.py — single source of truth for the V2 feature set.

Both training (weekly_retrain_v2.py) and inference (master.py) import from
here so the feature definition can never drift between the two again.

V2 feature set (4 features, chosen by walk-forward validation over
2025-03 → 2026-06, 3,187 out-of-sample games):

    era_diff_w   = clip(away_era, 1.5, 8.0)  - clip(home_era, 1.5, 8.0)
    whip_diff_w  = clip(away_whip, 0.8, 2.0) - clip(home_whip, 0.8, 2.0)
    ops_diff_c   = clip(home_ops - away_ops, -0.25, 0.25)
    kpct_diff    = away_kpct - home_kpct

Why winsorized (clipped): a starter with 2 IP and a 27.00 ERA was feeding
raw 27.0 into the model. Clipping bounds every pitcher stat to a plausible
talent range so small samples can't blow up a prediction.

Why only 4: permutation importance on the 18-feature XGBoost showed
era_diff was the only feature with clearly positive out-of-sample signal;
13 of 18 features actively hurt held-out log loss. The 4 kept features are
the de-correlated survivors. Walk-forward: 60.2% acc / 0.2325 Brier vs
58.7% / 0.2372 for the old 18-feature XGBoost.

Model: LogisticRegression(C=0.5) + 5-fold calibration wrapper, trained on
ALL rows including the current season (the old pipeline silently excluded
the current season from training — see weekly_retrain_v2.py).
"""

import pickle
import numpy as np

FEATURES_V2 = ["era_diff_w", "whip_diff_w", "ops_diff_c", "kpct_diff"]

MODEL_FILE  = "model_v2.pkl"
SCALER_FILE = "scaler_v2.pkl"

# Winsorization bounds — plausible single-season talent ranges
ERA_LO, ERA_HI   = 1.5, 8.0
WHIP_LO, WHIP_HI = 0.8, 2.0
OPS_DIFF_CAP     = 0.25

# Safety clamp on output probability. Wide on purpose: the model is
# calibrated, so this only catches pathological inputs, it is not a
# tuning knob. (Old pipeline clamped 30-70 and clipped 12.9% of preds.)
PROB_LO, PROB_HI = 0.22, 0.78

# ── BET window — single source of truth ─────────────────────────────────
# Edge sign convention: edge = model_prob - implied_prob (both 0-100 scale,
# vig included). Positive = value on that side. The window is applied to the
# SIGNED edge of each side independently; a game's BET flag can therefore
# belong to the value side, which is NOT always the side the model picks to
# win (value-dog bets). Graders and notifications must use flagged_side(),
# never assume the flag means "bet the model's pick".
BET_MIN, BET_MAX = 3.0, 8.0


def is_bet(edge):
    """True iff a SIGNED edge sits inside the bet window [BET_MIN, BET_MAX]."""
    return edge is not None and BET_MIN <= edge <= BET_MAX


def flagged_side(row):
    """Which side of a picks-CSV row carries the BET flag: 'away', 'home',
    or None. Reads the per-book edge strings, which embed ' ** BET **' at
    flag time — the authoritative record of which side was bet."""
    away_flagged = "BET" in str(row.get("DK Edge Away", "")) + str(row.get("MGM Edge Away", ""))
    home_flagged = "BET" in str(row.get("DK Edge Home", "")) + str(row.get("MGM Edge Home", ""))
    if away_flagged:
        return "away"
    if home_flagged:
        return "home"
    return None


def add_v2_features(df):
    """Add V2 feature columns to a training dataframe in place-safe copy."""
    d = df.copy()
    d["era_diff_w"]  = d["away_era"].clip(ERA_LO, ERA_HI)   - d["home_era"].clip(ERA_LO, ERA_HI)
    d["whip_diff_w"] = d["away_whip"].clip(WHIP_LO, WHIP_HI) - d["home_whip"].clip(WHIP_LO, WHIP_HI)
    d["ops_diff_c"]  = (d["home_ops"] - d["away_ops"]).clip(-OPS_DIFF_CAP, OPS_DIFF_CAP)
    d["kpct_diff"]   = d["away_kpct"] - d["home_kpct"]
    return d


def build_feature_vector(home_era, home_whip, away_era, away_whip,
                         home_ops, home_kpct, away_ops, away_kpct):
    """Build the 4-feature vector for a single game at inference time.

    home_ops / away_ops: the OFFENSIVE strength of that team's lineup
    (platoon-adjusted vs the OPPOSING starter's hand when confirmed,
    team season OPS otherwise). Same convention as training data.
    """
    era_diff_w  = min(max(away_era, ERA_LO), ERA_HI) - min(max(home_era, ERA_LO), ERA_HI)
    whip_diff_w = min(max(away_whip, WHIP_LO), WHIP_HI) - min(max(home_whip, WHIP_LO), WHIP_HI)
    ops_diff_c  = max(-OPS_DIFF_CAP, min(OPS_DIFF_CAP, home_ops - away_ops))
    kpct_diff   = away_kpct - home_kpct
    return np.array([[era_diff_w, whip_diff_w, ops_diff_c, kpct_diff]])


_model_cache = {}

def load_model_v2():
    """Load model + scaler once and cache (old code re-loaded every game)."""
    if "m" not in _model_cache:
        with open(MODEL_FILE, "rb") as f:
            _model_cache["m"] = pickle.load(f)
        with open(SCALER_FILE, "rb") as f:
            _model_cache["s"] = pickle.load(f)
    return _model_cache["m"], _model_cache["s"]


def predict_home_win_prob_v2(home_era, home_whip, away_era, away_whip,
                             home_ops, home_kpct, away_ops, away_kpct):
    """Home win probability, 0-100 scale. Calibrated — do NOT add post-hoc
    adjustments (park factor, home boost, bullpen nudges) on top of this.
    Those layers cost the old pipeline ~4 pts of pick accuracy."""
    model, scaler = load_model_v2()
    X = build_feature_vector(home_era, home_whip, away_era, away_whip,
                             home_ops, home_kpct, away_ops, away_kpct)
    p = model.predict_proba(scaler.transform(X))[0][1]
    p = max(PROB_LO, min(PROB_HI, p))
    return round(p * 100, 1)
