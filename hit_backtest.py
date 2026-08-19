"""hit_backtest.py — walk-forward backtest of the hit-model formula.

Consumes the point-in-time CSVs built by hit_backtest_data.py and, for
every batter-game since the burn-in date, computes P(1+ hit) using ONLY
data from before that date, then grades it against the boxscore.

Formula under test (same shape as the HR watch):

    h_PA   = shrunk batter H/PA × starter H/BF factor × park factor
    P(1+)  = 1 - (1 - h_PA) ^ n_eff

Where the HR model plugs expected PA straight into the exponent, hits
can't: 15% of starter-games end with <=2 PA (subs, early exits, ejections)
and PA is endogenous (more hits -> more trips), so a point expected-PA
overstates P(1+ hit) by 3-6 pts. n_eff is therefore an EFFECTIVE PA:
  - morning regime (no lineups):     n_eff = k × season PA/G, k fitted
  - refresh regime (lineups posted): n_eff = k × (w·slot-mean PA +
    (1-w)·season PA/G) — a batter's own PA/G beats his slot outright
    (it also carries sub/pinch-hit tendency); a 25% slot blend is the
    best holdout. Per-slot free-fitted n_eff is reported for reference.

Reports: calibration by bucket in both regimes, factor ablations, prior
sweeps, fit vs holdout Brier, daily top-15, P(2+ hits) as a side check.

Run:  C:\\Users\\Poons\\Model\\.venv\\Scripts\\python.exe hit_backtest.py
"""

import json
import os
import sys

import numpy as np
import pandas as pd

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

EVAL_START = "2026-05-01"   # ~5 weeks burn-in for season-to-date stats
HOLDOUT_START = os.environ.get("PROPS_HOLDOUT_START", "2026-07-01")  # rolling: set by props_retrain.py
MIN_PA = 100
BATTER_PRIOR = 400            # 2026-08-16 sweep: 300-600 flat, 400 slightly better tail
PITCH_PRIOR = 300
STARTER_SHARE = 0.55
PARK_DAMP = 0.5
PIT_LO, PIT_HI = 0.80, 1.25

# Approximate multi-year HITS park factors (100 = neutral), Statcast abbrevs.
# Hits factors are far more compressed than HR factors; Coors is the only
# big one. Damped by PARK_DAMP like the HR table.
PARK_H = {
    "COL": 114, "BOS": 106, "KC": 104, "CIN": 103, "AZ": 103, "ARI": 103,
    "TEX": 102, "MIA": 102, "PIT": 102, "LAA": 101, "TOR": 101, "BAL": 101,
    "MIN": 101, "PHI": 100, "CWS": 100, "ATL": 100, "WSH": 100, "CHC": 100,
    "MIL": 100, "STL": 99, "HOU": 99, "DET": 99, "TB": 98, "SD": 98,
    "NYY": 98, "LAD": 98, "CLE": 98, "SF": 97, "SEA": 96, "NYM": 97,
    "ATH": 100, "OAK": 99,
}


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def game_prob(h_pa, n):
    return 1 - (1 - np.clip(h_pa, 1e-4, 0.8)) ** n


def prob_2plus(h_pa, n):
    q = np.clip(h_pa, 1e-4, 0.8)
    p0 = (1 - q) ** n
    p1 = n * q * (1 - q) ** (n - 1)
    return np.clip(1 - p0 - p1, 0, 1)


def calib(p, y, edges, label):
    print(f"\nCalibration — {label}:")
    for lo, hi in zip(edges, edges[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum():
            print(f"  p {lo*100:>4.0f}-{hi*100:<4.0f}: n={int(m.sum()):>5}  "
                  f"pred {p[m].mean()*100:5.1f}%  actual {y[m].mean()*100:5.1f}%")


def fit_scalar(h_pa, base_n, y, grid):
    best = None
    for k in grid:
        b = brier(game_prob(h_pa, base_n * k), y)
        if best is None or b < best[1]:
            best = (k, b)
    return best[0]


def main():
    bat = pd.read_csv("hit_bt_batters.csv")
    pit = pd.read_csv("hit_bt_pitchers.csv")
    games = pd.read_csv("hit_bt_games.csv").drop_duplicates("game_pk")
    print(f"loaded: {len(bat)} batter-games, {bat['date'].nunique()} days, {len(games)} games")
    unmapped = set(games["home_team"]) - set(PARK_H)
    if unmapped:
        print(f"WARNING unmapped parks (factor 100): {unmapped}")

    # ── prior-to-date cumulatives ────────────────────────────────────────
    daily = (bat.groupby(["batter", "date"])
                .agg(pa=("pa", "sum"), ab=("ab", "sum"), h=("h", "sum"),
                     so=("so", "sum"), bb=("bb", "sum"))
                .reset_index().sort_values(["batter", "date"]))
    g = daily.groupby("batter")
    for c in ("pa", "ab", "h", "so", "bb"):
        daily[f"c_{c}"] = g[c].cumsum() - daily[c]
    daily["c_g"] = g.cumcount()
    daily["c_h15"] = g["h"].transform(lambda s: s.shift(1).rolling(15, min_periods=1).sum())
    daily["c_pa15"] = g["pa"].transform(lambda s: s.shift(1).rolling(15, min_periods=1).sum())

    pit = pit.sort_values(["pitcher", "date"])
    gp = pit.groupby("pitcher")
    pit["c_bf"] = gp["bf"].cumsum() - pit["bf"]
    pit["c_ha"] = gp["h_allowed"].cumsum() - pit["h_allowed"]
    pit["c_pso"] = gp["so"].cumsum() - pit["so"]

    lg = daily.groupby("date").agg(pa=("pa", "sum"), h=("h", "sum")).sort_values("date")
    lg["c_pa"] = lg["pa"].cumsum() - lg["pa"]
    lg["c_h"] = lg["h"].cumsum() - lg["h"]
    lg["lg_rate"] = (lg["c_h"] / lg["c_pa"]).fillna(0.22)

    pk_day = bat.groupby(["home_team", "date"]).agg(pa=("pa", "sum"), h=("h", "sum")).reset_index()
    pk_day = pk_day.sort_values(["home_team", "date"])
    gk = pk_day.groupby("home_team")
    pk_day["pk_pa"] = gk["pa"].cumsum() - pk_day["pa"]
    pk_day["pk_h"] = gk["h"].cumsum() - pk_day["h"]

    # ── assemble eval rows ───────────────────────────────────────────────
    cols = ["batter", "date"] + [c for c in daily.columns if c.startswith("c_")]
    df = bat.merge(daily[cols], on=["batter", "date"])
    df = df.merge(games[["game_pk", "home_sp", "home_sp_hand", "away_sp", "away_sp_hand"]],
                  on="game_pk", how="left")
    df["opp_sp"] = np.where(df["is_home"] == 1, df["away_sp"], df["home_sp"])
    df["sp_hand"] = np.where(df["is_home"] == 1, df["away_sp_hand"], df["home_sp_hand"])
    df = df.merge(pit[["pitcher", "date", "c_bf", "c_ha", "c_pso"]],
                  left_on=["opp_sp", "date"], right_on=["pitcher", "date"], how="left")
    df = df.merge(lg[["lg_rate"]], left_on="date", right_index=True)
    df = df.merge(pk_day[["home_team", "date", "pk_pa", "pk_h"]], on=["home_team", "date"], how="left")
    df = df[(df["date"] >= EVAL_START) & (df["c_pa"] >= MIN_PA) & (df["slot"] > 0)].copy()
    df = df.reset_index(drop=True)

    lgr = df["lg_rate"].values
    df["bat_rate"] = (df["c_h"] + BATTER_PRIOR * lgr) / (df["c_pa"] + BATTER_PRIOR)
    df["f_bat"] = df["bat_rate"] / lgr
    shrunk = (df["c_ha"].fillna(0) + PITCH_PRIOR * lgr) / (df["c_bf"].fillna(0) + PITCH_PRIOR)
    df["f_pit_raw"] = (shrunk / lgr).clip(PIT_LO, PIT_HI)
    df["f_pit"] = STARTER_SHARE * df["f_pit_raw"] + (1 - STARTER_SHARE)
    df["f_park"] = 1 + (df["home_team"].map(PARK_H).fillna(100) - 100) / 100 * PARK_DAMP
    emp = (df["pk_h"].fillna(0) + 3000 * lgr) / (df["pk_pa"].fillna(0) + 3000)
    df["f_park_emp"] = (emp / lgr).clip(0.9, 1.15)
    df["pa_g"] = (df["c_pa"] / df["c_g"].clip(lower=1)).clip(2.0, 5.0)
    df["y"] = (df["h"] > 0).astype(int)
    df["y2"] = (df["h"] > 1).astype(int)
    n, y, y2 = len(df), df["y"].values, df["y2"].values
    fit_m = (df["date"] < HOLDOUT_START).values
    test_m = ~fit_m
    base = y.mean()
    print(f"\neval: {n} batter-games over {df['date'].nunique()} days | "
          f"actual 1+ hit rate {base*100:.1f}% | 2+ hits {y2.mean()*100:.1f}% | "
          f"fit rows {fit_m.sum()} / holdout rows {test_m.sum()}")
    print("\nActual PA per starter-game by slot (why a raw expected-PA runs hot):")
    print("  " + "  ".join(f"{s}:{v:.2f}" for s, v in df.groupby("slot")["pa"].mean().items()))
    print(f"  share of starter-games with <=2 PA: {(df['pa'] <= 2).mean()*100:.1f}%")

    stack = (df["bat_rate"] * df["f_pit"] * df["f_park"]).values

    # ── effective PA: per-slot (refresh regime), fitted on fit window ────
    slot = df["slot"].clip(1, 9).values
    eff_slot = {}
    grid = np.arange(2.0, 5.01, 0.05)
    for s in range(1, 10):
        m = fit_m & (slot == s)
        eff_slot[s] = float(fit_scalar(stack[m], np.ones(m.sum()), y[m], grid))
    n_slot = np.array([eff_slot[s] for s in slot])
    print("\nEffective PA by slot (fitted May-Jun): "
          + "  ".join(f"{s}:{v:.2f}" for s, v in eff_slot.items()))
    # optional batter-specific tilt: n = eff_slot × (pa_g / slot-mean pa_g)^gamma
    slot_pag = df.groupby("slot")["pa_g"].transform("mean").values
    tilt = (df["pa_g"].values / slot_pag)
    best_g = None
    for gam in np.arange(0.0, 1.51, 0.1):
        b = brier(game_prob(stack[fit_m], (n_slot * tilt ** gam)[fit_m]), y[fit_m])
        if best_g is None or b < best_g[1]:
            best_g = (gam, b)
    gamma = best_g[0]
    n_slot_t = n_slot * tilt ** gamma
    print(f"Batter PA/G tilt exponent gamma (fit): {gamma:.1f} | holdout Brier x1000 "
          f"slot-only {brier(game_prob(stack[test_m], n_slot[test_m]), y[test_m])*1000:.2f} vs "
          f"tilted {brier(game_prob(stack[test_m], n_slot_t[test_m]), y[test_m])*1000:.2f}")

    # ── effective PA: morning regime, k × season PA/G ────────────────────
    k = fit_scalar(stack[fit_m], df["pa_g"].values[fit_m], y[fit_m], np.arange(0.6, 1.21, 0.01))
    n_morn = df["pa_g"].values * k
    print(f"Morning regime: n_eff = {k:.2f} × season PA/G")
    slot_mean = df[fit_m].groupby("slot")["pa"].mean()
    sm = df["slot"].map(slot_mean).values
    print("Mean actual PA by slot (fit window): "
          + "  ".join(f"{int(s_)}:{v:.2f}" for s_, v in slot_mean.items()))
    print("Refresh regime blend n_eff = k × (w·slot-mean PA + (1-w)·PA/G) — Brier x1000 fit / holdout:")
    blend = {}
    for w in (0.0, 0.25, 0.5, 0.75, 1.0):
        base_n = w * sm + (1 - w) * df["pa_g"].values
        kw = fit_scalar(stack[fit_m], base_n[fit_m], y[fit_m], np.arange(0.7, 1.21, 0.01))
        pw = game_prob(stack, base_n * kw)
        blend[w] = (kw, brier(pw[fit_m], y[fit_m]) * 1000, brier(pw[test_m], y[test_m]) * 1000)
        print(f"  w={w:<4} k={kw:.2f}: {blend[w][1]:7.2f} / {blend[w][2]:7.2f}")
    W_SLOT = 0.25
    k_blend = blend[W_SLOT][0]
    n_blend = (W_SLOT * sm + (1 - W_SLOT) * df["pa_g"].values) * k_blend
    p_blend = game_prob(stack, n_blend)

    p_slot = game_prob(stack, n_slot)
    p_slot_t = game_prob(stack, n_slot_t)
    p_morn = game_prob(stack, n_morn)
    edges = [0, .45, .5, .55, .6, .65, .7, .75, 1.01]
    calib(p_morn[test_m], y[test_m], edges, "HOLDOUT, morning regime (k × season PA/G)")
    calib(p_slot[test_m], y[test_m], edges, "HOLDOUT, refresh regime (effective PA by slot)")
    calib(p_blend[test_m], y[test_m], edges, "HOLDOUT, refresh regime CHOSEN: 25% slot / 75% PA/G blend")
    calib(prob_2plus(stack, n_slot)[test_m], y2[test_m], [0, .1, .15, .2, .25, .3, 1.01],
          "HOLDOUT, P(2+ hits) with slot effective PA")

    # ── ablations under the fitted effective PA ─────────────────────────
    def report(name, h_pa, nn):
        p = game_prob(h_pa, nn)
        print(f"  {name:<30} all {brier(p, y)*1000:7.2f}   fit {brier(p[fit_m], y[fit_m])*1000:7.2f}"
              f"   holdout {brier(p[test_m], y[test_m])*1000:7.2f}")

    print(f"\nBrier x1000 (lower better) | base-rate all {brier(np.full(n, base), y)*1000:.2f}"
          f"  fit {brier(np.full(fit_m.sum(), y[fit_m].mean()), y[fit_m])*1000:.2f}"
          f"  holdout {brier(np.full(test_m.sum(), y[test_m].mean()), y[test_m])*1000:.2f}")
    print("  (refresh regime: slot effective PA)")
    br, fp, fk = df["bat_rate"].values, df["f_pit"].values, df["f_park"].values
    report("full: bat*pit*park", stack, n_slot)
    report("bat only", br, n_slot)
    report("bat*pit", br * fp, n_slot)
    report("bat*park", br * fk, n_slot)
    report("bat*pit*park_empirical", br * fp * df["f_park_emp"].values, n_slot)
    report("league rate only (slot only)", lgr, n_slot)
    print("  (morning regime: k × season PA/G)")
    report("full: bat*pit*park", stack, n_morn)
    report("bat only", br, n_morn)
    report("league rate only (PA/G only)", lgr, n_morn)
    print("  (home-team PA haircut on slot n_eff)")
    for hc in (0.97, 0.94):
        report(f"full, home n_eff x{hc}", stack, n_slot * np.where(df["is_home"] == 1, hc, 1.0))
    print("  (recency blend: (1-w)*season + w*last15)")
    r15 = ((df["c_h15"].fillna(0) + 60 * lgr) / (df["c_pa15"].fillna(0) + 60)).values
    for w in (0.25, 0.5):
        report(f"form w={w}", ((1 - w) * br + w * r15) * fp * fk, n_slot)
    print("  (opposing starter K-rate factor)")
    lg_k = 0.22
    krate = ((df["c_pso"].fillna(0) + 300 * lg_k) / (df["c_bf"].fillna(0) + 300)).values
    for s in (0.25, 0.5):
        fkr = np.clip(1 - s * (krate / lg_k - 1), 0.85, 1.15)
        report(f"k-factor strength {s}", stack * (STARTER_SHARE * fkr + 1 - STARTER_SHARE), n_slot)

    # ── prior / strength sweeps (fit vs holdout, slot n_eff) ─────────────
    def fh(p):
        return f"{brier(p[fit_m], y[fit_m])*1000:7.2f} / {brier(p[test_m], y[test_m])*1000:7.2f}"

    print("\nBatter prior sweep — Brier x1000 fit / holdout:")
    for bp in (100, 200, 300, 400, 600, 900):
        b_ = ((df["c_h"] + bp * lgr) / (df["c_pa"] + bp)).values
        print(f"  prior {bp:>4}: {fh(game_prob(b_ * fp * fk, n_slot))}")
    print("Pitcher prior sweep:")
    for pp in (100, 200, 300, 500, 800):
        sh = ((df["c_ha"].fillna(0) + pp * lgr) / (df["c_bf"].fillna(0) + pp)).values
        f_ = STARTER_SHARE * np.clip(sh / lgr, PIT_LO, PIT_HI) + (1 - STARTER_SHARE)
        print(f"  prior {pp:>4}: {fh(game_prob(br * f_ * fk, n_slot))}")
    print("Starter share sweep:")
    for ss in (0.4, 0.55, 0.7, 1.0):
        f_ = ss * df["f_pit_raw"].values + (1 - ss)
        print(f"  share {ss:>4}: {fh(game_prob(br * f_ * fk, n_slot))}")
    print("Park damp sweep (static table):")
    for pd_ in (0.0, 0.5, 1.0):
        fpk = (1 + (df["home_team"].map(PARK_H).fillna(100) - 100) / 100 * pd_).values
        print(f"  damp {pd_:>4}: {fh(game_prob(br * fp * fpk, n_slot))}")

    # ── damp exponent alpha on the whole stack ───────────────────────────
    ratio = stack / lgr
    best = None
    for alpha in np.arange(0.4, 1.61, 0.05):
        b = brier(game_prob(lgr * ratio ** alpha, n_slot)[fit_m], y[fit_m])
        if best is None or b < best[1]:
            best = (alpha, b)
    alpha = best[0]
    p_cal = game_prob(lgr * ratio ** alpha, n_slot)
    print(f"\nStack exponent alpha fitted May-Jun: {alpha:.2f} | holdout Brier x1000: "
          f"alpha=1 {brier(p_slot[test_m], y[test_m])*1000:.2f} vs fitted {brier(p_cal[test_m], y[test_m])*1000:.2f}")

    # ── daily top-15 (the board list) ────────────────────────────────────
    df["p_morn"], df["p_slot"], df["p_blend"] = p_morn, p_slot, p_blend
    for label, col in (("morning", "p_morn"), ("refresh/slot-only", "p_slot"), ("refresh/blend CHOSEN", "p_blend")):
        top = df.sort_values(col, ascending=False).groupby("date").head(15)
        tg = top.groupby("date").agg(hits=("y", "sum"), exp=(col, "sum"))
        th = tg[tg.index >= HOLDOUT_START]
        print(f"Daily top-15 ({label}): hitters-with-a-hit {tg['hits'].mean():.2f} vs expected "
              f"{tg['exp'].mean():.2f} | holdout {th['hits'].mean():.2f} vs {th['exp'].mean():.2f} "
              f"| 15/15 days {int((tg['hits']==15).sum())}/{len(tg)}")
    for thr in (0.70, 0.74):
        m = test_m & (p_slot >= thr)
        if m.sum():
            print(f"holdout tail p>={thr*100:.0f}% (slot): n={int(m.sum())} pred {p_slot[m].mean()*100:.1f}% actual {y[m].mean()*100:.1f}%")

    with open("hit_bt_params.json", "w") as f:
        json.dump({"morning_k": round(float(k), 3), "refresh_k": round(float(k_blend), 3),
                   "refresh_w_slot": W_SLOT,
                   "slot_mean_pa": {int(s_): round(float(v), 2) for s_, v in slot_mean.items()},
                   "eff_pa_slot_free": eff_slot, "tilt_gamma": round(float(gamma), 2),
                   "batter_prior": BATTER_PRIOR, "fit_window": f"{EVAL_START}..{HOLDOUT_START}"},
                  f, indent=1)
    df.assign(p_cal=p_cal).to_csv("hit_bt_eval.csv", index=False)
    print("\nwrote hit_bt_eval.csv, hit_bt_params.json")


if __name__ == "__main__":
    main()
