"""
notify_pick.py — phone notification when lineups are confirmed and the
final pick is locked in.

Runs every 15 minutes (Task Scheduler: BaseballPickNotify). For each game
today where BOTH lineups are confirmed:
  1. If the picks CSV row isn't CONFIRMED+PLATOON yet, re-runs master_v2.py
     so the pick reflects the actual lineups.
  2. Sends a push notification via ntfy.sh with the model pick, odds, and
     edge. One notification per game per day (state in notified_<date>.json).

Phone setup (one time): install the "ntfy" app (App Store / Play Store),
tap + and subscribe to the topic below. Nothing else needed.
"""

import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

# Task Scheduler consoles use cp1252, which can't encode emoji glyphs
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

NTFY_TOPIC = "poons-mlb-picks-k7d24q"   # subscribe to this in the ntfy app
PYTHON = r"C:\Users\Poons\AppData\Local\Python\pythoncore-3.11-64\python.exe"
MASTER = r"C:\Users\Poons\baseball-model\master_v2.py"


def lv_today():
    return datetime.now(timezone(timedelta(hours=-7))).strftime("%Y-%m-%d")


def get_confirmed_games(date_str):
    """Games today where BOTH lineups are posted. Returns list of dicts."""
    data = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={"sportId": 1, "date": date_str, "hydrate": "lineups"},
        timeout=15,
    ).json()
    games = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            lu = g.get("lineups", {})
            if lu.get("homePlayers") and lu.get("awayPlayers"):
                games.append({
                    "away": g["teams"]["away"]["team"]["name"],
                    "home": g["teams"]["home"]["team"]["name"],
                    "state": g.get("status", {}).get("abstractGameState", ""),
                })
    return games


def load_picks(date_str):
    filename = f"picks_{date_str}.csv"
    if not os.path.exists(filename):
        return {}
    picks = {}
    with open(filename, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = f"{row['Away']}@{row['Home']}"
            # doubleheaders: two rows share a key — keep the one with a pick
            existing = picks.get(key)
            if existing and existing.get("Model Away%") not in (None, "", "None") \
                    and row.get("Model Away%") in (None, "", "None"):
                continue
            picks[key] = row
    return picks


def load_state(date_str):
    try:
        with open(f"notified_{date_str}.json") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_state(date_str, notified):
    with open(f"notified_{date_str}.json", "w") as f:
        json.dump(sorted(notified), f)


def format_pick(row, started=False):
    away, home = row["Away"], row["Home"]
    away_p, home_p = float(row["Model Away%"]), float(row["Model Home%"])
    side = away if away_p > home_p else home
    prob = max(away_p, home_p)
    if side == away:
        dk_odds, mgm_odds = row["DK Away Odds"], row["MGM Away Odds"]
        dk_edge, mgm_edge = row["DK Edge Away"], row["MGM Edge Away"]
    else:
        dk_odds, mgm_odds = row["DK Home Odds"], row["MGM Home Odds"]
        dk_edge, mgm_edge = row["DK Edge Home"], row["MGM Edge Home"]
    bet = "BET" in str(row.get("Flag", ""))
    lines = [
        f"{away} @ {home}",
        f"Pick: {side} ({prob:.1f}%)",
        f"DK {dk_odds} (edge {dk_edge.replace(' ** BET **', '')}) | "
        f"MGM {mgm_odds} (edge {mgm_edge.replace(' ** BET **', '')})",
        "** BET **" if bet else "No bet (outside 3-8% window)",
    ]
    sharp = row.get("Sharp Signal", "N/A")
    if "FADE" in str(sharp):
        lines.append("Sharp FADE veto active")
    if started:
        lines.append("(game already started)")
    return "\n".join(lines), bet


def send_push(title, body, bet):
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers={
            "Title": title,
            "Priority": "high" if bet else "default",
            "Tags": "baseball" + (",moneybag" if bet else ""),
        },
        timeout=15,
    )


def send_heartbeat(date_str):
    """9 AM 'model is alive' push — first run of the day sends this."""
    picks = load_picks(date_str)
    if picks:
        body = (f"Model is working. {len(picks)} game(s) on today's slate. "
                "The pick will be sent as soon as both lineups are confirmed.")
    else:
        body = ("Model is working, but no picks file for today "
                "(off day, or check the overnight run). Lineup watch is active.")
    send_push("MLB model: morning check-in", body, bet=False)


def main():
    date_str = lv_today()
    notified = load_state(date_str)

    if "_heartbeat" not in notified:
        send_heartbeat(date_str)
        notified.add("_heartbeat")
        save_state(date_str, notified)
        print(f"{date_str}: heartbeat sent")

    confirmed = get_confirmed_games(date_str)
    if not confirmed:
        print(f"{date_str}: no games with both lineups confirmed yet")
        return
    pending = [g for g in confirmed if f"{g['away']}@{g['home']}" not in notified]
    if not pending:
        print(f"{date_str}: all confirmed games already notified")
        return

    picks = load_picks(date_str)

    # If any pending game's pick wasn't built from confirmed lineups,
    # re-run master_v2 once so the pick is final before we send it.
    needs_rerun = any(
        picks.get(f"{g['away']}@{g['home']}", {}).get("Lineup Source") != "CONFIRMED+PLATOON"
        and g["state"] == "Preview"
        for g in pending
    )
    if needs_rerun:
        print("Re-running master_v2.py with confirmed lineups...")
        subprocess.run([PYTHON, MASTER, date_str], timeout=1800)
        picks = load_picks(date_str)

    for g in pending:
        key = f"{g['away']}@{g['home']}"
        if key in notified:  # doubleheader: same key appears twice in one run
            continue
        row = picks.get(key)
        if not row:
            print(f"{key}: lineups confirmed but no pick row yet — will retry next run")
            continue
        if row.get("Model Away%") in (None, "", "None") or row.get("Model Home%") in (None, "", "None"):
            print(f"{key}: no model pick yet (starter unresolved) — will retry next run")
            continue
        body, bet = format_pick(row, started=g["state"] in ("Live", "Final"))
        title = f"MLB pick locked: {g['away']} @ {g['home']}"
        send_push(title, body, bet)
        notified.add(key)
        print(f"Notified: {key}")

    save_state(date_str, notified)


if __name__ == "__main__":
    main()
