"""Pen-exposure trial: does (expected bullpen innings x pen quality) add
signal over the model's probability? Point-in-time on the 2026 live sample.

exp_ip   = starter's mean IP over his last 5 starts BEFORE the game (hook proxy)
exposure = (9 - exp_ip) * pen_era7d   (innings the pen must cover, weighted by
                                       how bad the pen has been lately)
feature  = away_exposure - home_exposure
"""
import csv, re, sys, os, time
from glob import glob
import numpy as np
import requests
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

sys.stdout.reconfigure(errors="replace")
os.chdir(r"C:\Users\Poons\baseball-model")
from check_results import get_game_results

def f(x):
    m = re.search(r"-?\d+\.?\d*", str(x or ""))
    return float(m.group()) if m else None

# name -> mlbam id, one roster call
print("building roster map...")
_roster = {}
j = requests.get("https://statsapi.mlb.com/api/v1/sports/1/players",
                 params={"season": 2026}, timeout=60).json()
for p in j.get("people", []):
    _roster[p["fullName"]] = p["id"]
print(f"{len(_roster)} players")

def ip_float(s):
    try:
        w, _, frac = str(s).partition(".")
        return int(w) + int(frac or 0) / 3.0
    except ValueError:
        return None

_logs = {}
def starter_exp_ip(name, before_date):
    """Mean IP of last 5 starts before date. None if <3 starts."""
    pid = _roster.get(name)
    if not pid:
        return None
    if pid not in _logs:
        try:
            j = requests.get(f"https://statsapi.mlb.com/api/v1/people/{pid}/stats",
                params={"stats": "gameLog", "group": "pitching", "season": 2026},
                timeout=30).json()
            sp = j["stats"][0]["splits"]
            _logs[pid] = [(s["date"], ip_float(s["stat"].get("inningsPitched")),
                           int(s["stat"].get("gamesStarted", 0) or 0)) for s in sp]
        except Exception:
            _logs[pid] = []
        time.sleep(0.05)
    starts = [ip for d, ip, gs in _logs[pid]
              if gs and ip is not None and d < before_date]
    if len(starts) < 3:
        return None
    return sum(starts[-5:]) / len(starts[-5:])

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
        abp, hbp = f(row.get("Away BP ERA(7d)")), f(row.get("Home BP ERA(7d)"))
        if mp is None or abp is None or hbp is None:
            continue
        aip = starter_exp_ip(row.get("Away SP"), d)
        hip = starter_exp_ip(row.get("Home SP"), d)
        if aip is None or hip is None:
            continue
        mp = min(max(mp / 100, 0.02), 0.98)
        games.append(dict(
            d=d, y=1 if r["winner"] == h else 0,
            lg=np.log(mp / (1 - mp)),
            expo=(9 - aip) * abp - (9 - hip) * hbp,   # away minus home burden
            hook=hip - aip,                            # home starter goes deeper
        ))

print(f"{len(games)} games with model prob + exp-IP + pen data")
games.sort(key=lambda g: g["d"])
dates = sorted({g["d"] for g in games})
CONFIGS = {"model prob only": ["lg"],
           "model + pen exposure": ["lg", "expo"],
           "model + hook (exp IP diff)": ["lg", "hook"],
           "model + both": ["lg", "expo", "hook"]}
print(f"{'CONFIG':<28}{'n':>6}{'acc':>8}{'brier':>9}{'logloss':>9}")
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
    print(f"{name:<28}{len(ys):>6}{((preds>0.5)==ys).mean():>8.4f}"
          f"{brier_score_loss(ys, preds):>9.4f}{log_loss(ys, preds):>9.4f}")
