"""
train_model_v2.py — trains the V2 model on training_data.csv.

Changes vs the old retrain:
  1. TRAINS ON ALL ROWS, including the current season. The old code
     excluded every current-season row from training the moment 50+
     existed (test_mask/train_mask split), which also made the
     "2026 weighted 3x" log line dead code — the weight was never applied.
  2. 4-feature calibrated logistic regression (see features_v2.py for why).
  3. Honest validation: walk-forward by month instead of scoring a test
     set whose features contain look-ahead. The printed number is what
     the model would actually have done betting forward in time.
  4. No park factor / bullpen / home-boost layers anywhere. The model's
     intercept already carries home-field advantage (~52.2% base rate),
     and park effects already live inside season pitcher/lineup stats.

Run:  py -3.11 .\\train_model_v2.py
"""

import warnings; warnings.filterwarnings("ignore")
import pickle
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss

from features_v2 import FEATURES_V2, add_v2_features, MODEL_FILE, SCALER_FILE

LR_C = 0.5  # regularization — validated vs C=1.0 (identical) and heavier sets


def make_model():
    return CalibratedClassifierCV(
        LogisticRegression(max_iter=1000, C=LR_C), cv=5
    )


def walk_forward_report(df, min_train=2000, min_test=30):
    """Monthly walk-forward over the last two seasons. Every prediction is
    made by a model that never saw that month. This is the honest number."""
    df = df.sort_values(["date", "game_id"]).reset_index(drop=True)
    df["ym"] = df["date"].str[:7]
    recent_seasons = sorted(df["season"].unique())[-2:]
    months = sorted(df[df["season"].isin(recent_seasons)]["ym"].unique())

    rows = []
    for mth in months:
        tr = df[df["date"] < mth + "-01"]
        te = df[df["ym"] == mth]
        if len(te) < min_test or len(tr) < min_train:
            continue
        sc = StandardScaler()
        m = make_model()
        m.fit(sc.fit_transform(tr[FEATURES_V2]), tr["home_win"])
        p = m.predict_proba(sc.transform(te[FEATURES_V2]))[:, 1]
        rows.append({
            "month": mth, "n": len(te),
            "acc":   accuracy_score(te["home_win"], p > 0.5),
            "brier": brier_score_loss(te["home_win"], p),
            "ll":    log_loss(te["home_win"], np.clip(p, 1e-6, 1 - 1e-6)),
        })
    return pd.DataFrame(rows)


def train_final(df):
    """Fit production model on every row (walk-forward above is the report;
    the deployed model should use all available information)."""
    sc = StandardScaler()
    X = sc.fit_transform(df[FEATURES_V2])
    m = make_model()
    m.fit(X, df["home_win"])
    with open(MODEL_FILE, "wb") as f:
        pickle.dump(m, f)
    with open(SCALER_FILE, "wb") as f:
        pickle.dump(sc, f)
    return m, sc


def main():
    df = pd.read_csv("training_data.csv")
    df = add_v2_features(df)
    print(f"Training rows: {len(df)}  (seasons: {sorted(df['season'].unique())})")
    print(f"Base home win rate: {df['home_win'].mean():.4f}")

    print("\nWalk-forward validation (honest out-of-sample):")
    wf = walk_forward_report(df)
    print(wf.round(4).to_string(index=False))
    wacc = np.average(wf["acc"], weights=wf["n"])
    wbr  = np.average(wf["brier"], weights=wf["n"])
    print(f"\n  Weighted mean: acc={wacc:.4f}  brier={wbr:.4f}")
    print("  (Old 18-feature XGBoost on the same protocol: acc=0.5874 brier=0.2372)")

    print("\nFitting final model on all rows...")
    train_final(df)

    # interpretability — this model is 4 numbers + an intercept
    lr = LogisticRegression(max_iter=1000, C=LR_C)
    sc = StandardScaler()
    lr.fit(sc.fit_transform(df[FEATURES_V2]), df["home_win"])
    print("\nStandardized coefficients:")
    for f, c in zip(FEATURES_V2, lr.coef_[0]):
        print(f"  {f:12s} {c:+.4f}")
    print(f"  intercept    {lr.intercept_[0]:+.4f}  (home-field advantage)")

    print(f"\nSaved {MODEL_FILE} + {SCALER_FILE}")
    return wacc, wbr


if __name__ == "__main__":
    main()
