"""
nightly_notify.py — push summary after the 10:50 PM nightly picks run.

Runs as the second action of the BaseballMasterPicks scheduled task,
immediately after master_v2.py generates tomorrow's picks. Sends an
ntfy push with the slate summary, or a failure alert if the picks file
is missing/stale.
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone

# Task Scheduler consoles use cp1252, which can't encode emoji glyphs
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from notify_pick import load_picks, send_push

STALE_SECONDS = 45 * 60  # picks file older than this = nightly run failed


def main():
    lv = timezone(timedelta(hours=-7))
    date_str = (datetime.now(lv) + timedelta(days=1)).strftime("%Y-%m-%d")
    filename = f"picks_{date_str}.csv"

    fresh = os.path.exists(filename) and (time.time() - os.path.getmtime(filename)) < STALE_SECONDS
    if not fresh:
        send_push(
            "MLB model: nightly run PROBLEM",
            f"No fresh picks file for {date_str} after the 10:50 PM run — check the machine.",
            bet=False,
        )
        print(f"{date_str}: picks file missing or stale — failure alert sent")
        return

    picks = load_picks(date_str)
    bets = []
    for key, row in picks.items():
        if "BET" in str(row.get("Flag", "")):
            away_p, home_p = float(row["Model Away%"]), float(row["Model Home%"])
            if away_p > home_p:
                side, odds, dk_e, mgm_e = row["Away"], row["DK Away Odds"], row["DK Edge Away"], row["MGM Edge Away"]
            else:
                side, odds, dk_e, mgm_e = row["Home"], row["DK Home Odds"], row["DK Edge Home"], row["MGM Edge Home"]
            dk_e = str(dk_e).replace(" ** BET **", "")
            mgm_e = str(mgm_e).replace(" ** BET **", "")
            bets.append(f"{side} ({max(away_p, home_p):.1f}%) vs {row['Away'] if side == row['Home'] else row['Home']}"
                        f" - DK {odds}, edge DK {dk_e} / MGM {mgm_e}")

    lines = [f"Nightly run complete. {len(picks)} game(s) on tomorrow's slate ({date_str})."]
    if bets:
        lines.append(f"{len(bets)} early BET flag(s):")
        lines.extend(f"- {b}" for b in bets)
        lines.append("(pre-lineup numbers — final pick comes when lineups confirm)")
    else:
        lines.append("No BET flags yet — final picks come when lineups confirm.")
    send_push(f"MLB model: tomorrow's slate ready", "\n".join(lines), bet=bool(bets))
    print(f"{date_str}: nightly summary sent ({len(picks)} games, {len(bets)} bets)")


if __name__ == "__main__":
    main()
