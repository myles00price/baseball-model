"""
daily_results_notify.py — end-of-day results text.

Grades today's official flagged bets and texts the shared topic:
today's record + P&L, each bet's result, and the running V2 record
with ROI since launch. Runs as the second action of the
BaseballCheckResults task (10:30 PM), after check_results.py.

Late games still in progress are listed as pending; they fold into
the running totals the next night.
"""

import csv
import sys
import time
from datetime import datetime, timedelta, timezone
from glob import glob

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from features_v2 import flagged_side
from check_results import get_game_results
from notify_pick import send_push

V2_LAUNCH = "2026-07-16"


def payout(odds):
    o = float(odds)
    return o if o > 0 else 10000.0 / abs(o)


def grade_day(date_str, results=None):
    """[(bet_team, odds, won|None, score)] for official flags on date_str."""
    fn = f"picks_{date_str}.csv"
    try:
        rows = list(csv.DictReader(open(fn, encoding="utf-8-sig")))
    except OSError:
        return []
    if results is None:
        try:
            results = get_game_results(date_str)
        except Exception:
            results = {}
    out = []
    for row in rows:
        if "BET" not in str(row.get("Flag", "")):
            continue
        a, h = row["Away"], row["Home"]
        s = flagged_side(row)
        bt = a if s == "away" else h if s == "home" else None
        if not bt:
            continue
        odds = row["DK Away Odds"] if bt == a else row["DK Home Odds"]
        res = results.get(f"{a}@{h}")
        if not res:
            out.append((bt, odds, None, ""))
            continue
        out.append((bt, odds, bt == res["winner"],
                    f"{res['away_score']}-{res['home_score']}"))
    return out


def main():
    lv = timezone(timedelta(hours=-7))
    today = datetime.now(lv).strftime("%Y-%m-%d")

    # Today's card
    day = grade_day(today)
    day_w = sum(1 for *_, won, _s in [(0, 0, g[2], g[3]) for g in day] if won)
    day_graded = [g for g in day if g[2] is not None]
    day_pnl = sum((payout(g[1]) if g[2] else -100.0) for g in day_graded)
    day_l = len(day_graded) - day_w

    # Running V2 totals (all graded official bets since launch)
    run_w = run_n = 0
    run_pnl = 0.0
    for f in sorted(glob("picks_2026-*.csv")):
        d = f.replace("picks_", "").replace(".csv", "")
        if d < V2_LAUNCH or d > today:
            continue
        time.sleep(0.2)
        for bt, odds, won, _score in grade_day(d):
            if won is None:
                continue
            run_n += 1
            run_w += won
            run_pnl += payout(odds) if won else -100.0

    lines = []
    if not day:
        lines.append("Today: no official plays.")
    else:
        rec = f"{day_w}-{day_l}" if day_graded else "all pending"
        pnl_str = f"{day_pnl:+.0f}" if day_graded else "-"
        lines.append(f"Today: {rec} ({pnl_str})")
        for bt, odds, won, score in day:
            mark = "W" if won else "L" if won is not None else "pending"
            lines.append(f"  {mark}: {bt} {odds}" + (f" ({score})" if score else ""))
    roi = run_pnl / (run_n * 100) * 100 if run_n else 0.0
    winpct = run_w / run_n * 100 if run_n else 0.0
    lines.append(f"V2 running: {run_w}-{run_n - run_w} ({winpct:.1f}%) | "
                 f"{run_pnl:+.0f} at $100 flat | ROI {roi:+.1f}%")
    lines.append(f"Gate: {run_n}/100 picks")

    # Stats file for board.html — regenerated every nightly grade
    import json
    with open("board_stats.json", "w") as f:
        json.dump({
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "record": f"{run_w}-{run_n - run_w}", "win_pct": round(winpct, 1),
            "pnl": round(run_pnl), "roi": round(roi, 1),
            "gate": run_n, "gate_target": 100,
            "flagged_clv": 6.49, "clv_beat_pct": 96,
            "today": [{"team": bt, "odds": odds,
                       "result": ("W" if won else "L") if won is not None else "pending",
                       "score": score} for bt, odds, won, score in day],
        }, f, indent=1)
    print("board_stats.json written")

    try:  # full ledger for the board's analytics section
        import gen_analytics
        gen_analytics.main()
    except Exception as e:
        print(f"analytics generation failed: {e}")

    try:  # nightly pitcher-usage collection (data for future bullpen trials)
        import pen_usage_log
        pen_usage_log.collect_recent()
    except Exception as e:
        print(f"pen usage collection failed: {e}")

    try:  # grade HR watch predictions into the training archive
        import hr_grade
        hr_grade.run()
    except Exception as e:
        print(f"hr grading failed: {e}")

    try:  # grade HIT watch predictions into the training archive
        import hit_grade
        hit_grade.run()
    except Exception as e:
        print(f"hit grading failed: {e}")

    try:  # grade K watch predictions into the training archive
        import k_grade
        k_grade.run()
    except Exception as e:
        print(f"k grading failed: {e}")

    if "--stats-only" in sys.argv:
        print("(stats-only: no text sent)")
        return
    send_push("MLB model: daily record", "\n".join(lines), bet=False)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
