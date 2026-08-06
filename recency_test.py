"""
recency_test.py — does recency-weighting pitcher form beat season-to-date?
(User idea 2026-08-06: WMA on pitcher stats, weighting recent starts.)

Built on the 2026 live sample (picks CSVs since 4/17: starter NAMES known),
with TRUE point-in-time features from game logs — only starts strictly
before each game count. Weekly walk-forward, identical rows per config.

Run:  py -3.11 .\\recency_test.py
"""

import csv
import sys
import time
from datetime import datetime
from glob import glob

import numpy as np
import requests
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from check_results import get_game_results


def parse_ip(v):
    try:
        s = str(v)
        if "." in s:
            w, f = s.split(".")
            return int(w) + {"0": 0, "1": 1 / 3, "2": 2 / 3}.get(f, 0)
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def roster_map():
    j = requests.get("https://statsapi.mlb.com/api/v1/sports/1/players",
                     params={"season": 2026, "fields": "people,id,fullName"},
                     timeout=60).json()
    return {p["fullName"]: p["id"] for p in j.get("people", [])}


_logs = {}
def game_log(pid):
    if pid in _logs:
        return _logs[pid]
    try:
        j = requests.get(f"https://statsapi.mlb.com/api/v1/people/{pid}/stats",
                         params={"stats": "gameLog", "season": 2026, "group": "pitching"},
                         timeout=30).json()
        rows = []
        for sp in j["stats"][0]["splits"]:
            st = sp.get("stat", {})
            ip = parse_ip(st.get("inningsPitched", 0))
            if ip <= 0:
                continue
            rows.append((sp["date"], ip, float(st.get("earnedRuns", 0))))
        rows.sort()
        _logs[pid] = rows
    except Exception:
        _logs[pid] = []
    time.sleep(0.08)
    return _logs[pid]


def eras_before(pid, date, min_starts=3):
    """(season_td, last5, decay) ERA using only starts strictly before date."""
    prior = [(ip, er) for d, ip, er in game_log(pid) if d < date]
    if len(prior) < min_starts:
        return None
    def era(pairs):
        ip = sum(p[0] for p in pairs)
        return 9 * sum(p[1] for p in pairs) / ip if ip > 0 else None
    season = era(prior)
    last5 = era(prior[-5:])
    # exponential decay, halflife 3 starts
    w = [0.5 ** ((len(prior) - 1 - i) / 3) for i in range(len(prior))]
    dip = sum(wi * p[0] for wi, p in zip(w, prior))
    der = sum(wi * p[1] for wi, p in zip(w, prior))
    decay = 9 * der / dip if dip > 0 else None
    return season, last5, decay


def main():
    names = roster_map()
    print(f"roster map: {len(names)} players")
    games = []
    for f in sorted(glob("picks_2026-*.csv")):
        d = f.replace("picks_", "").replace(".csv", "")
        if d > "2026-08-05":
            continue
        try:
            R = get_game_results(d)
        except Exception:
            continue
        if not R:
            continue
        time.sleep(0.08)
        for row in csv.DictReader(open(f, encoding="utf-8-sig")):
            a, h = row["Away"], row["Home"]
            res = R.get(f"{a}@{h}")
            asp, hsp = row.get("Away SP", ""), row.get("Home SP", "")
            if not res or asp in ("", "TBD") or hsp in ("", "TBD"):
                continue
            aid, hid = names.get(asp), names.get(hsp)
            if not aid or not hid:
                continue
            ea = eras_before(aid, d)
            eh = eras_before(hid, d)
            if not ea or not eh or None in ea or None in eh:
                continue
            clip = lambda x: min(max(x, 1.5), 8.0)
            games.append({
                "d": d, "y": 1 if res["winner"] == h else 0,
                "season": clip(ea[0]) - clip(eh[0]),
                "last5": clip(ea[1]) - clip(eh[1]),
                "decay": clip(ea[2]) - clip(eh[2]),
            })
    print(f"{len(games)} point-in-time games built\n")
    games.sort(key=lambda g: g["d"])
    dates = sorted({g["d"] for g in games})
    # weekly walk-forward: predict each date using all prior dates, once >=150 train rows
    CONFIGS = {"season-to-date": ["season"], "last-5 starts": ["last5"],
               "decay (hl=3)": ["decay"], "season+last5": ["season", "last5"],
               "season+decay": ["season", "decay"]}
    print(f"{'CONFIG':<16}{'n':>6}{'acc':>8}{'brier':>9}{'logloss':>9}")
    base = None
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
        acc = float(((preds > 0.5) == ys).mean())
        br = brier_score_loss(ys, preds)
        ll = log_loss(ys, preds)
        if name == "season-to-date":
            base = (acc, br)
        print(f"{name:<16}{len(ys):>6}{acc:>8.4f}{br:>9.4f}{ll:>9.4f}")
    if base:
        print("\n(sample is ~10x smaller than the main gauntlet — treat close calls as ties)")


if __name__ == "__main__":
    main()
