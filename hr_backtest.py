"""hr_backtest.py — walk-forward backtest of the LONG BALL WATCH formula.

Consumes the point-in-time CSVs built by hr_backtest_data.py and, for every
batter-game since the burn-in date, computes the live model's probability
using ONLY data from before that date, then grades it against what happened.

Reproduces: shrunk batter HR/PA, platoon vs starter hand, starter HR/BF
factor, damped park factor, expected PA. Not reproducible without leakage
in v1: arsenal profiles (need time-split snapshots), weather, book odds.

Reports: calibration by probability bucket, daily top-15 hit rates,
factor ablations (Brier with each factor switched off), and a fitted
damp exponent alpha for the factor stack:

    p_PA = league_rate * (stack / league_rate) ^ alpha

alpha = 1 is the live model; alpha < 1 compresses the tail. The eval is
played-batters-only, i.e. the post-lineup-refresh regime.

Run:  C:\\Users\\Poons\\Model\\.venv\\Scripts\\python.exe hr_backtest.py
"""

import os
import sys

import numpy as np
import pandas as pd

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

EVAL_START = "2026-05-01"
HOLDOUT_START = os.environ.get("PROPS_HOLDOUT_START", "2026-07-01")  # rolling: set by props_retrain.py   # ~5 weeks of burn-in for season-to-date stats
MIN_PA = 100
BATTER_PRIOR = 200
PLATOON_PRIOR = 300
PITCH_PRIOR = 300
STARTER_SHARE = 0.55
PARK_DAMP = 0.5

# Statcast team abbrev -> HR park factor (same table as hr_model.py)
PARK_HR = {
    "CIN": 128, "LAD": 120, "NYY": 117, "PHI": 113, "MIL": 111, "COL": 110,
    "CWS": 110, "HOU": 108, "BAL": 106, "ATL": 105, "LAA": 104, "AZ": 103,
    "ARI": 103, "TEX": 102, "TOR": 102, "CHC": 101, "WSH": 101, "ATH": 100,
    "OAK": 100, "SEA": 99, "MIN": 99, "CLE": 97, "TB": 96, "SD": 96,
    "NYM": 95, "BOS": 92, "DET": 91, "STL": 89, "PIT": 88, "KC": 86,
    "MIA": 84, "SF": 82,
}


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def main():
    bat = pd.read_csv("hr_bt_batters.csv")
    pit = pd.read_csv("hr_bt_pitchers.csv")
    games = pd.read_csv("hr_bt_games.csv").drop_duplicates("game_pk")
    print(f"loaded: {len(bat)} batter-games, {bat['date'].nunique()} days, "
          f"{len(games)} games")

    unmapped = set(games["home_team"]) - set(PARK_HR)
    if unmapped:
        print(f"WARNING unmapped parks (factor 100): {unmapped}")

    # ── prior-to-date cumulatives ────────────────────────────────────────
    daily = (bat.groupby(["batter", "date"])
                .agg(pa_n=("pa_n", "sum"), hr=("hr", "sum"),
                     pa_vl=("pa_vl", "sum"), hr_vl=("hr_vl", "sum"),
                     pa_vr=("pa_vr", "sum"), hr_vr=("hr_vr", "sum"))
                .reset_index().sort_values(["batter", "date"]))
    g = daily.groupby("batter")
    for c in ("pa_n", "hr", "pa_vl", "hr_vl", "pa_vr", "hr_vr"):
        daily[f"c_{c}"] = g[c].cumsum() - daily[c]
    daily["c_g"] = g.cumcount()

    pit = pit.sort_values(["pitcher", "date"])
    gp = pit.groupby("pitcher")
    pit["c_bf"] = gp["bf"].cumsum() - pit["bf"]
    pit["c_hra"] = gp["hr_allowed"].cumsum() - pit["hr_allowed"]

    lg = (daily.groupby("date").agg(pa=("pa_n", "sum"), hr=("hr", "sum"))
               .sort_values("date"))
    lg["c_pa"] = lg["pa"].cumsum() - lg["pa"]
    lg["c_hr"] = lg["hr"].cumsum() - lg["hr"]
    lg["lg_rate"] = (lg["c_hr"] / lg["c_pa"]).fillna(0.03)

    # ── assemble eval rows ───────────────────────────────────────────────
    df = bat.merge(daily[["batter", "date"] + [c for c in daily.columns if c.startswith("c_")]],
                   on=["batter", "date"])
    df = df.merge(games[["game_pk", "home_sp", "home_sp_hand", "away_sp", "away_sp_hand"]],
                  on="game_pk", how="left")
    df["is_home"] = df["bat_team"] == df["home_team"]
    df["opp_sp"] = np.where(df["is_home"], df["away_sp"], df["home_sp"])
    df["sp_hand"] = np.where(df["is_home"], df["away_sp_hand"], df["home_sp_hand"])
    df = df.merge(pit[["pitcher", "date", "c_bf", "c_hra"]],
                  left_on=["opp_sp", "date"], right_on=["pitcher", "date"], how="left")
    df = df.merge(lg[["lg_rate"]], left_on="date", right_index=True)
    df = df[(df["date"] >= EVAL_START) & (df["c_pa_n"] >= MIN_PA)].copy()

    lgr = df["lg_rate"]
    df["bat_rate"] = (df["c_hr"] + BATTER_PRIOR * lgr) / (df["c_pa_n"] + BATTER_PRIOR)
    df["f_bat"] = df["bat_rate"] / lgr

    vs_pa = np.where(df["sp_hand"] == "L", df["c_pa_vl"], df["c_pa_vr"])
    vs_hr = np.where(df["sp_hand"] == "L", df["c_hr_vl"], df["c_hr_vr"])
    split_rate = (vs_hr + PLATOON_PRIOR * df["bat_rate"]) / (vs_pa + PLATOON_PRIOR)
    df["f_platoon"] = (split_rate / df["bat_rate"]).clip(0.8, 1.2)

    shrunk = (df["c_hra"].fillna(0) + PITCH_PRIOR * lgr) / (df["c_bf"].fillna(0) + PITCH_PRIOR)
    df["f_pit"] = STARTER_SHARE * (shrunk / lgr).clip(0.75, 1.35) + (1 - STARTER_SHARE)

    df["f_park"] = 1 + (df["home_team"].map(PARK_HR).fillna(100) - 100) / 100 * PARK_DAMP
    df["exp_pa"] = (df["c_pa_n"] / df["c_g"].clip(lower=1)).clip(3.2, 4.7)
    df["y"] = (df["hr"] > 0).astype(int)

    def game_prob(stack_pa, exp_pa):
        return 1 - (1 - stack_pa.clip(1e-5, 0.5)) ** exp_pa

    df["p_full"] = game_prob(df["bat_rate"] * df["f_platoon"] * df["f_pit"] * df["f_park"], df["exp_pa"])

    n, y = len(df), df["y"].values
    base = y.mean()
    print(f"\neval: {n} batter-games over {df['date'].nunique()} days | "
          f"actual HR rate {base*100:.1f}%")

    # ── calibration ──────────────────────────────────────────────────────
    print("\nCalibration (live formula, alpha=1):")
    edges = [0, .08, .12, .16, .20, 1.0]
    for lo, hi in zip(edges, edges[1:]):
        m = (df["p_full"] >= lo) & (df["p_full"] < hi)
        if m.sum():
            print(f"  p {lo*100:>4.0f}-{hi*100:<4.0f}: n={m.sum():>5}  "
                  f"pred {df.loc[m,'p_full'].mean()*100:5.1f}%  "
                  f"actual {df.loc[m,'y'].mean()*100:5.1f}%")

    # ── daily top-15 ─────────────────────────────────────────────────────
    top = df.sort_values("p_full", ascending=False).groupby("date").head(15)
    tg = top.groupby("date").agg(hits=("y", "sum"), exp=("p_full", "sum"))
    print(f"\nDaily top-15: mean hits {tg['hits'].mean():.2f} vs expected "
          f"{tg['exp'].mean():.2f} | zero-HR days {int((tg['hits']==0).sum())}/{len(tg)}")

    # ── ablations ────────────────────────────────────────────────────────
    print(f"\nBrier x1000 (lower better) | base-rate {brier(np.full(n, base), y)*1000:.3f}")
    variants = {
        "full model": df["bat_rate"] * df["f_platoon"] * df["f_pit"] * df["f_park"],
        "bat only": df["bat_rate"],
        "no platoon": df["bat_rate"] * df["f_pit"] * df["f_park"],
        "no pitcher": df["bat_rate"] * df["f_platoon"] * df["f_park"],
        "no park": df["bat_rate"] * df["f_platoon"] * df["f_pit"],
    }
    for name, stack in variants.items():
        print(f"  {name:<12} {brier(game_prob(stack, df['exp_pa']).values, y)*1000:.3f}")

    # ── fit damp exponent alpha (walk-forward: fit on May-Jun, test Jul+) ─
    print("\nDamp exponent alpha: p_PA = lg * (stack/lg)^alpha")
    stack_pa = (df["bat_rate"] * df["f_platoon"] * df["f_pit"] * df["f_park"])
    ratio = stack_pa / lgr
    fit_m = df["date"] < HOLDOUT_START
    test_m = ~fit_m
    best = None
    for alpha in np.arange(0.3, 1.31, 0.05):
        p = game_prob(lgr * ratio ** alpha, df["exp_pa"])
        b_fit = brier(p[fit_m].values, y[fit_m.values])
        if best is None or b_fit < best[1]:
            best = (alpha, b_fit)
    alpha = best[0]
    p_cal = game_prob(lgr * ratio ** alpha, df["exp_pa"])
    print(f"  fitted on May-Jun: alpha = {alpha:.2f}")
    print(f"  Jul+ holdout Brier x1000: alpha=1 "
          f"{brier(df.loc[test_m,'p_full'].values, y[test_m.values])*1000:.3f}  "
          f"vs alpha={alpha:.2f} {brier(p_cal[test_m].values, y[test_m.values])*1000:.3f}")
    m = test_m & (p_cal >= 0.16)
    m1 = test_m & (df["p_full"] >= 0.16)
    if m1.sum():
        print(f"  Jul+ tail (p>=16%): alpha=1 pred {df.loc[m1,'p_full'].mean()*100:.1f}% "
              f"actual {df.loc[m1,'y'].mean()*100:.1f}% (n={m1.sum()})")
    if m.sum():
        print(f"                     damped pred {p_cal[m].mean()*100:.1f}% "
              f"actual {df.loc[m,'y'].mean()*100:.1f}% (n={m.sum()})")
    top_c = df.assign(pc=p_cal).sort_values("pc", ascending=False).groupby("date").head(15)
    tgc = top_c[top_c["date"] >= HOLDOUT_START].groupby("date").agg(h=("y", "sum"), e=("pc", "sum"))
    tgu = top[top["date"] >= HOLDOUT_START].groupby("date").agg(h=("y", "sum"), e=("p_full", "sum"))
    print(f"  Jul+ top-15/day: alpha=1 hits {tgu['h'].mean():.2f} vs exp {tgu['e'].mean():.2f} | "
          f"damped hits {tgc['h'].mean():.2f} vs exp {tgc['e'].mean():.2f}")

    df.assign(p_cal=p_cal).to_csv("hr_bt_eval.csv", index=False)
    print("\nwrote hr_bt_eval.csv")


if __name__ == "__main__":
    main()
