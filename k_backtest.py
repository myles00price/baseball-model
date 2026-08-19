"""k_backtest.py — walk-forward backtest of the K WATCH strikeout skeleton.

Consumes the point-in-time boxscore CSVs (hit_bt_pitchers / hit_bt_batters /
hit_bt_games, built by hit_backtest_data.py) plus k_bt_priors.csv (2025
rates from k_backtest_data.py). For every STARTING pitcher appearance since
the burn-in date it builds tonight's strikeout distribution using ONLY data
from before that date, then grades it against the boxscore K total.

Skeleton under test (all inputs point-in-time):

  1. per-PA K probability   logit(p_i) = logit(p_pit) + logit(p_bat_i) - logit(lg)
       p_pit  : pitcher K/BF shrunk toward a prior (league or 2025 rate)
       p_bat_i: each lineup batter's K/PA shrunk the same way; the lineup is
                the ACTUAL slot 1-9 (refresh regime, lineups posted), the
                team's PREVIOUS game's slot 1-9 (morning proxy), or the
                team K% (morning fallback)
       pK     : mean of p_i over the nine
  2. expected batters faced  BF_hat = blend of last-N-start mean and season mean
                                       (shrunk toward league mean for short records)
  3. distribution            K ~ mixture over BF of Binomial(BF, pK), BF drawn
                             from BF_hat + empirical residuals (fit window);
                             Poisson(BF_hat x pK) as the simple alternative
  4. P(K >= n+0.5) for every half-line -> graded by Brier/log-loss, calibration
     by bucket, MAE of the mean vs naive baselines.

Fit window May-Jun 2026 (parameters), holdout Jul-1 onward. Every candidate
addition (recency K%, vs-hand batter K%, lineup-OBP BF tilt, 2025 prior,
Poisson vs mixture) is reported fit / holdout so it earns or loses its place.

Run:  C:\\Users\\Poons\\Model\\.venv\\Scripts\\python.exe k_backtest.py
"""

import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import betabinom, binom, poisson

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

EVAL_START = "2026-05-01"
HOLDOUT_START = os.environ.get("PROPS_HOLDOUT_START", "2026-07-01")  # rolling: set by props_retrain.py
MIN_PIT_BF = 60          # eligibility: some 2026 record
KMAX = 20                # distribution support 0..KMAX
LINES = [3.5, 4.5, 5.5, 6.5, 7.5, 8.5]


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


# ── distributions ────────────────────────────────────────────────────────

def dist_poisson(lam):
    ks = np.arange(KMAX + 1)
    pm = poisson.pmf(ks[None, :], lam[:, None])
    pm[:, -1] += 1 - pm.sum(1)
    return pm


def dist_mixture(bf_hat, pk, resid_w, resid_v, kappa=None):
    """P(K=k) = sum_r w_r Binom(k; max(1, round(bf_hat)+r), pk).
    With kappa: the per-PA rate itself is Beta(pk*kappa, (1-pk)*kappa) —
    beta-binomial, i.e. game-to-game stuff/umpire/approach variance."""
    ks = np.arange(KMAX + 1)
    out = np.zeros((len(bf_hat), KMAX + 1))
    base = np.rint(bf_hat).astype(int)
    for w, r in zip(resid_w, resid_v):
        n = np.clip(base + r, 1, 40)
        if kappa:
            out += w * betabinom.pmf(ks[None, :], n[:, None], (pk * kappa)[:, None], ((1 - pk) * kappa)[:, None])
        else:
            out += w * binom.pmf(ks[None, :], n[:, None], pk[:, None])
    out[:, -1] += 1 - out.sum(1)
    return out


def logscore(pm, k_act, mask):
    idx = np.clip(k_act.astype(int), 0, KMAX)
    p = pm[np.arange(len(pm)), idx][mask]
    return float(-np.mean(np.log(np.clip(p, 1e-9, 1))))


def p_over(pm, line):
    """P(K > line) for a half-line from a pmf matrix."""
    k0 = int(np.ceil(line))
    return pm[:, k0:].sum(1)


def mean_of(pm):
    return pm @ np.arange(KMAX + 1)


def calib(p, y, label, edges=(0, .2, .3, .4, .5, .6, .7, .8, 1.01)):
    print(f"\n  calibration — {label}:")
    for lo, hi in zip(edges, edges[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum():
            print(f"    P {lo*100:>3.0f}-{hi*100:<3.0f}: n={int(m.sum()):>5}  pred {p[m].mean()*100:5.1f}%  "
                  f"actual {y[m].mean()*100:5.1f}%")


def line_score(pm, k_act, mask, label):
    """Brier / log-loss over all fixed half-lines + the 'nearest-median' line."""
    rows = []
    for L in LINES:
        p = p_over(pm, L)[mask]
        y = (k_act[mask] > L).astype(float)
        rows.append((L, brier(p, y), logloss(p, y)))
    med = np.array([np.searchsorted(np.cumsum(r), 0.5) for r in pm])  # median K
    Lm = med - 0.5                                                      # book-style line near median
    p = np.array([pm[i, int(np.ceil(Lm[i])):].sum() for i in range(len(pm))])[mask]
    y = (k_act[mask] > Lm[mask]).astype(float)
    print(f"  {label:<38} " + " ".join(f"{L}:{b*1000:5.1f}" for L, b, _ in rows)
          + f" | med-line brier {brier(p, y)*1000:5.1f} ll {logloss(p, y):.4f} "
          f"| meanBrier {np.mean([b for _, b, _ in rows])*1000:5.1f}")
    return np.mean([b for _, b, _ in rows]), brier(p, y)


def main():
    pit = pd.read_csv("hit_bt_pitchers.csv")
    bat = pd.read_csv("hit_bt_batters.csv")
    games = pd.read_csv("hit_bt_games.csv").drop_duplicates("game_pk")
    pri = pd.read_csv("k_bt_priors.csv")
    priP = pri[pri.kind == "P"].set_index("id")
    priB = pri[pri.kind == "B"].set_index("id")
    priC = pri[pri.kind == "C"].set_index("id")
    print(f"loaded: {len(pit)} pitcher-games, {len(bat)} batter-games, {len(games)} games")

    # ── league / team point-in-time K% (from batter rows) ────────────────
    lg = bat.groupby("date").agg(pa=("pa", "sum"), so=("so", "sum")).sort_index()
    lg["c_pa"] = lg["pa"].cumsum() - lg["pa"]
    lg["c_so"] = lg["so"].cumsum() - lg["so"]
    lg["lg_k"] = (lg["c_so"] / lg["c_pa"]).fillna(0.22)
    lg_k_of = lg["lg_k"].to_dict()

    tm = bat.groupby(["team", "date"]).agg(pa=("pa", "sum"), so=("so", "sum")).reset_index().sort_values(["team", "date"])
    gt = tm.groupby("team")
    tm["c_pa"] = gt["pa"].cumsum() - tm["pa"]
    tm["c_so"] = gt["so"].cumsum() - tm["so"]
    team_k = {(r.team, r.date): (r.c_so, r.c_pa) for r in tm.itertuples()}

    # ── batter cumulatives (overall + vs starter hand) ───────────────────
    bat = bat.merge(games[["game_pk", "home_sp_hand", "away_sp_hand"]], on="game_pk", how="left")
    bat["opp_hand"] = np.where(bat["is_home"] == 1, bat["away_sp_hand"], bat["home_sp_hand"])
    bd = (bat.groupby(["batter", "date"])
             .agg(pa=("pa", "sum"), so=("so", "sum"), team=("team", "first"),
                  hand=("opp_hand", "first"), slot=("slot", "max"), game_pk=("game_pk", "first"))
             .reset_index().sort_values(["batter", "date"]))
    gb = bd.groupby("batter")
    bd["c_pa"] = gb["pa"].cumsum() - bd["pa"]
    bd["c_so"] = gb["so"].cumsum() - bd["so"]
    for h in ("L", "R"):
        m = (bd["hand"] == h)
        bd[f"pa_{h}"] = np.where(m, bd["pa"], 0)
        bd[f"so_{h}"] = np.where(m, bd["so"], 0)
        bd[f"c_pa_{h}"] = bd.groupby("batter")[f"pa_{h}"].cumsum() - bd[f"pa_{h}"]
        bd[f"c_so_{h}"] = bd.groupby("batter")[f"so_{h}"].cumsum() - bd[f"so_{h}"]
    bd["pri_so"] = bd["batter"].map(priB["so"]).fillna(0)
    bd["pri_pa"] = bd["batter"].map(priB["denom"]).fillna(0)
    bat_day = {(r.batter, r.date): r for r in bd.itertuples()}

    # lineups: (team, date) -> list of batter ids slot 1-9 that game; and prev game's
    lu = bat[bat["slot"] > 0].sort_values(["team", "date", "slot"]).drop_duplicates(["team", "date", "slot"])
    lineup_of = lu.groupby(["team", "date"])["batter"].apply(list).to_dict()
    team_dates = {t: sorted(d for (tt, d) in lineup_of if tt == t) for t in lu["team"].unique()}
    prev_lineup = {}
    for t, ds in team_dates.items():
        for i, d in enumerate(ds):
            prev_lineup[(t, d)] = lineup_of[(t, ds[i - 1])] if i > 0 else None
    # OBP-ish: batter reaches (h+bb+hbp)/pa cumulative for the lineup-OBP tilt
    bd2 = bat.groupby(["batter", "date"]).agg(h=("h", "sum"), bb=("bb", "sum"), hbp=("hbp", "sum")).reset_index().sort_values(["batter", "date"])
    g2 = bd2.groupby("batter")
    bd2["c_ob"] = g2["h"].cumsum() - bd2["h"] + g2["bb"].cumsum() - bd2["bb"] + g2["hbp"].cumsum() - bd2["hbp"]
    ob_day = {(r.batter, r.date): r.c_ob for r in bd2.itertuples()}
    lg_ob = ((bat["h"] + bat["bb"] + bat["hbp"]).sum() / bat["pa"].sum())

    # ── pitcher cumulatives ──────────────────────────────────────────────
    pit = pit.sort_values(["pitcher", "date"]).reset_index(drop=True)
    gp = pit.groupby("pitcher")
    pit["c_bf"] = gp["bf"].cumsum() - pit["bf"]
    pit["c_so"] = gp["so"].cumsum() - pit["so"]
    st = pit[pit["is_starter"] == 1].copy()
    gs = st.groupby("pitcher")
    st["c_gs"] = gs.cumcount()
    st["c_bf_st"] = gs["bf"].cumsum() - st["bf"]
    st["c_so_st"] = gs["so"].cumsum() - st["so"]
    for n in (3, 5, 8):
        st[f"bf_l{n}"] = gs["bf"].transform(lambda s: s.shift(1).rolling(n, min_periods=1).mean())
        st[f"so_l{n}"] = gs["so"].transform(lambda s: s.shift(1).rolling(n, min_periods=1).sum())
        st[f"bfsum_l{n}"] = gs["bf"].transform(lambda s: s.shift(1).rolling(n, min_periods=1).sum())
    st["pri_so"] = st["pitcher"].map(priP["so"]).fillna(0)
    st["pri_bf"] = st["pitcher"].map(priP["denom"]).fillna(0)
    st["car_so"] = st["pitcher"].map(priC["so"]).fillna(0)
    st["car_bf"] = st["pitcher"].map(priC["denom"]).fillna(0)
    st = st.merge(games[["game_pk", "home_team", "away_team"]], on="game_pk", how="left")
    st["opp"] = np.where(st["team"] == st["home_team"], st["away_team"], st["home_team"])
    st = st[(st["date"] >= EVAL_START) & (st["c_bf"] >= MIN_PIT_BF)].reset_index(drop=True)
    st["lg_k"] = st["date"].map(lg_k_of)
    print(f"eval: {len(st)} starts {EVAL_START}..{st['date'].max()} | mean K {st['so'].mean():.2f} "
          f"sd {st['so'].std():.2f} | mean BF {st['bf'].mean():.1f} sd {st['bf'].std():.1f}")

    # league mean BF per start (fit window) for shrinkage
    fit_m = (st["date"] < HOLDOUT_START).values
    test_m = ~fit_m
    LG_BF = st.loc[fit_m, "bf"].mean()
    k_act = st["so"].values.astype(float)
    lgk = st["lg_k"].values

    # ── batter-side per start: lineup means under several regimes ────────
    def bat_rate(row, prior_n, target, hand=None):
        if hand in ("L", "R"):
            so, pa = getattr(row, f"c_so_{hand}"), getattr(row, f"c_pa_{hand}")
        else:
            so, pa = row.c_so, row.c_pa
        return (so + prior_n * target) / (pa + prior_n)

    def lineup_terms(ids, date, lgk_d, prior_n, use_2025, hand=None):
        """mean logit(p_bat) - logit(lg) over the lineup + mean OBP; None if empty."""
        terms, obs = [], []
        for b in ids:
            r = bat_day.get((b, date))
            if r is None:
                continue
            tgt = lgk_d
            if use_2025 and r.pri_pa > 0:
                tgt = (r.pri_so + 200 * lgk_d) / (r.pri_pa + 200)
            pb = bat_rate(r, prior_n, tgt, hand)
            terms.append(logit(pb) - logit(lgk_d))
            ob = ob_day.get((b, date))
            if ob is not None and r.c_pa > 0:
                obs.append((ob + 100 * lg_ob) / (r.c_pa + 100))
        if not terms:
            return None, None
        return float(np.mean(terms)), (float(np.mean(obs)) if obs else lg_ob)

    regimes = {}
    for name, prior_n, use25, hand_split in (
            ("lineup", 60, False, False), ("lineup_p100", 100, False, False),
            ("lineup_p30", 30, False, False), ("lineup_2025", 60, True, False),
            ("lineup_hand", 60, False, True), ("prev_lineup", 60, False, False),
            ("team", None, None, None)):
        vals, obs = np.zeros(len(st)), np.full(len(st), lg_ob)
        for i, r in enumerate(st.itertuples()):
            if name == "team":
                so, pa = team_k.get((r.opp, r.date), (0, 0))
                pt = (so + 300 * r.lg_k) / (pa + 300)
                vals[i] = logit(pt) - logit(r.lg_k)
                continue
            ids = prev_lineup.get((r.opp, r.date)) if name == "prev_lineup" else lineup_of.get((r.opp, r.date))
            if not ids:
                so, pa = team_k.get((r.opp, r.date), (0, 0))
                vals[i] = logit((so + 300 * r.lg_k) / (pa + 300)) - logit(r.lg_k)
                continue
            t, ob = lineup_terms(ids, r.date, r.lg_k, prior_n, use25, r.hand if hand_split else None)
            if t is None:
                so, pa = team_k.get((r.opp, r.date), (0, 0))
                t = logit((so + 300 * r.lg_k) / (pa + 300)) - logit(r.lg_k)
                ob = lg_ob
            vals[i], obs[i] = t, ob
        regimes[name] = (vals, obs)
    print("regimes built:", ", ".join(regimes))

    # ── pitcher rate under prior variants ────────────────────────────────
    def pit_rate(prior_n, use25, anchor_n=200):
        """use25: False=league target, True=2025 rate, 'career'=career-thru-2025 rate,
        'blend'=career shrunk toward league then 2025 given double weight (recent bias)."""
        tgt = lgk.copy()
        if use25 is True:
            has = st["pri_bf"].values > 0
            tgt = np.where(has, (st["pri_so"].values + anchor_n * lgk) / (st["pri_bf"].values + anchor_n), lgk)
        elif use25 == "career":
            has = st["car_bf"].values > 0
            tgt = np.where(has, (st["car_so"].values + anchor_n * lgk) / (st["car_bf"].values + anchor_n), lgk)
        elif use25 == "blend":
            so = st["car_so"].values + st["pri_so"].values          # 2025 counted twice
            bf = st["car_bf"].values + st["pri_bf"].values
            tgt = (so + anchor_n * lgk) / (bf + anchor_n)
        return (st["c_so"].values + prior_n * tgt) / (st["c_bf"].values + prior_n)

    # ── expected BF ──────────────────────────────────────────────────────
    def bf_hat(w_recent, n_recent, prior_starts=3):
        season = (st["c_bf_st"].values + prior_starts * LG_BF) / (st["c_gs"].values + prior_starts)
        rec = st[f"bf_l{n_recent}"].fillna(LG_BF).values
        rec = np.where(st["c_gs"].values >= 1, rec, LG_BF)
        return w_recent * rec + (1 - w_recent) * season

    print(f"\nExpected BF — MAE vs actual BF (fit / holdout); league mean {LG_BF:.1f}:")
    bf_opts = {}
    for w in (0.0, 0.25, 0.5, 0.75, 1.0):
        for n in (3, 5, 8):
            if w == 0.0 and n != 5:
                continue
            b = bf_hat(w, n)
            bf_opts[(w, n)] = b
            print(f"  w_recent={w:<4} n={n}: {np.abs(b - st['bf'].values)[fit_m].mean():.3f} / "
                  f"{np.abs(b - st['bf'].values)[test_m].mean():.3f}")
    print(f"  naive league mean:   {np.abs(LG_BF - st['bf'].values)[fit_m].mean():.3f} / "
          f"{np.abs(LG_BF - st['bf'].values)[test_m].mean():.3f}")
    # provisional choice by fit MAE (re-chosen below by fit-window Brier)
    best_bf = min(bf_opts, key=lambda k: np.abs(bf_opts[k] - st["bf"].values)[fit_m].mean())
    print(f"  best by fit MAE: w_recent={best_bf[0]} n={best_bf[1]}")
    BF = bf_opts[best_bf]
    # lineup-OBP tilt on BF (more runners -> more BF)
    for s in (0.5, 1.0):
        ob = regimes["lineup"][1]
        b2 = BF * (1 + s * (ob / lg_ob - 1))
        print(f"  + OBP tilt s={s}: {np.abs(b2 - st['bf'].values)[fit_m].mean():.3f} / "
              f"{np.abs(b2 - st['bf'].values)[test_m].mean():.3f}")
    # K-rate tilt on BF (high-K pitchers go deeper?)
    resid_bf = st["bf"].values - BF

    # ── residual distribution for the mixture (fit window) ───────────────
    r_int = np.rint(resid_bf[fit_m]).astype(int)
    r_int = np.clip(r_int, -18, 12)
    vals_r, cnt = np.unique(r_int, return_counts=True)
    resid_w, resid_v = cnt / cnt.sum(), vals_r
    print(f"  BF residual (fit): sd {resid_bf[fit_m].std():.2f}, support {vals_r.min()}..{vals_r.max()}")

    # ── core comparison ──────────────────────────────────────────────────
    KAPPA = [None]  # set after the fit below; None = plain binomial

    def build(p_pit, bat_term, bf, kind="mix", kappa="auto"):
        pk = sigmoid(logit(p_pit) + bat_term)
        if kind == "pois":
            return dist_poisson(bf * pk), pk
        kap = KAPPA[0] if kappa == "auto" else kappa
        return dist_mixture(bf, pk, resid_w, resid_v, kap), pk

    def fit_brier(pm):
        return np.mean([brier(p_over(pm, L)[fit_m], (k_act[fit_m] > L)) for L in LINES])

    print("\nBrier x1000 by line (holdout) — lower is better")
    print(f"  {'variant':<38} " + " ".join(f"{L:>5}" for L in LINES))
    results = {}
    # naive baselines
    naive_rate = (st["c_so_st"].values + 3 * LG_BF * lgk) / (st["c_bf_st"].values + 3 * LG_BF)
    naive_lam = naive_rate * ((st["c_bf_st"].values + 3 * LG_BF) / (st["c_gs"].values + 3))
    pm = dist_poisson(naive_lam)
    results["naive: season K/start Poisson"] = line_score(pm, k_act, test_m, "naive: season K/start Poisson")
    pm = dist_poisson(np.full(len(st), k_act[fit_m].mean()))
    results["naive: league mean Poisson"] = line_score(pm, k_act, test_m, "naive: league mean Poisson")

    for pn in (50, 100, 200, 400):
        pm, _ = build(pit_rate(pn, False), regimes["lineup"][0], BF)
        results[f"lineup, pit prior {pn}, lg target"] = line_score(pm, k_act, test_m, f"lineup, pit prior {pn}, lg target")
    for pn in (100, 200, 400):
        pm, _ = build(pit_rate(pn, True), regimes["lineup"][0], BF)
        results[f"lineup, pit prior {pn}, 2025 target"] = line_score(pm, k_act, test_m, f"lineup, pit prior {pn}, 2025 target")
    for pn in (100, 200, 400, 800):
        pm, _ = build(pit_rate(pn, "career"), regimes["lineup"][0], BF)
        results[f"lineup, pit prior {pn}, career target"] = line_score(pm, k_act, test_m, f"lineup, pit prior {pn}, career target")
    for pn in (200, 400, 800):
        pm, _ = build(pit_rate(pn, "blend"), regimes["lineup"][0], BF)
        results[f"lineup, pit prior {pn}, career+2025x2 target"] = line_score(pm, k_act, test_m, f"lineup, pit prior {pn}, career+2025x2")
    # pick pitcher prior by FIT window (not holdout)
    fit_scores = {}
    for pn in (50, 100, 200, 400, 800):
        for u in (False, True, "career", "blend"):
            pm, _ = build(pit_rate(pn, u), regimes["lineup"][0], BF)
            fit_scores[(pn, u)] = np.mean([brier(p_over(pm, L)[fit_m], (k_act[fit_m] > L)) for L in LINES])
    (PN, U25) = min(fit_scores, key=fit_scores.get)
    print("  fit-window mean Brier by (prior BF, target): " + "  ".join(
        f"{k[0]}/{ {False:'lg',True:'2025','career':'car','blend':'bl'}[k[1]] }:{v*1000:.2f}" for k, v in sorted(fit_scores.items(), key=lambda kv: kv[1])[:8]))
    print(f"  -> pitcher prior chosen on FIT window: {PN} BF, target={U25}")
    P_PIT = pit_rate(PN, U25)
    # small-sample subset: pitchers with < 150 BF this season at game time (the Snell case)
    small = (st["c_bf"].values < 150) & test_m
    print(f"  small-sample starts (c_bf<150, holdout n={int(small.sum())}) — mean Brier by target at chosen prior:")
    for u in (False, True, "career", "blend"):
        pm, _ = build(pit_rate(PN, u), regimes["lineup"][0], BF)
        mb = np.mean([brier(p_over(pm, L)[small], (k_act[small] > L)) for L in LINES])
        print(f"      target={u}: {mb*1000:.1f}")

    print("\n  batter-side regimes (chosen pitcher prior):")
    for name in ("team", "prev_lineup", "lineup", "lineup_p30", "lineup_p100", "lineup_2025", "lineup_hand"):
        pm, _ = build(P_PIT, regimes[name][0], BF)
        results[name] = line_score(pm, k_act, test_m, f"bat regime: {name}")
    print("  no batter term (pitcher only):")
    pm, _ = build(P_PIT, np.zeros(len(st)), BF)
    results["pitcher only"] = line_score(pm, k_act, test_m, "pitcher only")
    print("  batter term strength (x0.5 / x1.5, lineup regime):")
    for s in (0.5, 1.5):
        pm, _ = build(P_PIT, s * regimes["lineup"][0], BF)
        line_score(pm, k_act, test_m, f"lineup x{s}")

    # re-choose the BF option by FIT-window Brier (with the chosen pitcher prior)
    bf_fit = {k: fit_brier(build(P_PIT, regimes["lineup"][0], b)[0]) for k, b in bf_opts.items()}
    best_bf = min(bf_fit, key=bf_fit.get)
    BF = bf_opts[best_bf]
    print(f"\n  BF option chosen by fit Brier: w_recent={best_bf[0]} n={best_bf[1]}")

    print("\n  distribution family (lineup regime):")
    pm_bin, PK = build(P_PIT, regimes["lineup"][0], BF, "mix", kappa=None)
    pm_pois, _ = build(P_PIT, regimes["lineup"][0], BF, "pois")
    line_score(pm_bin, k_act, test_m, "mixture-binomial (BF residuals)")
    line_score(pm_pois, k_act, test_m, "poisson(BF x pK)")
    print(f"  full-pmf log score (holdout, lower better): binomial-mix {logscore(pm_bin, k_act, test_m):.4f}"
          f"  poisson {logscore(pm_pois, k_act, test_m):.4f}")
    print("  beta-binomial per-PA rate: kappa fitted on FIT window by log score")
    kap_fit = {}
    for kap in (30, 50, 75, 100, 150, 200, 300, 500):
        pm_k, _ = build(P_PIT, regimes["lineup"][0], BF, "mix", kappa=kap)
        kap_fit[kap] = logscore(pm_k, k_act, fit_m)
        print(f"    kappa {kap:>4}: fit ls {kap_fit[kap]:.4f}  holdout ls {logscore(pm_k, k_act, test_m):.4f}"
              f"  holdout meanBrier {np.mean([brier(p_over(pm_k, L)[test_m], (k_act[test_m] > L)) for L in LINES])*1000:5.1f}")
    print(f"    binomial (kappa=inf): fit ls {logscore(pm_bin, k_act, fit_m):.4f}")
    KAPPA[0] = min(kap_fit, key=kap_fit.get)
    if kap_fit[KAPPA[0]] >= logscore(pm_bin, k_act, fit_m):
        KAPPA[0] = None
    print(f"  -> kappa chosen: {KAPPA[0]}")
    pm_mix, PK = build(P_PIT, regimes["lineup"][0], BF)
    line_score(pm_mix, k_act, test_m, f"CHOSEN: mixture, kappa={KAPPA[0]}")
    lam = BF * PK
    print(f"  mean K: model {lam[test_m].mean():.2f} vs actual {k_act[test_m].mean():.2f} (holdout) | "
          f"MAE model {np.abs(lam - k_act)[test_m].mean():.3f}  naive-season {np.abs(naive_lam - k_act)[test_m].mean():.3f}  "
          f"league {np.abs(k_act[fit_m].mean() - k_act)[test_m].mean():.3f}")
    print(f"  variance: actual {k_act[test_m].var():.2f}  mixture {((pm_mix * (np.arange(KMAX+1)**2)).sum(1) - mean_of(pm_mix)**2)[test_m].mean():.2f}  "
          f"poisson {lam[test_m].mean():.2f}")

    print("\n  BF-side variants (lineup regime, mixture):")
    for (w, n), b in bf_opts.items():
        if (w, n) in ((0.0, 5), (0.5, 5), (1.0, 5), (0.5, 8), (0.25, 5)):
            pm, _ = build(P_PIT, regimes["lineup"][0], b)
            line_score(pm, k_act, test_m, f"BF w={w} n={n}")
    for s in (0.5, 1.0):
        b2 = BF * (1 + s * (regimes["lineup"][1] / lg_ob - 1))
        pm, _ = build(P_PIT, regimes["lineup"][0], b2)
        line_score(pm, k_act, test_m, f"BF + OBP tilt s={s}")

    print("\n  recency K% blend (last-5-start K/BF, expected to fail):")
    for w in (0.25, 0.5):
        r5 = (st["so_l5"].fillna(0).values + 100 * lgk) / (st["bfsum_l5"].fillna(0).values + 100)
        pm, _ = build((1 - w) * P_PIT + w * r5, regimes["lineup"][0], BF)
        line_score(pm, k_act, test_m, f"recency w={w}")

    # ── calibration of the chosen model on holdout ───────────────────────
    pm = pm_mix
    for L in (4.5, 5.5, 6.5):
        calib(p_over(pm, L)[test_m], (k_act[test_m] > L).astype(float), f"HOLDOUT P(over {L})")
    # book-style: line nearest the model median
    med = np.array([np.searchsorted(np.cumsum(r), 0.5) for r in pm])
    Lm = med - 0.5
    p_med = np.array([pm[i, int(np.ceil(Lm[i])):].sum() for i in range(len(pm))])
    y_med = (k_act > Lm).astype(float)
    calib(p_med[test_m], y_med[test_m], "HOLDOUT P(over median-line)", edges=(0, .4, .45, .5, .55, .6, .65, 1.01))
    # PIT-style: predicted vs actual over the whole distribution by decile of E[K]
    print("\n  mean K by predicted decile (holdout):")
    d = pd.DataFrame({"lam": lam[test_m], "k": k_act[test_m]})
    d["dec"] = pd.qcut(d["lam"], 8, labels=False, duplicates="drop")
    for g, sub in d.groupby("dec"):
        print(f"    pred {sub['lam'].mean():5.2f}  actual {sub['k'].mean():5.2f}  n={len(sub)}")

    # ── morning vs refresh: how much does the actual lineup buy? ────────
    print("\n  morning-regime choice for the live model:")
    for name in ("team", "prev_lineup"):
        pm_, _ = build(P_PIT, regimes[name][0], BF)
        line_score(pm_, k_act, test_m, f"morning: {name}")

    # ── save eval + params ───────────────────────────────────────────────
    st["p_pit"] = P_PIT
    st["bat_term"] = regimes["lineup"][0]
    st["pk"] = PK
    st["bf_hat"] = BF
    st["lam"] = lam
    for L in LINES:
        st[f"p_over_{L}"] = p_over(pm, L)
    st.to_csv("k_bt_eval.csv", index=False)
    params = {
        "fit_window": f"{EVAL_START}..{HOLDOUT_START}",
        "pit_prior_bf": int(PN), "pit_prior_target": str(U25),
        "bat_prior_pa": 60, "bf_w_recent": best_bf[0], "bf_n_recent": best_bf[1],
        "bf_prior_starts": 3, "lg_bf": round(float(LG_BF), 2), "kappa": KAPPA[0],
        "resid": {"v": [int(v) for v in resid_v], "w": [round(float(w), 5) for w in resid_w]},
        "holdout_summary": {k: [round(v[0] * 1000, 2), round(v[1] * 1000, 2)] for k, v in results.items()},
    }
    with open("k_bt_params.json", "w") as f:
        json.dump(params, f, indent=1)
    print("\nwrote k_bt_eval.csv, k_bt_params.json")


if __name__ == "__main__":
    main()
