"""
weekly_report.py — Thursday performance report ("the margin call").

Computes fresh numbers across every graded pick, writes a dated
WEEKLY_REPORT_<date>.md to the repo, pushes to GitHub, and sends a
condensed summary to the ntfy topic.

Scheduled: BaseballWeeklyReport, Thursdays 9:15 AM.
Run manually:  py -3.11 .\\weekly_report.py
"""

import csv
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from glob import glob

# Task Scheduler consoles use cp1252, which can't encode emoji glyphs
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from features_v2 import flagged_side
from check_results import get_game_results
from notify_pick import send_push

V2_LAUNCH = "2026-07-16"
GATE_PICKS, GATE_WINPCT = 100, 54.0


def payout(odds):
    o = float(odds)
    return o if o > 0 else 10000.0 / abs(o)


def gather():
    """Grade every picks file once. Returns per-game records."""
    games = []
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
            g = {"date": d, "away": a, "home": h, "winner": res["winner"],
                 "pick": pick, "pick_won": pick == res["winner"],
                 "bet_team": None, "bet_won": None, "bet_profit": 0.0}
            if "BET" in str(row.get("Flag", "")):
                s = flagged_side(row)
                bt = a if s == "away" else h if s == "home" else pick
                odds = row["DK Away Odds"] if bt == a else row["DK Home Odds"]
                g["bet_team"] = bt
                g["bet_won"] = bt == res["winner"]
                try:
                    g["bet_profit"] = payout(odds) if g["bet_won"] else -100.0
                except Exception:
                    g["bet_profit"] = 100.0 if g["bet_won"] else -100.0
            games.append(g)
    return games


def clv_stats(days=None):
    try:
        log = json.load(open("clv_log.json"))
    except Exception:
        return None
    vals = [e["clv"] for e in log
            if e.get("clv") is not None and (days is None or e.get("date") in days)]
    if not vals:
        return None
    beat = sum(1 for c in vals if c > 0)
    return {"n": len(vals), "avg": sum(vals) / len(vals), "beat": beat}


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    week_start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    games = gather()

    # V2 window (official flagged bets, correct side)
    v2 = [g for g in games if g["date"] >= V2_LAUNCH]
    v2_bets = [g for g in v2 if g["bet_team"]]
    v2_w = sum(1 for g in v2_bets if g["bet_won"])
    v2_pnl = sum(g["bet_profit"] for g in v2_bets)
    v2_picks_w = sum(1 for g in v2 if g["pick_won"])

    # This week's dailies
    week = [g for g in v2 if g["date"] >= week_start]
    by_day = defaultdict(lambda: [0, 0, 0, 0, 0.0])  # pw, pt, bw, bt, pnl
    for g in week:
        d = by_day[g["date"]]
        d[0] += g["pick_won"]; d[1] += 1
        if g["bet_team"]:
            d[2] += bool(g["bet_won"]); d[3] += 1; d[4] += g["bet_profit"]

    # Season flagged
    sb = [g for g in games if g["bet_team"]]
    sb_w = sum(1 for g in sb if g["bet_won"])
    sb_pnl = sum(g["bet_profit"] for g in sb)

    # Team analytics
    picked = defaultdict(lambda: [0, 0])
    bet_on = defaultdict(lambda: [0, 0])
    for g in games:
        picked[g["pick"]][1] += 1; picked[g["pick"]][0] += g["pick_won"]
        if g["bet_team"]:
            bet_on[g["bet_team"]][1] += 1; bet_on[g["bet_team"]][0] += bool(g["bet_won"])
    rank = sorted(((c / t, c, t, tm) for tm, (c, t) in picked.items() if t >= 8), reverse=True)
    best = rank[:5]
    worst = rank[-5:]
    hot_bets = sorted(bet_on.items(), key=lambda kv: -kv[1][1])[:6]

    clv_season = clv_stats()
    v2_days = sorted({g["date"] for g in v2})
    clv_v2 = clv_stats(days=set(v2_days))

    gate_pct = (v2_w / len(v2_bets) * 100) if v2_bets else 0.0

    # ── Markdown report ──────────────────────────────────────────────
    lines = [
        f"# MLB Model — Weekly Performance Report",
        f"**Generated {today} · auto-report**", "",
        "## Headline",
        f"- V2 official flagged bets since launch ({V2_LAUNCH}): **{v2_w}-{len(v2_bets)-v2_w}** "
        f"({gate_pct:.1f}%), P&L **{v2_pnl:+.0f}** at $100 flat "
        f"(ROI {v2_pnl/(len(v2_bets)*100)*100 if v2_bets else 0:+.1f}%)",
        f"- Deploy gate: **{len(v2_bets)} / {GATE_PICKS}** picks at {gate_pct:.1f}% (need >={GATE_WINPCT}%)",
        f"- V2 pick accuracy (all games): {v2_picks_w}/{len(v2)} ({v2_picks_w/len(v2)*100 if v2 else 0:.1f}%)",
    ]
    if clv_v2:
        lines.append(f"- V2-window CLV: **{clv_v2['avg']:+.2f}%** avg, beat close "
                     f"{clv_v2['beat']}/{clv_v2['n']} ({clv_v2['beat']/clv_v2['n']*100:.0f}%)")
    if clv_season:
        lines.append(f"- Season CLV: {clv_season['avg']:+.2f}% avg over {clv_season['n']} games "
                     f"({clv_season['beat']/clv_season['n']*100:.0f}% beat rate)")
    lines += ["", "## This week (daily)", "| Day | Picks | Official flags | P&L |", "|---|---|---|---|"]
    for d in sorted(by_day):
        pw, pt, bw, bt, pnl = by_day[d]
        flags = f"{bw}-{bt-bw}" if bt else "no flags"
        lines.append(f"| {d} | {pw}/{pt} | {flags} | {pnl:+.0f} |")
    lines += ["", "## Season flagged bets (correct-side grading)",
              f"- Record: {sb_w}-{len(sb)-sb_w} ({sb_w/len(sb)*100 if sb else 0:.1f}%), "
              f"P&L {sb_pnl:+.0f} (ROI {sb_pnl/(len(sb)*100)*100 if sb else 0:+.1f}%)", "",
              "## Team analytics", "**Best when picked (min 8):**"]
    lines += [f"- {tm}: {c}/{t} ({p*100:.0f}%)" for p, c, t, tm in best]
    lines.append("**Worst when picked:**")
    lines += [f"- {tm}: {c}/{t} ({p*100:.0f}%)" for p, c, t, tm in worst]
    lines.append("**Most-bet teams:**")
    lines += [f"- {tm}: {w}-{t-w}" for tm, (w, t) in hot_bets]
    lines += ["", "*Auto-generated. Full analysis notes: see prior manual reports.*"]

    report_file = f"WEEKLY_REPORT_{today}.md"
    if os.path.exists(report_file):  # don't clobber a hand-written report
        report_file = f"WEEKLY_REPORT_{today}_auto.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote {report_file}")

    # ── Push to GitHub ───────────────────────────────────────────────
    try:
        subprocess.run(["git", "add", report_file], timeout=60)
        subprocess.run(["git", "commit", "-m", f"weekly report {today}"], timeout=60)
        subprocess.run(["git", "push"], timeout=120)
    except Exception as e:
        print(f"git push failed: {e}")

    # ── Condensed text ───────────────────────────────────────────────
    week_bets = sum(d[3] for d in by_day.values())
    week_w = sum(d[2] for d in by_day.values())
    week_pnl = sum(d[4] for d in by_day.values())
    body = [
        f"Weekly report ({today}):",
        f"This week: {week_w}-{week_bets-week_w} official plays, {week_pnl:+.0f}",
        f"V2 since launch: {v2_w}-{len(v2_bets)-v2_w} ({gate_pct:.0f}%), {v2_pnl:+.0f} at $100 flat",
        f"Gate: {len(v2_bets)}/{GATE_PICKS} picks (need 54%+)",
    ]
    if clv_v2:
        body.append(f"CLV: {clv_v2['avg']:+.2f}% avg, {clv_v2['beat']/clv_v2['n']*100:.0f}% beat close")
    if best:
        body.append(f"Best team: {best[0][3]} {best[0][1]}/{best[0][2]}")
    body.append("Full report on GitHub. Flat stakes until gate.")
    send_push("MLB model: weekly report", "\n".join(body), bet=False)
    print("Weekly text sent")


if __name__ == "__main__":
    main()
