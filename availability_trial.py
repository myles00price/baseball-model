"""Bullpen AVAILABILITY trial (Trial B): does reliever workload/rest add
signal over the model's probability? Uses the new pen_usage.csv archive —
actual pitches thrown per arm per day, point-in-time by construction.

Features per team, computed from days BEFORE the game:
  burden2  = total reliever pitches thrown over the last 2 days
  tired    = # relievers unavailable-ish: threw 20+ pitches yesterday,
             or pitched back-to-back (both of the last 2 days)
  fresh_hi = # rested relievers (0 pitches last 2 days) among the team's
             top-usage arms (proxy for 'best arms available tonight')
Diffs are away - home. Incremental walk-forward vs stored model prob.
"""
import csv, re, sys, os
from glob import glob
from collections import defaultdict
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

sys.stdout.reconfigure(errors="replace")
os.chdir(r"C:\Users\Poons\baseball-model")
from check_results import get_game_results

def f(x):
    m = re.search(r"-?\d+\.?\d*", str(x or ""))
    return float(m.group()) if m else None

# pen_usage.csv -> per (team, date): {pid: pitches} for RELIEF appearances
usage = defaultdict(dict)          # (team, date) -> {pid: pitches}
appearances = defaultdict(int)     # (team, pid) -> total relief apps (for top-usage set)
for r in csv.DictReader(open("pen_usage.csv", encoding="utf-8-sig")):
    if r["started"] == "1":
        continue
    try:
        p = float(r["pitches"] or 0)
    except ValueError:
        p = 0.0
    usage[(r["team"], r["date"])][r["pid"]] = usage[(r["team"], r["date"])].get(r["pid"], 0) + p
    appearances[(r["team"], r["pid"])] += 1

teams = {t for t, _ in usage}
top_arms = {}  # team -> set of top-6 most used reliever pids (season)
for t in teams:
    arms = sorted(((n, pid) for (tm, pid), n in appearances.items() if tm == t), reverse=True)
    top_arms[t] = {pid for _, pid in arms[:6]}

def prior_days(d, n):
    import datetime
    dd = datetime.date.fromisoformat(d)
    return [(dd - datetime.timedelta(days=i)).isoformat() for i in range(1, n + 1)]

def team_metrics(team, d):
    d1, d2 = prior_days(d, 2)
    u1 = usage.get((team, d1), {})
    u2 = usage.get((team, d2), {})
    burden2 = sum(u1.values()) + sum(u2.values())
    tired = sum(1 for pid in set(u1) | set(u2)
                if u1.get(pid, 0) >= 20 or (pid in u1 and pid in u2))
    fresh_hi = sum(1 for pid in top_arms.get(team, ()) if pid not in u1 and pid not in u2)
    return burden2, tired, fresh_hi

games = []
for fn in sorted(glob("picks_2026-*.csv")):
    d = fn.replace("picks_", "").replace(".csv", "")
    try:
        R = get_game_results(d)
    except Exception:
        continue
    if not R:
        continue
    for row in csv.DictReader(open(fn, encoding="utf-8-sig")):
        a, h = row.get("Away"), row.get("Home")
        r = R.get(f"{a}@{h}")
        if not r:
            continue
        mp = f(row.get("Model Home%"))
        if mp is None or a not in teams or h not in teams:
            continue
        ab, at, af = team_metrics(a, d)
        hb, ht, hf = team_metrics(h, d)
        mp = min(max(mp / 100, 0.02), 0.98)
        games.append(dict(d=d, y=1 if r["winner"] == h else 0,
                          lg=np.log(mp / (1 - mp)),
                          burden=(ab - hb) / 10.0, tired=at - ht, fresh=af - hf))

print(f"{len(games)} games with model prob + availability data")
games.sort(key=lambda g: g["d"])
dates = sorted({g["d"] for g in games})
CONFIGS = {"model prob only": ["lg"],
           "model + burden (pitches 2d)": ["lg", "burden"],
           "model + tired arms": ["lg", "tired"],
           "model + fresh top arms": ["lg", "fresh"],
           "model + all availability": ["lg", "burden", "tired", "fresh"]}
print(f"{'CONFIG':<30}{'n':>6}{'acc':>8}{'brier':>9}{'logloss':>9}")
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
    print(f"{name:<30}{len(ys):>6}{((preds>0.5)==ys).mean():>8.4f}"
          f"{brier_score_loss(ys, preds):>9.4f}{log_loss(ys, preds):>9.4f}")
