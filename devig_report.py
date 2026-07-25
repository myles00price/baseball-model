"""
devig_report.py — would a de-vigged edge window have bet better?

Re-grades the whole picks history two ways from the SAME stored odds:
  A) current: edge = model% - vig-included implied%   (what runs today)
  B) de-vig:  edge = model% - no-vig implied%         (candidate change)

Both use the 3-8% window and the same gates (reliability >= 8, no Coors
home games, no Sharp FADE). Read-only analysis — changes nothing live.

Run:  py -3.11 .\\devig_report.py
"""

import csv
import sys
import time
from glob import glob

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from features_v2 import BET_MIN, BET_MAX
from check_results import get_game_results

V2_LAUNCH = "2026-07-16"


def implied(odds):
    o = float(odds)
    return (-o) / (-o + 100) * 100 if o < 0 else 100 / (o + 100) * 100


def payout(odds):
    o = float(odds)
    return o if o > 0 else 10000.0 / abs(o)


def pick_bet(row, devig):
    """Return (side, team, odds) the window would bet, or None."""
    ap, hp = float(row["Model Away%"]), float(row["Model Home%"])
    best = None
    for a_col, h_col in (("DK Away Odds", "DK Home Odds"), ("MGM Away Odds", "MGM Home Odds")):
        try:
            ao, ho = float(row[a_col]), float(row[h_col])
        except (ValueError, TypeError):
            continue
        ia, ih = implied(ao), implied(ho)
        if devig:
            tot = ia + ih
            ia, ih = ia / tot * 100, ih / tot * 100
        for side, edge, odds in (("away", ap - ia, ao), ("home", hp - ih, ho)):
            if BET_MIN <= edge <= BET_MAX:
                if best is None or payout(odds) > payout(best[2]):
                    best = (side, row["Away"] if side == "away" else row["Home"], odds)
    return best


def gates_pass(row):
    try:
        rel_ok = min(float(row.get("Away Reliability%", 0) or 0),
                     float(row.get("Home Reliability%", 0) or 0)) >= 8
    except (ValueError, TypeError):
        rel_ok = False
    return (rel_ok and row.get("Home") != "Colorado Rockies"
            and "FADE" not in str(row.get("Sharp Signal", "")))


BUCKETS = (("0-3%", 0, 3), ("3-6%", 3, 6), ("6-10%", 6, 10), ("10%+", 10, 999))


def bucket_of(edge):
    for name, lo, hi in BUCKETS:
        if lo <= edge < hi:
            return name
    return None


def main():
    stats = {m: {"all": [0, 0, 0.0], "v2": [0, 0, 0.0], "dog": [0, 0, 0.0]}
             for m in ("vig", "devig")}
    # value-side DK edge buckets, no gates — diagnostic like the calibration report
    ebuckets = {m: {b[0]: [0, 0, 0.0] for b in BUCKETS} for m in ("vig", "devig")}
    diffs = []

    for f in sorted(glob("picks_2026-*.csv")):
        d = f.replace("picks_", "").replace(".csv", "")
        try:
            results = get_game_results(d)
        except Exception:
            continue
        if not results:
            continue
        time.sleep(0.2)
        for row in csv.DictReader(open(f, encoding="utf-8-sig")):
            ap, hp = row["Model Away%"], row["Model Home%"]
            if ap in ("None", "") or hp in ("None", ""):
                continue
            a, h = row["Away"], row["Home"]
            res = results.get(f"{a}@{h}") or results.get(a) or results.get(h)
            if not res:
                continue
            pick = a if float(ap) > float(hp) else h

            # Edge-bucket diagnostic (DK, value side, no gates)
            try:
                ao, ho = float(row["DK Away Odds"]), float(row["DK Home Odds"])
                ia, ih = implied(ao), implied(ho)
                for m in ("vig", "devig"):
                    if m == "devig":
                        tot = ia + ih
                        xa, xh = ia / tot * 100, ih / tot * 100
                    else:
                        xa, xh = ia, ih
                    ea, eh = float(ap) - xa, float(hp) - xh
                    side, edge, odds = ("away", ea, ao) if ea >= eh else ("home", eh, ho)
                    b = bucket_of(edge)
                    if b:
                        team = a if side == "away" else h
                        won = team == res["winner"]
                        s = ebuckets[m][b]
                        s[0] += 1; s[1] += won
                        s[2] += payout(odds) if won else -100.0
            except (ValueError, TypeError):
                pass

            if not gates_pass(row):
                continue
            bets = {}
            for m in ("vig", "devig"):
                bet = pick_bet(row, devig=(m == "devig"))
                bets[m] = bet
                if not bet:
                    continue
                _, team, odds = bet
                won = team == res["winner"]
                profit = payout(odds) if won else -100.0
                for bucket in (["all"] + (["v2"] if d >= V2_LAUNCH else [])
                               + (["dog"] if team != pick else [])):
                    s = stats[m][bucket]
                    s[0] += 1; s[1] += won; s[2] += profit
            if (bets["vig"] is None) != (bets["devig"] is None):
                tag = "devig-only" if bets["vig"] is None else "vig-only"
                bet = bets["devig"] or bets["vig"]
                won = bet[1] == res["winner"]
                diffs.append((d, f"{a} @ {h}", tag, bet[1], "W" if won else "L"))

    print(f"{'Method':<8} {'Scope':<6} {'Bets':>5} {'Record':>8} {'Win%':>6} {'P&L':>10} {'ROI':>7}")
    print("-" * 55)
    for m in ("vig", "devig"):
        for scope in ("all", "v2", "dog"):
            n, w, pnl = stats[m][scope]
            if n:
                print(f"{m:<8} {scope:<6} {n:>5} {w:>3}-{n-w:<4} {w/n*100:>5.1f}% "
                      f"{pnl:>+10.2f} {pnl/(n*100)*100:>+6.1f}%")
    print(f"\nEdge buckets — value side at DK, no gates (bets/win%/P&L):")
    print(f"{'Bucket':<8} {'— vig —':>24} {'— devig —':>26}")
    for name, _, _ in BUCKETS:
        v = ebuckets["vig"][name]; d = ebuckets["devig"][name]
        vs = f"{v[1]}/{v[0]} ({v[1]/v[0]*100:.0f}%) {v[2]:+8.0f}" if v[0] else "—"
        ds = f"{d[1]}/{d[0]} ({d[1]/d[0]*100:.0f}%) {d[2]:+8.0f}" if d[0] else "—"
        print(f"{name:<8} {vs:>24} {ds:>26}")

    print(f"\nGames where the methods disagree ({len(diffs)}):")
    for d, game, tag, team, wl in diffs:
        print(f"  {d}  {game:<42} {tag:<10} bet {team}: {wl}")


if __name__ == "__main__":
    main()
