"""
gen_analytics.py — builds board_analytics.json for board.html's LEDGER section.

Aggregates the graded season: V2 daily results + equity curve, season flagged
totals, value-dog vs aligned splits, team analytics, and de-vig edge buckets.
Called by daily_results_notify.py after each nightly grade (and runnable
standalone).
"""

import csv
import json
import sys
import time
from collections import defaultdict
from glob import glob

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from weekly_report import gather, V2_LAUNCH, payout
from check_results import get_game_results
from features_v2 import BET_MIN, BET_MAX


def implied(o):
    o = float(o)
    return (-o) / (-o + 100) * 100 if o < 0 else 100 / (o + 100) * 100


BUCKETS = (("0-3", 0, 3), ("3-6", 3, 6), ("6-10", 6, 10), ("10+", 10, 999))


def main():
    games = gather()

    # V2 daily + equity
    daily = defaultdict(lambda: {"pw": 0, "pt": 0, "bw": 0, "bt": 0, "pnl": 0.0})
    for g in games:
        if g["date"] < V2_LAUNCH:
            continue
        d = daily[g["date"]]
        d["pt"] += 1; d["pw"] += g["pick_won"]
        if g["bet_team"]:
            d["bt"] += 1; d["bw"] += bool(g["bet_won"]); d["pnl"] += g["bet_profit"]
    days = []
    cum = 0.0
    for dt in sorted(daily):
        d = daily[dt]
        cum += d["pnl"]
        days.append({"d": dt[5:], "pw": d["pw"], "pt": d["pt"],
                     "bw": d["bw"], "bl": d["bt"] - d["bw"],
                     "pnl": round(d["pnl"]), "cum": round(cum)})

    # splits
    def split(gs):
        out = {}
        for name, sub in (("dog", [g for g in gs if g["bet_team"] and g["bet_team"] != g["pick"]]),
                          ("aligned", [g for g in gs if g["bet_team"] and g["bet_team"] == g["pick"]])):
            w = sum(1 for g in sub if g["bet_won"])
            out[name] = {"w": w, "l": len(sub) - w,
                         "pnl": round(sum(g["bet_profit"] for g in sub))}
        return out

    v2games = [g for g in games if g["date"] >= V2_LAUNCH]
    sb = [g for g in games if g["bet_team"]]
    sb_w = sum(1 for g in sb if g["bet_won"])

    # teams
    picked = defaultdict(lambda: [0, 0]); bet_on = defaultdict(lambda: [0, 0])
    for g in games:
        picked[g["pick"]][1] += 1; picked[g["pick"]][0] += g["pick_won"]
        if g["bet_team"]:
            bet_on[g["bet_team"]][1] += 1; bet_on[g["bet_team"]][0] += bool(g["bet_won"])
    # full per-team model record (for board team pages)
    model_teams = {}
    for tm in set(list(picked.keys()) + list(bet_on.keys())):
        pw, pt = picked.get(tm, [0, 0])
        bw, bt = bet_on.get(tm, [0, 0])
        model_teams[tm] = {"pw": pw, "pt": pt, "bw": bw, "bl": bt - bw}

    rank = sorted(((c / t, c, t, tm) for tm, (c, t) in picked.items() if t >= 8), reverse=True)
    teams = {
        "best": [{"t": tm, "w": c, "n": t} for _, c, t, tm in rank[:5]],
        "worst": [{"t": tm, "w": c, "n": t} for _, c, t, tm in rank[-5:]],
        "most_bet": [{"t": tm, "w": w, "l": t - w}
                     for tm, (w, t) in sorted(bet_on.items(), key=lambda kv: -kv[1][1])[:6]],
    }

    # de-vig edge buckets (value side at DK, no gates)
    ebuckets = {b[0]: [0, 0, 0.0] for b in BUCKETS}
    # extra flagged-bet splits: side, price band, sharp signal
    from features_v2 import flagged_side, is_bet
    from master_v2 import bet_side_ok
    xsplits = {k: [0, 0, 0.0] for k in
               ("home", "away", "fav-155", "fav", "dog", "dog+150",
                "sharp-conf", "sharp-na", "veto-would")}

    def _f(x):
        import re as _re
        m = _re.search(r"-?\d+\.?\d*", str(x or ""))
        return float(m.group()) if m else None

    def _xadd(k, won, profit):
        s = xsplits[k]; s[0] += 1; s[1] += won; s[2] += profit
    for f in sorted(glob("picks_2026-*.csv")):
        dt = f.replace("picks_", "").replace(".csv", "")
        try:
            results = get_game_results(dt)
        except Exception:
            continue
        if not results:
            continue
        time.sleep(0.15)
        for row in csv.DictReader(open(f, encoding="utf-8-sig")):
            ap, hp = row.get("Model Away%"), row.get("Model Home%")
            if ap in (None, "None", "") or hp in (None, "None", ""):
                continue
            a, h = row["Away"], row["Home"]
            res = results.get(f"{a}@{h}")
            if not res:
                continue
            try:
                ao, ho = float(row["DK Away Odds"]), float(row["DK Home Odds"])
            except (ValueError, TypeError):
                continue
            ia, ih = implied(ao), implied(ho)
            tot = ia + ih
            xa, xh = ia / tot * 100, ih / tot * 100
            ea, eh = float(ap) - xa, float(hp) - xh
            side, edge, odds = ("away", ea, ao) if ea >= eh else ("home", eh, ho)
            for name, lo, hi in BUCKETS:
                if lo <= edge < hi:
                    team = a if side == "away" else h
                    won = team == res["winner"]
                    s = ebuckets[name]
                    s[0] += 1; s[1] += won
                    s[2] += payout(odds) if won else -100.0
                    break

            # flagged-bet extra splits
            if "BET" in str(row.get("Flag", "")):
                fs = flagged_side(row)
                if fs:
                    bt = a if fs == "away" else h
                    bo = ao if fs == "away" else ho
                    bwon = bt == res["winner"]
                    bprofit = payout(bo) if bwon else -100.0
                    _xadd("away" if fs == "away" else "home", bwon, bprofit)
                    band = ("fav-155" if bo <= -155 else "fav" if bo < 100
                            else "dog+150" if bo >= 150 else "dog")
                    _xadd(band, bwon, bprofit)
                    sh = str(row.get("Sharp Signal", ""))
                    _xadd("sharp-conf" if "CONFIRMED" in sh else "sharp-na", bwon, bprofit)

            # phantom ledger: bets the sharp FADE veto suppressed (live era) —
            # tracks whether the veto keeps paying for itself
            if (dt >= V2_LAUNCH and "FADE" in str(row.get("Sharp Signal", ""))
                    and "BET" not in str(row.get("Flag", "")) and h != "Colorado Rockies"):
                arel, hrel = _f(row.get("Away Reliability%")), _f(row.get("Home Reliability%"))
                awhf, hwhf = _f(row.get("Away SP Whiff")), _f(row.get("Home SP Whiff"))
                for side in ("away", "home"):
                    e1 = _f(row.get("DK Edge Away") if side == "away" else row.get("DK Edge Home"))
                    e2 = _f(row.get("MGM Edge Away") if side == "away" else row.get("MGM Edge Home"))
                    if not ((e1 is not None and is_bet(e1)) or (e2 is not None and is_bet(e2))):
                        continue
                    brel, orel, owhf = (arel, hrel, hwhf) if side == "away" else (hrel, arel, awhf)
                    if brel is None or orel is None or not bet_side_ok(brel, orel, owhf):
                        continue
                    podds = ao if side == "away" else ho
                    pteam = a if side == "away" else h
                    pwon = pteam == res["winner"]
                    _xadd("veto-would", pwon, payout(podds) if pwon else -100.0)
                    break

    # F5 shadow ledger (paper only — see f5_shadow.py)
    try:
        import f5_shadow
        f5 = f5_shadow.grade_all()
    except Exception as e:
        print(f"F5 shadow grading skipped: {e}")
        f5 = None

    out = {
        "days": days,
        "f5_shadow": f5,
        "season_flagged": {"w": sb_w, "l": len(sb) - sb_w,
                           "pnl": round(sum(g["bet_profit"] for g in sb))},
        "split_season": split(games), "split_v2": split(v2games),
        "teams": teams,
        "model_teams": model_teams,
        "buckets": [{"b": n, "n": v[0], "w": v[1], "pnl": round(v[2])}
                    for n, v in ebuckets.items()],
        "xsplits": {k: {"n": v[0], "w": v[1], "pnl": round(v[2])}
                    for k, v in xsplits.items()},
        "wf": {"months": ["25-03","25-04","25-05","25-06","25-07","25-08","25-09","26-04","26-05","26-06"],
               "old": [62.7,61.8,56.7,57.3,54.9,59.4,58.6,58.1,62.7,55.8],
               "v2":  [64.2,63.4,58.1,58.3,56.8,58.0,60.5,63.3,64.4,58.1]},
    }
    with open("board_analytics.json", "w") as f:
        json.dump(out, f)
    print(f"board_analytics.json written: {len(days)} days, {len(sb)} season bets")


if __name__ == "__main__":
    main()
