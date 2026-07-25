"""
blend_test.py — walk-forward test of market-blended probabilities.

Question: does shrinking V2's probability toward the (de-vigged) market
improve calibration and betting P&L — especially by deflating the
overconfident big-edge zone?

Method (all out-of-sample):
  1. For each month Apr-Jul 2026, train the exact V2 model (calibrated LR,
     features_v2) on all training rows BEFORE that month; predict the month.
  2. Join predictions to stored DK odds from the picks CSVs.
  3. Blend: p = w*model + (1-w)*devig_market for w in 0..1.
  4. Score log loss / Brier, and simulate betting the 3-8% de-vig window
     at DK odds. The "adaptive" row picks each month's w from prior months
     only — the deployable version of the idea.

Run:  py -3.11 .\\blend_test.py
"""

import csv
import sys
import warnings; warnings.filterwarnings("ignore")
from glob import glob

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, log_loss

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from features_v2 import FEATURES_V2, add_v2_features, BET_MIN, BET_MAX

LR_C = 0.5
MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07"]
WEIGHTS = [round(w, 1) for w in np.arange(0.0, 1.01, 0.1)]


def implied(o):
    o = float(o)
    return (-o) / (-o + 100) * 100 if o < 0 else 100 / (o + 100) * 100


def payout(o):
    o = float(o)
    return o if o > 0 else 10000.0 / abs(o)


def load_odds():
    """(date, away, home) -> (dk_away, dk_home) from picks CSVs."""
    odds = {}
    for f in sorted(glob("picks_2026-*.csv")):
        for row in csv.DictReader(open(f, encoding="utf-8-sig")):
            try:
                odds[(row["Date"], row["Away"], row["Home"])] = (
                    float(row["DK Away Odds"]), float(row["DK Home Odds"]))
            except (ValueError, TypeError, KeyError):
                continue
    return odds


def main():
    df = pd.read_csv("training_data.csv")
    df = add_v2_features(df).sort_values(["date", "game_id"]).reset_index(drop=True)
    odds = load_odds()

    rows = []  # one per scored game: month, p_model, p_market, outcome, odds
    for mth in MONTHS:
        tr = df[df["date"] < mth + "-01"]
        te = df[df["date"].str[:7] == mth]
        if len(te) == 0 or len(tr) < 2000:
            continue
        sc = StandardScaler()
        m = CalibratedClassifierCV(LogisticRegression(max_iter=1000, C=LR_C), cv=5)
        m.fit(sc.fit_transform(tr[FEATURES_V2]), tr["home_win"])
        p = m.predict_proba(sc.transform(te[FEATURES_V2]))[:, 1]
        for prob, (_, g) in zip(p, te.iterrows()):
            key = (g["date"], g["away_team"], g["home_team"])
            if key not in odds:
                continue
            ao, ho = odds[key]
            ia, ih = implied(ao), implied(ho)
            mkt = ih / (ia + ih)  # de-vigged home probability (0-1)
            rows.append({"month": mth, "pm": prob, "mk": mkt,
                         "y": int(g["home_win"]), "ao": ao, "ho": ho})

    d = pd.DataFrame(rows)
    print(f"Joined {len(d)} games with odds + walk-forward V2 probs "
          f"({', '.join(sorted(d['month'].unique()))})\n")

    def bet_sim(p_home):
        """3-8% de-vig window at DK odds, both sides."""
        n = w = 0; pnl = 0.0
        for p, row in zip(p_home, d.itertuples()):
            ia, ih = implied(row.ao), implied(row.ho)
            tot = ia + ih
            dva, dvh = ia / tot * 100, ih / tot * 100
            eh = p * 100 - dvh
            ea = (1 - p) * 100 - dva
            if BET_MIN <= eh <= BET_MAX:
                n += 1; won = row.y == 1
            elif BET_MIN <= ea <= BET_MAX:
                n += 1; won = row.y == 0
            else:
                continue
            o = row.ho if BET_MIN <= eh <= BET_MAX else row.ao
            w += won; pnl += payout(o) if won else -100.0
        return n, w, pnl

    print(f"{'w(model)':>8} {'logloss':>8} {'brier':>7} {'bets':>5} {'record':>8} {'P&L':>9} {'ROI':>7}")
    scores = {}
    for wt in WEIGHTS:
        p = wt * d["pm"] + (1 - wt) * d["mk"]
        ll = log_loss(d["y"], np.clip(p, 1e-6, 1 - 1e-6))
        br = brier_score_loss(d["y"], p)
        n, wins, pnl = bet_sim(p)
        scores[wt] = ll
        rec = f"{wins}-{n-wins}" if n else "-"
        roi = f"{pnl/(n*100)*100:+.1f}%" if n else "-"
        print(f"{wt:>8} {ll:>8.4f} {br:>7.4f} {n:>5} {rec:>8} {pnl:>+9.0f} {roi:>7}")

    # Adaptive: pick each month's w from PRIOR months' log loss only
    adap_p = []
    for i, mth in enumerate(MONTHS):
        prior = d[d["month"] < mth]
        cur = d[d["month"] == mth]
        if len(cur) == 0:
            continue
        if len(prior) < 50:
            w_best = 0.5
        else:
            w_best = min(WEIGHTS, key=lambda wt: log_loss(
                prior["y"], np.clip(wt * prior["pm"] + (1 - wt) * prior["mk"], 1e-6, 1 - 1e-6)))
        adap_p.append((cur.index, w_best, wt))
    p_adaptive = d["pm"].copy()
    used = []
    for idx, w_best, _ in adap_p:
        p_adaptive.loc[idx] = w_best * d.loc[idx, "pm"] + (1 - w_best) * d.loc[idx, "mk"]
        used.append(str(w_best))
    ll = log_loss(d["y"], np.clip(p_adaptive, 1e-6, 1 - 1e-6))
    br = brier_score_loss(d["y"], p_adaptive)
    n, wins, pnl = bet_sim(p_adaptive)
    print(f"\nadaptive (monthly w from prior months: {', '.join(used)}):")
    print(f"  logloss {ll:.4f}  brier {br:.4f}  bets {n}  record {wins}-{n-wins}  "
          f"P&L {pnl:+.0f}  ROI {pnl/(n*100)*100 if n else 0:+.1f}%")


if __name__ == "__main__":
    main()
