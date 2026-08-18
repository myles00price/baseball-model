"""
props_analytics.py — the PROPS LEDGER: full-game-style analytics for the
three prop watches (Long Ball / Hit / K), built from their self-graded
training archives. Display-only, like the watches themselves.

Per product:
  - calibration by predicted-probability bucket (predicted vs actual)
  - top-N hit rate (the board's published list) with running streaks
  - home / away splits (batter's home status; pitcher's home status)
  - best / worst players WITH THE MODEL: who beats their model number
    most (min-sample gated), who falls short most
  - hit streaks: current consecutive-day streaks among top-listed players
  - vs-market: model fair vs best book price, graded at flat $100 (paper)

Output: props_analytics.json (board reads it). Called nightly from
daily_results_notify.py after the graders; runnable standalone.
"""

import csv
import json
import os
import sys
from collections import defaultdict

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

MIN_PLAYER_N = 5      # min graded appearances for best/worst lists
TOP_N = 15            # the board's published list depth (HR/Hit)


def f(x):
    try:
        v = float(str(x).replace("%", "").replace("+", ""))
        return v
    except (TypeError, ValueError):
        return None


def payout(o):
    o = float(o)
    return o if o > 0 else 10000.0 / abs(o)


def load(fn, prob_keys=()):
    """Load an archive; normalize probability columns to 0-1 fractions
    (the HR/Hit logs store some as percentages)."""
    if not os.path.exists(fn):
        return []
    with open(fn, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for k in prob_keys:
        vals = [f(r.get(k)) for r in rows]
        vals = [v for v in vals if v is not None]
        if vals and max(vals) > 1.0:
            for r in rows:
                v = f(r.get(k))
                if v is not None:
                    r[k] = v / 100.0
    return rows


def calib(rows, pkey, ykey, edges=(0, .05, .10, .15, .20, .30, 1.01)):
    out = []
    for lo, hi in zip(edges, edges[1:]):
        sub = [r for r in rows if f(r.get(pkey)) is not None and lo <= f(r[pkey]) < hi]
        if not sub:
            continue
        pred = sum(f(r[pkey]) for r in sub) / len(sub)
        act = sum(int(f(r[ykey]) or 0) for r in sub) / len(sub)
        out.append({"b": f"{lo*100:.0f}-{min(hi,1)*100:.0f}%", "n": len(sub),
                    "pred": round(pred * 100, 1), "act": round(act * 100, 1)})
    return out


def streaks(rows, ykey, datekey="date", namekey="name"):
    """Current consecutive-day 'yes' streak per player (any played row)."""
    by = defaultdict(list)
    for r in rows:
        by[r[namekey]].append((r[datekey], int(f(r.get(ykey)) or 0)))
    out = []
    for nm, seq in by.items():
        seq.sort()
        s = 0
        for _, y in reversed(seq):
            if y:
                s += 1
            else:
                break
        if s >= 2:
            out.append({"t": nm, "s": s, "last": seq[-1][0][5:]})
    return sorted(out, key=lambda x: -x["s"])[:8]


def player_table(rows, pkey, ykey, namekey="name", teamkey="team", label_pos=True):
    """Best/worst vs model: actual rate minus predicted rate, min sample."""
    agg = defaultdict(lambda: [0, 0.0, 0, ""])  # n, sum p, sum y, team
    for r in rows:
        p = f(r.get(pkey))
        if p is None:
            continue
        a = agg[r[namekey]]
        a[0] += 1; a[1] += p; a[2] += int(f(r.get(ykey)) or 0); a[3] = r.get(teamkey, "")
    tbl = []
    for nm, (n, sp, sy, tm) in agg.items():
        if n < MIN_PLAYER_N:
            continue
        tbl.append({"t": nm, "tm": tm, "n": n, "pred": round(sp / n * 100, 1),
                    "act": round(sy / n * 100, 1), "y": sy,
                    "d": round((sy / n - sp / n) * 100, 1)})
    tbl.sort(key=lambda x: -x["d"])
    return {"best": tbl[:6], "worst": list(reversed(tbl[-6:]))}


def side_split(rows, pkey, ykey, homekey="home"):
    out = {}
    for lab, want in (("home", "1"), ("away", "0")):
        sub = [r for r in rows if str(r.get(homekey)) == want and f(r.get(pkey)) is not None]
        if not sub:
            continue
        out[lab] = {"n": len(sub),
                    "pred": round(sum(f(r[pkey]) for r in sub) / len(sub) * 100, 1),
                    "act": round(sum(int(f(r[ykey]) or 0) for r in sub) / len(sub) * 100, 1)}
    return out


def top_n_daily(rows, pkey, ykey, n=TOP_N):
    """Per date, take the top-N by model p among played rows: hits, and streak
    of consecutive days with >=1 hit in the published list."""
    by = defaultdict(list)
    for r in rows:
        if f(r.get(pkey)) is not None:
            by[r["date"]].append(r)
    days = []
    for d in sorted(by):
        top = sorted(by[d], key=lambda r: -f(r[pkey]))[:n]
        played = [r for r in top if str(r.get("played", "1")) != "0"]
        hits = sum(int(f(r.get(ykey)) or 0) for r in played)
        exp = sum(f(r[pkey]) for r in played)
        days.append({"d": d[5:], "n": len(played), "hits": hits, "exp": round(exp, 1)})
    cur = 0
    for dday in reversed(days):
        if dday["hits"] > 0:
            cur += 1
        else:
            break
    tot_h = sum(x["hits"] for x in days); tot_e = sum(x["exp"] for x in days)
    tot_n = sum(x["n"] for x in days)
    return {"days": days[-10:], "list_streak": cur, "hits": tot_h,
            "exp": round(tot_e, 1), "n": tot_n}


EDGE_BUCKETS = (("<0", -99, 0), ("0-3", 0, 3), ("3-6", 3, 6), ("6-10", 6, 10), ("10+", 10, 999))


def _imp(o):
    return (-o) / (-o + 100) if o < 0 else 100 / (o + 100)


def edge_buckets(rows, pkey, ykey, odds_keys, under_key=None):
    """FIND ITS OWN ZONE: bucket every graded row by (model p - best-book
    implied) in points; per bucket: n, hits, hit rate, expected hits, and
    flat-$100 paper P&L on 'yes' at the best price. This is how the display
    lean threshold earns its number instead of being hand-picked.

    under_key: when the row carries the opposite side's price (DK posts
    Under 0.5 on batter_hits), the book's implied is DE-VIGGED:
    imp_yes / (imp_yes + imp_no). Otherwise raw implied (edge understated)."""
    out = {b[0]: [0, 0, 0.0, 0.0] for b in EDGE_BUCKETS}  # n, hits, sum p, pnl
    for r in rows:
        p = f(r.get(pkey))
        if p is None or str(r.get("played", "1")) == "0":
            continue
        best = None
        for k in odds_keys:
            o = f(r.get(k))
            if o is not None and (best is None or o > best):
                best = o
        if best is None:
            continue
        imp = _imp(best)
        u = f(r.get(under_key)) if under_key else None
        dk = f(r.get("odds_dk")) if under_key else None
        if u is not None and dk is not None:
            # de-vig off DK's two-sided price, then apply the same hold to the
            # best book's price (books' holds are near-identical on this market)
            hold = _imp(dk) + _imp(u)
            imp = imp / hold if hold > 0 else imp
        e = (p - imp) * 100
        y = int(f(r.get(ykey)) or 0)
        for name, lo, hi in EDGE_BUCKETS:
            if lo <= e < hi:
                b = out[name]
                b[0] += 1; b[1] += y; b[2] += p
                b[3] += payout(best) if y else -100.0
                break
    return [{"b": n, "n": v[0], "hits": v[1], "exp": round(v[2], 1),
             "rate": round(v[1] / v[0] * 100, 1) if v[0] else 0.0,
             "pnl": round(v[3])} for n, v in out.items() if v[0]]


def market_paper(rows, pkey, ykey, odds_keys, thresh=0.03):
    """Flat $100 paper on 'yes' whenever model p exceeds best-book de-vig
    implied by >= thresh (one-sided market: raw implied). Display-only."""
    w = l = 0; pnl = 0.0
    for r in rows:
        p = f(r.get(pkey))
        if p is None or str(r.get("played", "1")) == "0":
            continue
        best = None
        for k in odds_keys:
            o = f(r.get(k))
            if o is None:
                continue
            if best is None or o > best:
                best = o
        if best is None:
            continue
        imp = (-best) / (-best + 100) if best < 0 else 100 / (best + 100)
        if p - imp < thresh:
            continue
        y = int(f(r.get(ykey)) or 0)
        w += y; l += (1 - y)
        pnl += payout(best) if y else -100.0
    return {"w": w, "l": l, "pnl": round(pnl),
            "roi": round(pnl / ((w + l) * 100) * 100, 1) if w + l else 0.0}


def build_hr():
    rows = [r for r in load("hr_training_data.csv", ("p",)) if str(r.get("played", "1")) != "0"]
    if not rows:
        return None
    return {
        "days": len({r["date"] for r in rows}), "n": len(rows),
        "calib": calib(rows, "p", "hr_yes"),
        "topn": top_n_daily(rows, "p", "hr_yes"),
        "sides": side_split(rows, "p", "hr_yes"),
        "players": player_table(rows, "p", "hr_yes"),
        "streaks": streaks(rows, "hr_yes"),
        "paper": market_paper(rows, "p", "hr_yes", ("odds_dk", "odds_mgm", "odds_czr")),
        "ebuckets": edge_buckets(rows, "p", "hr_yes", ("odds_dk", "odds_mgm", "odds_czr")),
    }


def build_hit():
    rows = [r for r in load("hit_training_data.csv", ("p", "p2")) if str(r.get("played", "1")) != "0"]
    if not rows:
        return None
    return {
        "days": len({r["date"] for r in rows}), "n": len(rows),
        "calib": calib(rows, "p", "hit_yes", edges=(0, .5, .6, .65, .7, .75, .8, 1.01)),
        "topn": top_n_daily(rows, "p", "hit_yes"),
        "sides": side_split(rows, "p", "hit_yes"),
        "players": player_table(rows, "p", "hit_yes"),
        "streaks": streaks(rows, "hit_yes"),
        "paper": market_paper(rows, "p", "hit_yes", ("odds_dk", "odds_mgm", "odds_czr")),
        "ebuckets": edge_buckets(rows, "p", "hit_yes", ("odds_dk", "odds_mgm", "odds_czr"),
                                 under_key="odds_dk_u"),
        "ebuckets2": edge_buckets(rows, "p2", "hit2_yes", ("odds2_dk", "odds2_mgm", "odds2_czr")),
        "devig": sum(1 for r in rows if f(r.get("odds_dk_u")) is not None),
    }


def build_k():
    rows = [r for r in load("k_training_data.csv",
                            ("p_over_cons", "lock_p_over_cons"))
            if str(r.get("started", "1")) != "0" and f(r.get("k_actual")) is not None]
    if not rows:
        return None
    # over/under vs consensus line, model P(over) at the pre-game (lock if
    # available else morning) snapshot
    for r in rows:
        r["_p"] = f(r.get("lock_p_over_cons")) if f(r.get("lock_p_over_cons")) is not None else f(r.get("p_over_cons"))
        r["_y"] = f(r.get("lock_over_cons")) if f(r.get("lock_over_cons")) is not None else f(r.get("over_cons"))
        r["_ek"] = f(r.get("lock_exp_k")) if f(r.get("lock_exp_k")) is not None else f(r.get("exp_k"))
    graded = [r for r in rows if r["_p"] is not None and r["_y"] is not None]
    # best/worst pitchers vs model = actual K minus expected K
    agg = defaultdict(lambda: [0, 0.0, 0.0, ""])
    for r in rows:
        if r["_ek"] is None:
            continue
        a = agg[r["name"]]
        a[0] += 1; a[1] += r["_ek"]; a[2] += f(r["k_actual"]); a[3] = r.get("team", "")
    tbl = [{"t": nm, "tm": tm, "n": n, "pred": round(se / n, 2), "act": round(sa / n, 2),
            "d": round((sa - se) / n, 2)} for nm, (n, se, sa, tm) in agg.items() if n >= 3]
    tbl.sort(key=lambda x: -x["d"])
    # paper vs best line (model side at best price, edge >= 3 pts) + edge
    # buckets over EVERY priced start so the K market finds its own zone.
    # best_edge is stored as a fraction (0.05 = 5 pts).
    w = l = 0; pnl = 0.0
    kb = {b[0]: [0, 0, 0.0] for b in EDGE_BUCKETS}  # n, wins, pnl
    for r in rows:
        side = r.get("lock_best_side") or r.get("best_side")
        price = f(r.get("lock_best_price") if r.get("lock_best_price") else r.get("best_price"))
        edge = f(r.get("lock_best_edge") if r.get("lock_best_edge") else r.get("best_edge"))
        res = r.get("lock_best_result") or r.get("best_result")
        if not side or price is None or edge is None or res in (None, "", "P", "push"):
            continue
        won = str(res).upper().startswith("W") or res == "1"
        pr = payout(price) if won else -100.0
        e = edge * 100 if abs(edge) <= 1.5 else edge
        for name, lo, hi in EDGE_BUCKETS:
            if lo <= e < hi:
                kb[name][0] += 1; kb[name][1] += won; kb[name][2] += pr
                break
        if e < 3:
            continue
        w += won; l += (not won)
        pnl += pr
    mae = (sum(abs(f(r["k_actual"]) - r["_ek"]) for r in rows if r["_ek"] is not None)
           / max(1, sum(1 for r in rows if r["_ek"] is not None)))
    return {
        "days": len({r["date"] for r in rows}), "n": len(rows),
        "calib": calib(graded, "_p", "_y", edges=(0, .35, .45, .55, .65, 1.01)),
        "sides": side_split(graded, "_p", "_y"),
        "pitchers": {"best": tbl[:6], "worst": list(reversed(tbl[-6:]))},
        "mae": round(mae, 2),
        "paper": {"w": w, "l": l, "pnl": round(pnl),
                  "roi": round(pnl / ((w + l) * 100) * 100, 1) if w + l else 0.0},
        "ebuckets": [{"b": n, "n": v[0], "hits": v[1],
                      "rate": round(v[1] / v[0] * 100, 1) if v[0] else 0.0,
                      "pnl": round(v[2])} for n, v in kb.items() if v[0]],
    }


def main():
    out = {"hr": build_hr(), "hit": build_hit(), "k": build_k()}
    with open("props_analytics.json", "w") as fh:
        json.dump(out, fh)
    parts = [f"{k}: {v['n']} rows/{v['days']} days" for k, v in out.items() if v]
    print("props_analytics.json written — " + (", ".join(parts) if parts else "no graded data yet"))


if __name__ == "__main__":
    main()
