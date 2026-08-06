"""
skill_estimator_test.py — walk-forward trial: skill-based pitching estimators
(FIP, K-BB) vs the production ERA feature. Boss's hypothesis (2026-08-06):
ERA is backward-looking; estimators should predict better.

House rule: candidates must beat the baseline OUT-OF-SAMPLE to earn a slot.
Same harness as the V2 selection gauntlet: monthly walk-forward, calibrated
logistic regression, identical rows for every config.

Run:  py -3.11 .\\skill_estimator_test.py
"""

import sys
import warnings; warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.preprocessing import StandardScaler

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

MONTHS = ["2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08",
          "2025-09", "2026-04", "2026-05", "2026-06", "2026-07"]
LR_C = 0.5


def add_features(df):
    d = df.copy()
    # production features
    d["era_diff_w"] = d["away_era"].clip(1.5, 8.0) - d["home_era"].clip(1.5, 8.0)
    d["whip_diff_w"] = d["away_whip"].clip(0.8, 2.0) - d["home_whip"].clip(0.8, 2.0)
    d["ops_diff_c"] = (d["home_ops"] - d["away_ops"]).clip(-0.25, 0.25)
    d["kpct_diff"] = d["away_kpct"] - d["home_kpct"]
    # skill-estimator candidates (winsorized to plausible talent ranges)
    d["fip_diff_w"] = d["away_fip"].clip(2.0, 7.0) - d["home_fip"].clip(2.0, 7.0)
    kbb_away = (d["away_k9"] - d["away_bb9"]).clip(-2, 12)
    kbb_home = (d["home_k9"] - d["home_bb9"]).clip(-2, 12)
    d["kbb_diff"] = kbb_home - kbb_away   # positive favors home, like era_diff_w
    return d


CONFIGS = {
    "BASELINE (era)":        ["era_diff_w", "whip_diff_w", "ops_diff_c", "kpct_diff"],
    "FIP swap (era->fip)":   ["fip_diff_w", "whip_diff_w", "ops_diff_c", "kpct_diff"],
    "ERA + FIP":             ["era_diff_w", "fip_diff_w", "whip_diff_w", "ops_diff_c", "kpct_diff"],
    "KBB swap (era->k-bb)":  ["kbb_diff", "whip_diff_w", "ops_diff_c", "kpct_diff"],
    "ERA + KBB":             ["era_diff_w", "kbb_diff", "whip_diff_w", "ops_diff_c", "kpct_diff"],
    "FIP + KBB (no era)":    ["fip_diff_w", "kbb_diff", "whip_diff_w", "ops_diff_c", "kpct_diff"],
}


def main():
    df = pd.read_csv("training_data.csv")
    df = add_features(df).sort_values(["date", "game_id"]).reset_index(drop=True)
    needed = sorted({c for cols in CONFIGS.values() for c in cols})
    df = df.dropna(subset=needed + ["home_win"]).reset_index(drop=True)
    print(f"{len(df)} rows | months {MONTHS[0]}..{MONTHS[-1]}\n")

    print(f"{'CONFIG':<24}{'n':>6}{'acc':>8}{'brier':>9}{'logloss':>9}")
    results = {}
    for name, cols in CONFIGS.items():
        preds, ys = [], []
        for mth in MONTHS:
            tr = df[df["date"] < mth + "-01"]
            te = df[df["date"].str[:7] == mth]
            if len(te) == 0 or len(tr) < 2000:
                continue
            sc = StandardScaler()
            m = CalibratedClassifierCV(LogisticRegression(max_iter=1000, C=LR_C), cv=5)
            m.fit(sc.fit_transform(tr[cols]), tr["home_win"])
            p = m.predict_proba(sc.transform(te[cols]))[:, 1]
            preds.extend(p)
            ys.extend(te["home_win"].tolist())
        preds = np.clip(np.array(preds), 1e-6, 1 - 1e-6)
        ys = np.array(ys)
        acc = float(((preds > 0.5) == ys).mean())
        br = brier_score_loss(ys, preds)
        ll = log_loss(ys, preds)
        results[name] = (acc, br, ll)
        print(f"{name:<24}{len(ys):>6}{acc:>8.4f}{br:>9.4f}{ll:>9.4f}")

    base = results["BASELINE (era)"]
    print("\nvs baseline (negative brier delta = better):")
    for name, (acc, br, ll) in results.items():
        if name == "BASELINE (era)":
            continue
        print(f"  {name:<24} d_acc {acc-base[0]:+.4f}   d_brier {br-base[1]:+.5f}")


if __name__ == "__main__":
    main()
