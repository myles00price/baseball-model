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

NTFY_TOPIC = "poons-mlb-picks-k7d24q"   # shared: plays, results, weekly report ONLY
OPS_TOPIC = "poons-mlb-ops-x9r31m"      # private (owner only): system/failure alerts
PYTHON = r"C:\Users\Poons\AppData\Local\Python\pythoncore-3.11-64\python.exe"
MASTER = r"C:\Users\Poons\baseball-model\master_v2.py"

# Major US books for best-price shopping on confirmed picks
BOOKS = [
    ("draftkings", "DK"), ("betmgm", "MGM"), ("fanduel", "FD"),
    ("williamhill_us", "CZR"), ("hardrockbet", "HardRock"), ("circasports", "Circa"),
]
BOOK_LABEL = dict(BOOKS)


def _payout(odds):
    """$ won on a $100 stake at American odds — the line-shopping yardstick."""
    return odds if odds > 0 else 10000.0 / abs(odds)


def _fmt_odds(o):
    return f"+{o}" if o > 0 else str(o)


def fair_odds(prob_pct):
    """Model probability (0-100) -> no-vig American odds equivalent, so
    subscribers who think in odds can compare model vs book directly."""
    p = float(prob_pct)
    if p >= 50:
        return f"-{round(p / (100 - p) * 100)}"
    return f"+{round((100 - p) / p * 100)}"


def quarter_kelly(prob_pct, american_odds):
    """Quarter-Kelly stake as % of bankroll, capped at 2%.

    INFORMATIONAL until the 100-pick deploy gate passes — Kelly is only as
    good as the probability feeding it, and the model's live calibration
    isn't proven yet. Returns None when there is no positive-EV stake."""
    p = float(prob_pct) / 100.0
    b = _payout(float(american_odds)) / 100.0
    if b <= 0:
        return None
    k = (b * p - (1 - p)) / b
    if k <= 0:
        return None
    return min(k / 4 * 100, 2.0)


def fetch_market_odds(date_str=None):
    """team name -> {bookmaker_key: american_price}, six books, ONE slate.
    date_str filters to that Las Vegas date (default today) — the API
    returns multiple days and team-name keys would mix games otherwise."""
    from features_v2 import commence_lv_date
    if date_str is None:
        date_str = lv_today()
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        return {}
    try:
        resp = requests.get(
            "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/",
            params={
                "apiKey": key, "markets": "h2h", "oddsFormat": "american",
                "bookmakers": ",".join(k for k, _ in BOOKS),
            },
            timeout=20,
        )
        resp.raise_for_status()
        out = {}
        for game in resp.json():
            if commence_lv_date(game.get("commence_time")) != date_str:
                continue
            for bk in game.get("bookmakers", []):
                for mkt in bk.get("markets", []):
                    if mkt.get("key") != "h2h":
                        continue
                    for o in mkt.get("outcomes", []):
                        out.setdefault(o["name"], {})[bk["key"]] = o["price"]
        return out
    except Exception as e:
        print(f"odds fetch failed ({e}) — notifying without line shop")
        return {}


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


def format_pick(row, book_odds=None, started=False):
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
    # The BET flag belongs to the value side (features_v2.flagged_side),
    # which is not always the model's pick — name it explicitly.
    from features_v2 import flagged_side
    bside = flagged_side(row) if bet else None
    bet_team = row["Away"] if bside == "away" else row["Home"] if bside == "home" else None
    if bet and bet_team:
        bt_prob = row["Model Away%"] if bet_team == row["Away"] else row["Model Home%"]
        bt_fair = f"{float(bt_prob):.1f}% = fair {fair_odds(bt_prob)}"
        bet_line = (f"** BET: {bet_team} ({bt_fair}) **" if bet_team == side
                    else f"** BET: {bet_team} ({bt_fair}) ** (value dog — model still picks {side} to win)")
    else:
        bet_line = "No bet (outside 3-6% window)"
    lines = [
        f"{away} @ {home}",
        f"Pick: {side} ({prob:.1f}% = fair {fair_odds(prob)})",
        f"DK {dk_odds} (edge {dk_edge.replace(' ** BET **', '')}) | "
        f"MGM {mgm_odds} (edge {mgm_edge.replace(' ** BET **', '')})",
        bet_line,
    ]
    # Line shop the BET side when flagged, otherwise the pick side
    shop_team = bet_team if (bet and bet_team) else side
    prices = (book_odds or {}).get(shop_team, {})
    best_px = None
    if prices:
        ranked = sorted(prices.items(), key=lambda kv: -_payout(kv[1]))
        best_bk, best_px = ranked[0]
        lines.append(f"Best price: {BOOK_LABEL.get(best_bk, best_bk)} {_fmt_odds(best_px)}")
        lines.append(" | ".join(f"{BOOK_LABEL.get(k, k)} {_fmt_odds(v)}" for k, v in ranked))
    # Quarter-Kelly sizing on official bets (informational until the gate)
    if bet and bet_team:
        bet_prob = row["Model Away%"] if bet_team == row["Away"] else row["Model Home%"]
        kelly_px = best_px
        if kelly_px is None:
            kelly_px = row["DK Away Odds"] if bet_team == row["Away"] else row["DK Home Odds"]
        try:
            k = quarter_kelly(bet_prob, kelly_px)
        except Exception:
            k = None
        if k:
            lines.append(f"Kelly 1/4 (informational until 100-pick gate): {k:.1f}% of bankroll")
    sharp = row.get("Sharp Signal", "N/A")
    if "FADE" in str(sharp):
        lines.append("Sharp FADE veto active")
    if started:
        lines.append("(game already started)")
    return "\n".join(lines), bet


def send_ops(title, body):
    """System/failure alerts — private ops topic, never the shared one."""
    requests.post(f"https://ntfy.sh/{OPS_TOPIC}", data=body.encode("utf-8"),
                  headers={"Title": title, "Priority": "high", "Tags": "wrench"}, timeout=15)


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
        body = "Model is working. No slate loaded yet today - picks will follow if there are games."
        try:
            send_ops("Heartbeat: no picks file", "No picks file for today - check the overnight run.")
        except Exception:
            pass
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
    did_rerun = False
    if needs_rerun:
        print("Re-running master_v2.py with confirmed lineups...")
        subprocess.run([PYTHON, MASTER, date_str], timeout=1800)
        picks = load_picks(date_str)
        did_rerun = True

    book_odds = fetch_market_odds(date_str) if pending else {}

    sent_any = False
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
        body, bet = format_pick(row, book_odds, started=g["state"] in ("Live", "Final"))
        title = f"MLB pick locked: {g['away']} @ {g['home']}"
        send_push(title, body, bet)
        notified.add(key)
        sent_any = True
        print(f"Notified: {key}")
        # F5 shadow locks on the same lineup-confirmed evaluation as the
        # real play. Flags that fell out of the window on that evaluation
        # are already gone from the row - off the site, out of the ledger.
        try:
            import f5_shadow
            f5_shadow.lock_key(date_str, key)
        except Exception as e:
            print(f"F5 lock skipped for {key}: {e}")

    save_state(date_str, notified)

    # Push immediately so the live board reflects locks and dropped leans
    # within one cycle instead of waiting for the next scheduled push.
    if did_rerun or sent_any:
        try:
            subprocess.run(["git", "add", f"picks_{date_str}.csv", f"notified_{date_str}.json"], timeout=60)
            if os.path.exists(f"f5_shadow_{date_str}.json"):
                subprocess.run(["git", "add", f"f5_shadow_{date_str}.json"], timeout=60)
            subprocess.run(["git", "commit", "-m", f"lineup lock update {date_str}"], timeout=60)
            subprocess.run(["git", "push"], timeout=120)
            print("pushed lock update to site")
        except Exception as e:
            print(f"site push failed: {e}")


if __name__ == "__main__":
    main()
