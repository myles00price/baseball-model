"""hr_backtest2.py — round two: arsenal + weather factors, walk-forward.

Consumes hr_bt_eval.csv (round-one eval rows: the surviving core stack
bat_rate x f_pit x f_park, labels, exp_pa) plus the round-two pulls:

  hr_bt_bat_arsenal.csv / hr_bt_pit_usage.csv — per-day per-pitch-type
      batter ISO components and pitcher pitch counts. A chronological
      sweep rebuilds "profiles as of that morning" per hitter-day with
      zero leakage, then applies the LIVE arsenal logic (50-AB type
      shrinkage, 0.85–1.15 cap).
  hr_bt_weather.csv — game-time weather per game_pk; live wind/temp
      multiplier logic applied verbatim.

Ablations on the July+ holdout: core, +arsenal, +wind, +temp, +all.

Run:  C:\\Users\\Poons\\Model\\.venv\\Scripts\\python.exe hr_backtest2.py
"""

import sys
from collections import defaultdict

import numpy as np
import pandas as pd

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

ARSENAL_PRIOR_AB = 50
ARSENAL_LO, ARSENAL_HI = 0.85, 1.15
MIN_BAT_AB = 50
MIN_PIT_N = 100
WIND_PER_MPH = 0.02
WIND_CAP = 0.25
TEMP_PER_F = 0.005
TEMP_BASE_F = 72
TEMP_CAP = 0.12
FIT_END = "2026-07-01"


def weather_mults(row):
    cond = str(row.condition).lower()
    if "dome" in cond or "roof closed" in cond:
        return 1.0, 1.0
    temp_mult = 1.0
    try:
        adj = (float(row.temp) - TEMP_BASE_F) * TEMP_PER_F
        temp_mult = 1.0 + max(-TEMP_CAP, min(TEMP_CAP, adj))
    except (TypeError, ValueError):
        pass
    wind_mult = 1.0
    w = str(row.wind)
    try:
        mph = float(w.split("mph")[0].strip())
        wl = w.lower()
        sign = 1 if "out to" in wl else -1 if "in from" in wl else 0
        if sign:
            wind_mult = 1.0 + max(-WIND_CAP, min(WIND_CAP, sign * mph * WIND_PER_MPH))
    except (ValueError, IndexError):
        pass
    return wind_mult, temp_mult


def main():
    ev = pd.read_csv("hr_bt_eval.csv")
    bat_a = pd.read_csv("hr_bt_bat_arsenal.csv").sort_values("date")
    use = pd.read_csv("hr_bt_pit_usage.csv").sort_values("date")
    wx = pd.read_csv("hr_bt_weather.csv").drop_duplicates("game_pk")
    print(f"eval {len(ev)} rows | arsenal {len(bat_a)} | usage {len(use)} | wx {len(wx)}")

    # ── weather multipliers per game ─────────────────────────────────────
    wm = {int(r.game_pk): weather_mults(r) for r in wx.itertuples()}
    ev["f_wind"] = ev["game_pk"].map(lambda pk: wm.get(int(pk), (1.0, 1.0))[0])
    ev["f_temp"] = ev["game_pk"].map(lambda pk: wm.get(int(pk), (1.0, 1.0))[1])
    got = (ev["game_pk"].map(lambda pk: int(pk) in wm)).mean()
    print(f"weather coverage {got*100:.0f}% | wind!=1: {(ev['f_wind']!=1).mean()*100:.0f}%"
          f" | temp!=1: {(ev['f_temp']!=1).mean()*100:.0f}%")

    # ── arsenal factor via chronological sweep ───────────────────────────
    bat_cum = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))  # b -> pt -> ab,h,tb
    pit_cum = defaultdict(lambda: defaultdict(int))                # p -> pt -> n
    bat_by_date = {d: g for d, g in bat_a.groupby("date")}
    use_by_date = {d: g for d, g in use.groupby("date")}
    ev = ev.sort_values("date")
    ev_by_date = {d: g for d, g in ev.groupby("date")}
    all_dates = sorted(set(bat_a["date"]) | set(ev["date"]))
    f_ars = {}
    for d in all_dates:
        g = ev_by_date.get(d)
        if g is not None:
            for r in g.itertuples():
                f = 1.0
                b = bat_cum.get(r.batter)
                p = pit_cum.get(r.opp_sp)
                if b and p:
                    tot_ab = sum(v[0] for v in b.values())
                    tot_h = sum(v[1] for v in b.values())
                    tot_tb = sum(v[2] for v in b.values())
                    tot_n = sum(p.values())
                    if tot_ab >= MIN_BAT_AB and tot_n >= MIN_PIT_N:
                        base = (tot_tb - tot_h) / tot_ab
                        if base >= 0.05:
                            exp = 0.0
                            for pt, n in p.items():
                                u = n / tot_n
                                ab, h, tb = b.get(pt, (0, 0, 0))
                                iso_t = base if ab == 0 else \
                                    (ab * ((tb - h) / ab) + ARSENAL_PRIOR_AB * base) / (ab + ARSENAL_PRIOR_AB)
                                exp += u * iso_t
                            f = max(ARSENAL_LO, min(ARSENAL_HI, exp / base))
                f_ars[(r.batter, r.date, r.game_pk)] = f
        gb = bat_by_date.get(d)
        if gb is not None:
            for r in gb.itertuples():
                c = bat_cum[r.batter][r.pt]
                c[0] += r.ab; c[1] += r.h; c[2] += r.tb
        gu = use_by_date.get(d)
        if gu is not None:
            for r in gu.itertuples():
                pit_cum[r.pitcher][r.pt] += r.n
    ev["f_arsenal"] = [f_ars.get((r.batter, r.date, r.game_pk), 1.0) for r in ev.itertuples()]
    print(f"arsenal factor: neutral {(ev['f_arsenal']==1).mean()*100:.0f}% | "
          f"min {ev['f_arsenal'].min():.2f} max {ev['f_arsenal'].max():.2f}")

    # ── ablations ────────────────────────────────────────────────────────
    def gp(stack, exp_pa):
        return 1 - (1 - stack.clip(1e-5, 0.5)) ** exp_pa

    core = ev["bat_rate"] * ev["f_pit"] * ev["f_park"]
    variants = {
        "core (live, no platoon)": core,
        "core + arsenal": core * ev["f_arsenal"],
        "core + wind": core * ev["f_wind"],
        "core + temp": core * ev["f_temp"],
        "core + weather": core * ev["f_wind"] * ev["f_temp"],
        "core + all": core * ev["f_arsenal"] * ev["f_wind"] * ev["f_temp"],
    }
    for win, mask in (("fit May-Jun", ev["date"] < FIT_END),
                      ("HOLDOUT Jul+", ev["date"] >= FIT_END)):
        y = ev.loc[mask, "y"].values
        print(f"\n{win}: n={mask.sum()}, actual {y.mean()*100:.1f}% | Brier x1000")
        for name, stack in variants.items():
            p = gp(stack[mask], ev.loc[mask, "exp_pa"]).values
            print(f"  {name:<24} {float(np.mean((p-y)**2))*1000:.3f}")

    # tail + top-15 with everything on, holdout
    mask = ev["date"] >= FIT_END
    p_all = gp(variants["core + all"], ev["exp_pa"])
    sub = ev[mask].assign(p=p_all[mask])
    t = sub[sub["p"] >= 0.16]
    print(f"\nHoldout tail p>=16% (all factors): pred {t['p'].mean()*100:.1f}% "
          f"actual {t['y'].mean()*100:.1f}% (n={len(t)})")
    top = sub.sort_values("p", ascending=False).groupby("date").head(15)
    tg = top.groupby("date").agg(h=("y", "sum"), e=("p", "sum"))
    print(f"Holdout top-15/day: hits {tg['h'].mean():.2f} vs exp {tg['e'].mean():.2f}")

    ev.to_csv("hr_bt_eval2.csv", index=False)
    print("wrote hr_bt_eval2.csv")


if __name__ == "__main__":
    main()
