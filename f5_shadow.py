"""
f5_shadow.py — First-5-innings SHADOW pipeline. PAPER ONLY.

Why: the model's four features handicap starters, and starters pitch the
first five innings. Scored against 683 live slate games the model called
F5 winners at 57.7% vs 53.2% for full games. But F5 markets are priced off
the same starter stats and carry ~1pt more vig, so the idea must prove
itself against real prices before a dollar or a text moves. Same discipline
as the de-vig shadow (whose backtest said +8.6% and whose live ledger said
no — the reason this file exists in shadow form).

What it does, per master_v2 run:
  - predicts P(home leads after 5 | not tied) with model_f5.pkl
    (same 4 features, trained on F5 outcomes by train_f5.py)
  - pulls F5 moneylines (DK/FD/MGM/CZR) — 1 API credit per unlocked game
  - logs de-vig edges + a would-be flag (same inherited bet window, same reliability
    gates + Coors + sharp veto as the real model) to f5_shadow_<date>.json
  - rows lock when the game locks (texted/live/final) — last pre-lock
    snapshot is the shadow bet, mirroring lock-on-text
Graded nightly by gen_analytics via grade_all(); rendered on the board.
NEVER texts subscribers. NEVER flags real plays.
"""

import json
import os
import pickle
import sys
import time

import numpy as np
import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from features_v2 import (build_feature_vector, is_bet, PROB_LO, PROB_HI,
                         commence_lv_date)

F5_MODEL_FILE = "model_f5.pkl"
F5_SCALER_FILE = "scaler_f5.pkl"
F5_BOOKS = "draftkings,fanduel,betmgm,williamhill_us"
SAMPLE_TARGET = 50  # revisit switch decision here (50-100 shadow flags)

_cache = {}


def load_f5():
    if "m" not in _cache:
        with open(F5_MODEL_FILE, "rb") as f:
            _cache["m"] = pickle.load(f)
        with open(F5_SCALER_FILE, "rb") as f:
            _cache["s"] = pickle.load(f)
    return _cache["m"], _cache["s"]


def f5_available():
    return os.path.exists(F5_MODEL_FILE) and os.path.exists(F5_SCALER_FILE)


def predict_f5_home_prob(home_era, home_whip, away_era, away_whip,
                         home_ops, home_kpct, away_ops, away_kpct):
    """P(home leads after 5 | not tied), 0-100. Calibrated; no post-hoc layers."""
    model, scaler = load_f5()
    X = build_feature_vector(home_era, home_whip, away_era, away_whip,
                             home_ops, home_kpct, away_ops, away_kpct)
    p = model.predict_proba(scaler.transform(X))[0][1]
    return round(max(PROB_LO, min(PROB_HI, p)) * 100, 1)


def fetch_f5_odds(event_id):
    """F5 moneylines for one event. 1 credit. Returns {book: {team: price}}."""
    r = requests.get(
        f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds",
        params={"apiKey": os.environ["ODDS_API_KEY"], "regions": "us",
                "markets": "h2h_1st_5_innings", "oddsFormat": "american",
                "bookmakers": F5_BOOKS},
        timeout=20)
    j = r.json()
    out = {}
    for bk in j.get("bookmakers", []):
        for mk in bk.get("markets", []):
            if mk["key"] != "h2h_1st_5_innings":
                continue
            out[bk["key"]] = {o["name"]: o["price"] for o in mk["outcomes"]}
    return out


def event_id_map(odds_resp, target_str):
    """Map 'Away@Home' -> event id from the main odds response (free).
    Doubleheaders: the matchup has two events; keep them ordered by start so
    'Away@Home' -> game 1 and 'Away@Home#2' -> game 2 (matches game_key)."""
    grouped = {}
    for game in odds_resp:
        if commence_lv_date(game.get("commence_time")) != target_str:
            continue
        grouped.setdefault(f"{game['away_team']}@{game['home_team']}", []).append(game)
    out = {}
    for k, evs in grouped.items():
        evs.sort(key=lambda g: str(g.get("commence_time")))
        for i, g in enumerate(evs):
            out[k + (f"#{i+1}" if i > 0 else "")] = g["id"]
    return out


def _implied(o):
    o = float(o)
    return (-o) / (-o + 100) * 100 if o < 0 else 100 / (o + 100) * 100


def shadow_path(date_str):
    return f"f5_shadow_{date_str}.json"


def load_shadow(date_str):
    try:
        with open(shadow_path(date_str)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def capture(date_str, game_key, event_id, away, home, f5_home_prob,
            reliable_away, reliable_home, frozen):
    """Update one game's shadow row (skips locked rows). Returns row or None."""
    rows = _cache.setdefault(("rows", date_str), load_shadow(date_str))
    row = rows.get(game_key)
    if row and row.get("locked"):
        return row
    if frozen:
        if row:
            row["locked"] = True
        return row
    if event_id is None or f5_home_prob is None:
        return row
    try:
        odds = fetch_f5_odds(event_id)
        time.sleep(0.05)
    except Exception:
        return row
    if not odds:
        return row
    f5_away_prob = round(100 - f5_home_prob, 1)
    best_a = best_h = None
    dv_a, dv_h = [], []
    for bk, o in odds.items():
        oa, oh = o.get(away), o.get(home)
        if oa is None or oh is None:
            continue
        ia, ih = _implied(oa), _implied(oh)
        tot = ia + ih
        dv_a.append(f5_away_prob - ia / tot * 100)
        dv_h.append(f5_home_prob - ih / tot * 100)
        if best_a is None or oa > best_a[1]:
            best_a = [bk, oa]
        if best_h is None or oh > best_h[1]:
            best_h = [bk, oh]
    if not dv_a:
        return row
    edge_a, edge_h = round(max(dv_a), 1), round(max(dv_h), 1)
    flag = ""
    if is_bet(edge_a) and reliable_away:
        flag = "away"
    elif is_bet(edge_h) and reliable_home:
        flag = "home"
    rows[game_key] = {"away": away, "home": home, "prob_home": f5_home_prob,
                      "odds": odds, "best_away": best_a, "best_home": best_h,
                      "dv_edge_away": edge_a, "dv_edge_home": edge_h,
                      "flag": flag, "locked": False}
    return rows[game_key]


def save(date_str):
    rows = _cache.get(("rows", date_str))
    if rows is None:
        return
    with open(shadow_path(date_str), "w") as f:
        json.dump(rows, f, indent=1)
    flags = sum(1 for r in rows.values() if r.get("flag"))
    print(f"F5 shadow: {len(rows)} games logged, {flags} would-be flag(s) "
          f"-> {shadow_path(date_str)}")


def lock_key(date_str, game_key):
    """Hard-lock one game's F5 row at the moment its real play texts.
    Called by notify_pick so the paper bet freezes on the SAME lineup-lock
    evaluation as the official play (notify_pick reruns master with
    confirmed lineups just before texting). Pre-lineup flags that did not
    survive that evaluation are already gone from the row - they drop off
    the site and never enter the ledger."""
    rows = load_shadow(date_str)
    if game_key in rows and not rows[game_key].get("locked"):
        rows[game_key]["locked"] = True
        with open(shadow_path(date_str), "w") as f:
            json.dump(rows, f, indent=1)
        # keep any in-process cache coherent
        c = _cache.get(("rows", date_str))
        if c is not None and game_key in c:
            c[game_key]["locked"] = True


# ── grading ──────────────────────────────────────────────────────────

def f5_results(date_str):
    """{'Away@Home': 'away'|'home'|'tie'} for finals with 5+ innings."""
    j = requests.get("https://statsapi.mlb.com/api/v1/schedule",
                     params={"sportId": 1, "date": date_str,
                             "hydrate": "linescore"}, timeout=30).json()
    out = {}
    for dd in j.get("dates", []):
        for g in dd.get("games", []):
            if g.get("status", {}).get("codedGameState") != "F":
                continue
            inns = g.get("linescore", {}).get("innings", [])
            if len(inns) < 5:
                continue
            a5 = sum(x.get("away", {}).get("runs", 0) or 0 for x in inns[:5])
            h5 = sum(x.get("home", {}).get("runs", 0) or 0 for x in inns[:5])
            from features_v2 import key_from_sched as _kfs
            k = _kfs(g)   # DH-safe: game 2 -> 'Away@Home#2' (audit 2026-08-27:
                          # bare keys graded game-1 F5 vs whichever game came last
                          # and never graded a locked game-2 flag)
            out[k] = "tie" if a5 == h5 else ("home" if h5 > a5 else "away")
    return out


def _payout(o):
    o = float(o)
    return o if o > 0 else 10000.0 / abs(o)


F5_BUCKETS = (("0-3", 0, 3), ("3-5", 3, 5), ("5-8", 5, 8),
              ("8-12", 8, 12), ("12+", 12, 999))


def grade_all():
    """Grade the paper ledger. Two views, LOCKED (lineup-confirmed) rows only:
      - headline: flags inside the inherited bet window (the paper 'plays')
      - buckets:  EVERY locked game's best-edge side graded by edge size,
                  so F5 can reveal its OWN best window instead of assuming
                  the full-game one transfers."""
    from glob import glob
    w = l = push = 0
    pnl = 0.0
    bets = []
    buckets = {b[0]: [0, 0, 0, 0.0] for b in F5_BUCKETS}  # w, l, push, pnl
    for fn in sorted(glob("f5_shadow_2026-*.json")):
        d = fn.replace("f5_shadow_", "").replace(".json", "")
        try:
            rows = json.load(open(fn))
        except (OSError, ValueError):
            continue
        res = None
        for k, r in rows.items():
            if not r.get("locked"):
                continue
            ea, eh = r.get("dv_edge_away"), r.get("dv_edge_home")
            if ea is None or eh is None:
                continue
            if res is None:
                try:
                    res = f5_results(d)
                    time.sleep(0.1)
                except Exception:
                    break
            out = res.get(k)
            if out is None:
                continue

            def settle(side):
                best = r.get("best_away") if side == "away" else r.get("best_home")
                if not best:
                    return None
                if out == "tie":
                    return "P", 0.0, best
                if out == side:
                    return "W", _payout(best[1]), best
                return "L", -100.0, best

            # bucket view: best-edge side of every locked game
            side_b, edge_b = ("away", ea) if ea >= eh else ("home", eh)
            if edge_b > 0:
                s = settle(side_b)
                if s:
                    gr, pr, _ = s
                    for name, lo, hi in F5_BUCKETS:
                        if lo <= edge_b < hi:
                            bk = buckets[name]
                            bk[0] += gr == "W"; bk[1] += gr == "L"
                            bk[2] += gr == "P"; bk[3] += pr
                            break

            # headline ledger: in-window flags only
            if not r.get("flag"):
                continue
            side = r["flag"]
            s = settle(side)
            if not s:
                continue
            gr, pr, best = s
            if gr == "W":
                w += 1
            elif gr == "L":
                l += 1
            else:
                push += 1
            pnl += pr
            bets.append({"d": d, "t": r["away"] if side == "away" else r["home"],
                         "o": best[1], "bk": best[0],
                         "e": ea if side == "away" else eh,
                         "r": gr, "p": round(pr)})
    n = w + l
    return {"w": w, "l": l, "push": push, "pnl": round(pnl),
            "roi": round(pnl / ((n + push) * 100) * 100, 1) if (n + push) else 0.0,
            "target": SAMPLE_TARGET, "recent": bets[-12:],
            "buckets": [{"b": name, "w": v[0], "l": v[1], "push": v[2],
                         "pnl": round(v[3])} for name, v in buckets.items()]}


if __name__ == "__main__":
    print(json.dumps(grade_all(), indent=1))
