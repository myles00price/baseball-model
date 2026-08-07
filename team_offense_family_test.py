"""
team_offense_family_test.py — family trial: team offense rate stats
(OBP, SLG, ISO, BABIP, BB%, SB) vs the OPS baseline.

Point-in-time via statsapi byDateRange (season start -> day before game),
2026 live sample, weekly walk-forward. Family screen only — any winner
still must beat the FULL model incrementally before adoption.

Run:  py -3.11 .\\team_offense_family_test.py
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

TID = {"Arizona Diamondbacks":109,"Atlanta Braves":144,"Baltimore Orioles":110,"Boston Red Sox":111,
"Chicago Cubs":112,"Chicago White Sox":145,"Cincinnati Reds":113,"Cleveland Guardians":114,
"Colorado Rockies":115,"Detroit Tigers":116,"Houston Astros":117,"Kansas City Royals":118,
"Los Angeles Angels":108,"Los Angeles Dodgers":119,"Miami Marlins":146,"Milwaukee Brewers":158,
"Minnesota Twins":142,"New York Mets":121,"New York Yankees":147,"Athletics":133,
"Philadelphia Phillies":143,"Pittsburgh Pirates":134,"San Diego Padres":135,"San Francisco Giants":137,
"Seattle Mariners":136,"St. Louis Cardinals":138,"Tampa Bay Rays":139,"Texas Rangers":140,
"Toronto Blue Jays":141,"Washington Nationals":120}

_cache = {}
def team_stats_before(team, date):
    key = (team, date)
    if key in _cache:
        return _cache[key]
    tid = TID.get(team)
    if not tid:
        _cache[key] = None
        return None
    try:
        j = requests.get(f"https://statsapi.mlb.com/api/v1/teams/{tid}/stats",
                         params={"stats": "byDateRange", "group": "hitting", "season": 2026,
                                 "startDate": "2026-03-25", "endDate": date},
                         timeout=30).json()
        st = j["stats"][0]["splits"][0]["stat"]
        pa = float(st.get("plateAppearances", 0) or 0)
        out = {
            "obp": float(st.get("obp", 0) or 0),
            "slg": float(st.get("slg", 0) or 0),
            "ops": float(st.get("ops", 0) or 0),
            "iso": float(st.get("slg", 0) or 0) - float(st.get("avg", 0) or 0),
            "babip": float(st.get("babip", 0) or 0),
            "bbr": float(st.get("baseOnBalls", 0) or 0) / pa if pa else 0,
            "sb": float(st.get("stolenBases", 0) or 0) / pa * 100 if pa else 0,
        }
        _cache[key] = out
    except Exception:
        _cache[key] = None
    time.sleep(0.05)
    return _cache[key]


def prior_date(d):
    import datetime
    return (datetime.date.fromisoformat(d) - datetime.timedelta(days=1)).isoformat()


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
            sa = team_stats_before(a, pd_)
            sh = team_stats_before(h, pd_)
            if not sa or not sh or sa["ops"] == 0 or sh["ops"] == 0:
                continue
            g = {"d": d, "y": 1 if r["winner"] == h else 0}
            for k in ("obp", "slg", "ops", "iso", "babip", "bbr", "sb"):
                g[k] = sh[k] - sa[k]
            games.append(g)
    print(f"{len(games)} point-in-time games built")
    games.sort(key=lambda g: g["d"])
    dates = sorted({g["d"] for g in games})

    CONFIGS = {
        "OPS only (baseline)": ["ops"],
        "OBP + SLG": ["obp", "slg"],
        "ISO + BABIP": ["iso", "babip"],
        "BB% + SB": ["bbr", "sb"],
        "full family": ["obp", "slg", "iso", "babip", "bbr", "sb"],
        "OPS + BABIP": ["ops", "babip"],
        "OPS + BB% + SB": ["ops", "bbr", "sb"],
    }
    print(f"{'CONFIG':<22}{'n':>6}{'acc':>8}{'brier':>9}{'logloss':>9}")
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
        print(f"{name:<22}{len(ys):>6}{((preds>0.5)==ys).mean():>8.4f}"
              f"{brier_score_loss(ys,preds):>9.4f}{log_loss(ys,preds):>9.4f}")


if __name__ == "__main__":
    main()
