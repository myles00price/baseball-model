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

from notify_pick import load_picks, send_push, send_ops
from features_v2 import flagged_side

STALE_SECONDS = 45 * 60  # picks file older than this = nightly run failed


def main():
    lv = timezone(timedelta(hours=-7))
    date_str = (datetime.now(lv) + timedelta(days=1)).strftime("%Y-%m-%d")
    filename = f"picks_{date_str}.csv"

    fresh = os.path.exists(filename) and (time.time() - os.path.getmtime(filename)) < STALE_SECONDS
    if not fresh:
        # System problem: ops topic only — subscribers never see plumbing.
        send_ops("Nightly run PROBLEM",
                 f"No fresh picks file for {date_str} after the 10:50 PM run - check the machine.")
        print(f"{date_str}: picks file missing or stale — ops alert sent")
        return

    picks = load_picks(date_str)
    bets = []
    for key, row in picks.items():
        if "BET" in str(row.get("Flag", "")):
            # List the FLAGGED side (may be the value dog), not the model's pick
            s = flagged_side(row)
            if s == "away":
                side, prob, odds, dk_e, mgm_e = (row["Away"], row["Model Away%"],
                    row["DK Away Odds"], row["DK Edge Away"], row["MGM Edge Away"])
            elif s == "home":
                side, prob, odds, dk_e, mgm_e = (row["Home"], row["Model Home%"],
                    row["DK Home Odds"], row["DK Edge Home"], row["MGM Edge Home"])
            else:
                continue
            dk_e = str(dk_e).replace(" ** BET **", "")
            mgm_e = str(mgm_e).replace(" ** BET **", "")
            opp = row["Away"] if side == row["Home"] else row["Home"]
            bets.append(f"{side} ({float(prob):.1f}%) vs {opp}"
                        f" - DK {odds}, edge DK {dk_e} / MGM {mgm_e}")

    lines = [f"Nightly run complete. {len(picks)} game(s) on tomorrow's slate ({date_str})."]
    if bets:
        lines.append(f"{len(bets)} early BET flag(s):")
        lines.extend(f"- {b}" for b in bets)
        lines.append("(pre-lineup numbers — final pick comes when lineups confirm)")
    else:
        lines.append("No BET flags yet — final picks come when lineups confirm.")

    # K WATCH early leans: strikeout lines post overnight for probable starters.
    # Build tomorrow's K list now (k_model handles the date), then list leans.
    k_lines = []
    try:
        import subprocess
        subprocess.run([sys.executable, r"C:\Users\Poons\baseball-model\k_model.py", date_str],
                       timeout=600, cwd=r"C:\Users\Poons\baseball-model")
        import k_notify
        k_lines = k_notify.lean_lines(date_str)
    except Exception as e:
        print(f"K early leans skipped: {e}")
    if k_lines:
        lines.append(f"K WATCH early leans ({len(k_lines)}) - lock as K PLAYS when lineups confirm:")
        lines.extend(f"- {k}" for k in k_lines)
    send_push(f"MLB model: tomorrow's slate ready", "\n".join(lines), bet=bool(bets or k_lines))
    print(f"{date_str}: nightly summary sent ({len(picks)} games, {len(bets)} bets, {len(k_lines)} K leans)")


if __name__ == "__main__":
    main()
