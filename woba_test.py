"""
woba_test.py — does linear-weights offense (wOBA, the engine of wRC+)
beat OPS as a team-offense feature? Point-in-time, weekly walk-forward.
Park/league adjustment (the '+' in wRC+) not included — stated caveat.

Run:  py -3.11 .\\woba_test.py
"""

import csv
import sys
import time
from glob import glob

import numpy as np
import requests
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from check_results import get_game_results
from team_offense_family_test import TID, prior_date

W = {"bb": 0.69, "hbp": 0.72, "s": 0.88, "d": 1.24, "t": 1.56, "hr": 2.00}

_cache = {}
def offense_before(team, date):
    key = (team, date)
    if key in _cache:
        return _cache[key]
    tid = TID.get(team)
    try:
        j = requests.get(f"https://statsapi.mlb.com/api/v1/teams/{tid}/stats",
                         params={"stats": "byDateRange", "group": "hitting", "season": 2026,
                                 "startDate": "2026-03-25", "endDate": date},
                         timeout=30).json()
        st = j["stats"][0]["splits"][0]["stat"]
        g = lambda k: float(st.get(k, 0) or 0)
        h, d2, t3, hr = g("hits"), g("doubles"), g("triples"), g("homeRuns")
        singles = h - d2 - t3 - hr
        bb, ibb, hbp = g("baseOnBalls"), g("intentionalWalks"), g("hitByPitch")
        ab, sf = g("atBats"), g("sacFlies")
        denom = ab + bb - ibb + sf + hbp
        woba = ((W["bb"] * (bb - ibb) + W["hbp"] * hbp + W["s"] * singles
                 + W["d"] * d2 + W["t"] * t3 + W["hr"] * hr) / denom) if denom else 0
        out = {"woba": woba, "ops": float(st.get("ops", 0) or 0)}
        _cache[key] = out if out["ops"] > 0 else None
    except Exception:
        _cache[key] = None
    time.sleep(0.05)
    return _cache[key]


def main():
    games = []
    for f in sorted(glob("picks_2026-*.csv")):
        d = f.replace("picks_", "").replace(".csv", "")
        if d > "2026-08-06":
            continue
        try:
            R = get_game_results(d)
        except Exception:
            continue
        if not R:
            continue
        time.sleep(0.05)
        pd_ = prior_date(d)
        for row in csv.DictReader(open(f, encoding="utf-8-sig")):
            a, h = row["Away"], row["Home"]
            r = R.get(f"{a}@{h}")
            if not r:
                continue
            sa, sh = offense_before(a, pd_), offense_before(h, pd_)
            if not sa or not sh:
                continue
            games.append({"d": d, "y": 1 if r["winner"] == h else 0,
                          "ops": sh["ops"] - sa["ops"],
                          "woba": sh["woba"] - sa["woba"]})
    print(f"{len(games)} games")
    games.sort(key=lambda g: g["d"])
    dates = sorted({g["d"] for g in games})
    CONFIGS = {"OPS (baseline)": ["ops"], "wOBA (wRC+ engine)": ["woba"],
               "OPS + wOBA": ["ops", "woba"]}
    print(f"{'CONFIG':<20}{'n':>6}{'acc':>8}{'brier':>9}{'logloss':>9}")
    for name, cols in CONFIGS.items():
        preds, ys = [], []
        for dt in dates:
            tr = [g for g in games if g["d"] < dt]
            te = [g for g in games if g["d"] == dt]
            if len(tr) < 150 or not te:
                continue
            X = np.array([[g[c] for c in cols] for g in tr])
            Xt = np.array([[g[c] for c in cols] for g in te])
            m = LogisticRegression(max_iter=1000, C=0.5).fit(X, [g["y"] for g in tr])
            preds.extend(m.predict_proba(Xt)[:, 1])
            ys.extend(g["y"] for g in te)
        preds = np.clip(np.array(preds), 1e-6, 1 - 1e-6)
        ys = np.array(ys)
        print(f"{name:<20}{len(ys):>6}{((preds>0.5)==ys).mean():>8.4f}"
              f"{brier_score_loss(ys,preds):>9.4f}{log_loss(ys,preds):>9.4f}")


if __name__ == "__main__":
    main()
