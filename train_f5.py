"""
train_f5.py — trains the F5 head: same 4 features as V2, target = first-5-
innings winner (ties dropped, so the output is P(home leads after 5 | not
tied) — the right probability for F5 moneylines, which push on ties).

SHADOW ONLY. This model never places or texts a play; its flags are logged
in the picks CSVs and graded nightly so the F5 market idea can prove or
hang itself on a live sample, same as the de-vig shadow.

Run:  py -3.11 .\\train_f5.py    (run f5_backfill.py first)
"""

import warnings; warnings.filterwarnings("ignore")
import pickle
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from features_v2 import FEATURES_V2, add_v2_features

F5_MODEL_FILE = "model_f5.pkl"
F5_SCALER_FILE = "scaler_f5.pkl"
LR_C = 0.5


def make_model():
    return CalibratedClassifierCV(LogisticRegression(max_iter=1000, C=LR_C), cv=5)


def walk_forward_report(df, min_train=2000, min_test=30):
    df = df.sort_values(["date", "game_id"]).reset_index(drop=True)
    df["ym"] = df["date"].str[:7]
    recent = sorted(df["season"].unique())[-2:]
    months = sorted(df[df["season"].isin(recent)]["ym"].unique())
    rows = []
    for mth in months:
        tr = df[df["date"] < mth + "-01"]
        te = df[df["ym"] == mth]
        if len(te) < min_test or len(tr) < min_train:
            continue
        sc = StandardScaler()
        m = make_model()
        m.fit(sc.fit_transform(tr[FEATURES_V2]), tr["f5_home_win"])
        p = m.predict_proba(sc.transform(te[FEATURES_V2]))[:, 1]
        rows.append({"month": mth, "n": len(te),
                     "acc": accuracy_score(te["f5_home_win"], p > 0.5),
                     "brier": brier_score_loss(te["f5_home_win"], p),
                     "ll": log_loss(te["f5_home_win"], np.clip(p, 1e-6, 1 - 1e-6))})
    return pd.DataFrame(rows)


def main():
    df = pd.read_csv("training_data.csv")
    f5 = pd.read_csv("f5_outcomes.csv")
    f5 = f5[f5["f5_home_win"].notna() & (f5["f5_home_win"] != "")]
    f5["game_id"] = f5["game_id"].astype(int)
    df = df.merge(f5[["game_id", "f5_home_win"]], on="game_id", how="inner")
    df["f5_home_win"] = df["f5_home_win"].astype(int)
    df = add_v2_features(df)
    print(f"F5 training rows (ties dropped): {len(df)}")
    print(f"Base F5 home lead rate: {df['f5_home_win'].mean():.4f}")

    print("\nWalk-forward validation (honest out-of-sample):")
    wf = walk_forward_report(df)
    print(wf.round(4).to_string(index=False))
    wacc = np.average(wf["acc"], weights=wf["n"])
    wbr = np.average(wf["brier"], weights=wf["n"])
    print(f"\n  Weighted mean: acc={wacc:.4f}  brier={wbr:.4f}")

    sc = StandardScaler()
    X = sc.fit_transform(df[FEATURES_V2])
    m = make_model()
    m.fit(X, df["f5_home_win"])
    with open(F5_MODEL_FILE, "wb") as f:
        pickle.dump(m, f)
    with open(F5_SCALER_FILE, "wb") as f:
        pickle.dump(sc, f)
    print(f"\nSaved {F5_MODEL_FILE} + {F5_SCALER_FILE}")
    return wacc, wbr


if __name__ == "__main__":
    main()
