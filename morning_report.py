"""
morning_report.py — daily 8:30 AM board refresh + leans text.

Rebuilds TODAY's slate at current odds (master_v2 with today's date), then
texts the shared topic the morning board: every lean with price and edge,
plus yesterday's card and the running record from board_stats.json.

Scheduled: BaseballMorningReport, daily 8:30 AM (runs at boot if missed).
"""

import csv
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from features_v2 import flagged_side
from notify_pick import send_push, load_picks

PYTHON = r"C:\Users\Poons\AppData\Local\Python\pythoncore-3.11-64\python.exe"
MASTER = r"C:\Users\Poons\baseball-model\master_v2.py"


def main():
    lv = timezone(timedelta(hours=-7))
    today = datetime.now(lv).strftime("%Y-%m-%d")

    # Rebuild today's board at morning odds (locked games stay frozen).
    subprocess.run([PYTHON, MASTER, today], timeout=2400)

    picks = load_picks(today)
    leans = []
    fades = 0
    rows = list(picks.values()) if isinstance(picks, dict) else list(picks)
    for row in rows:
        if "FADE" in str(row.get("Sharp Signal", "")):
            fades += 1
        if "BET" not in str(row.get("Flag", "")):
            continue
        s = flagged_side(row)
        if not s:
            continue
        team = row["Away"] if s == "away" else row["Home"]
        opp = row["Home"] if s == "away" else row["Away"]
        prob = row["Model Away%"] if s == "away" else row["Model Home%"]
        odds = row["DK Away Odds"] if s == "away" else row["DK Home Odds"]
        dk = str(row["DK Edge Away" if s == "away" else "DK Edge Home"]).replace(" ** BET **", "")
        mgm = str(row["MGM Edge Away" if s == "away" else "MGM Edge Home"]).replace(" ** BET **", "")
        leans.append(f"- {team} ({float(prob):.1f}%) vs {opp} - DK {odds}, edge DK {dk} / MGM {mgm}")

    lines = [f"{'Morning board'} ({today}), {len(rows)} games:"]
    if leans:
        lines.append(f"{len(leans)} lean(s) at current odds:")
        lines.extend(leans)
        lines.append("(pre-lineup - final locked picks text as lineups confirm)")
    else:
        lines.append("No leans at current odds - no value worth forcing. "
                     "A lineup lock can still produce a play; you'll get a text if one does.")
    if fades:
        lines.append(f"{fades} game(s) vetoed on sharp movement.")

    # K WATCH: rebuild at morning lines FIRST so the text can carry the early
    # leans (K lines post overnight; leans lock as K PLAYS at lineup confirm).
    try:
        subprocess.run([PYTHON, r"C:\Users\Poons\baseball-model\k_model.py", today], timeout=600)
        # K lean lines pulled from subscriber texts 2026-08-19 (display-only)
    except Exception as e:
        print(f"k watch failed: {e}")
    try:
        s = json.load(open("board_stats.json"))
        y = s.get("today", [])
        if y:
            yw = sum(1 for g in y if g.get("result") == "W")
            yl = sum(1 for g in y if g.get("result") == "L")
            lines.append(f"Yesterday: {yw}-{yl}.")
        lines.append(f"V2: {s['record']} | {'+' if s['pnl']>=0 else '-'}${abs(s['pnl'])} | "
                     f"ROI {'+' if s['roi']>=0 else ''}{s['roi']}% | Gate {s['gate']}/{s['gate_target']}")
    except Exception:
        pass
    send_push("MLB model: morning board", "\n".join(lines), bet=bool(leans))
    print("\n".join(lines))

    # Refresh the board's LONG BALL WATCH list (display only, never texted).
    try:
        subprocess.run(
            [PYTHON, r"C:\Users\Poons\baseball-model\hr_model.py", today],
            timeout=600,
        )
    except Exception as e:
        print(f"hr watch failed: {e}")

    # Refresh the board's HIT WATCH list (display only, never texted).
    try:
        subprocess.run(
            [PYTHON, r"C:\Users\Poons\baseball-model\hit_model.py", today],
            timeout=600,
        )
    except Exception as e:
        print(f"hit watch failed: {e}")

    # (K WATCH already rebuilt above, before the morning text.)

    # Push the refreshed board to the site.
    try:
        subprocess.run(["git", "add", "."], timeout=60)
        subprocess.run(["git", "commit", "-m", f"morning board {today}"], timeout=60)
        subprocess.run(["git", "push"], timeout=120)
    except Exception as e:
        print(f"push failed: {e}")


if __name__ == "__main__":
    main()
