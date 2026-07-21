import requests
import csv
import os
import json
import sys
from datetime import datetime, timedelta, timezone

from features_v2 import flagged_side

# Task Scheduler consoles use cp1252, which can't encode emoji glyphs
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

def get_game_results(date_str):
    schedule = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={"sportId": 1, "date": date_str, "hydrate": "linescore"}
    ).json()
    results = {}
    for date in schedule.get("dates", []):
        for game in date.get("games", []):
            status = game.get("status", {}).get("abstractGameState")
            if status != "Final":
                continue
            home = game["teams"]["home"]["team"]["name"]
            away = game["teams"]["away"]["team"]["name"]
            home_score = game["teams"]["home"].get("score", 0)
            away_score = game["teams"]["away"].get("score", 0)
            winner = home if home_score > away_score else away
            results[f"{away}@{home}"] = {
                "home": home, "away": away,
                "home_score": home_score, "away_score": away_score,
                "winner": winner
            }
    return results

def get_closing_lines():
    try:
        odds_resp = requests.get(
            "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/",
            params={
                "apiKey": os.environ.get("ODDS_API_KEY", "719921510f0839e3f61743f271956eea"),
                "regions": "us",
                "markets": "h2h",
                "oddsFormat": "american",
                "bookmakers": "draftkings"
            }
        ).json()
        closing = {}
        for game in odds_resp:
            for bookmaker in game["bookmakers"]:
                if bookmaker["key"] != "draftkings":
                    continue
                for market in bookmaker["markets"]:
                    if market["key"] != "h2h":
                        continue
                    for outcome in market["outcomes"]:
                        team = outcome["name"]
                        price = outcome["price"]
                        try:
                            price = float(price)
                            imp = round((-price) / (-price + 100) * 100, 1) if price < 0 else round(100 / (price + 100) * 100, 1)
                            closing[team] = {"odds": int(price), "implied": imp}
                        except:
                            pass
        return closing
    except:
        return {}

# ── NEW: load opening lines from saved_lines.json ───────────────────────────
def load_opening_lines():
    """Returns the saved_lines.json dict, or {} if missing."""
    try:
        with open("saved_lines.json") as f:
            return json.load(f)
    except:
        return {}

def odds_to_implied(odds):
    """American odds → implied probability %. Returns None on failure."""
    try:
        o = float(odds)
        if o < 0:
            return round((-o) / (-o + 100) * 100, 1)
        else:
            return round(100 / (o + 100) * 100, 1)
    except:
        return None

def lookup_opening(saved, away, home, team):
    """Find the opening DK odds + implied % for `team` in the matchup.
    Returns (opening_odds, opening_implied) or (None, None) if not found."""
    # saved_lines.json keys are formatted "Away@Home" — exact match required
    key = f"{away}@{home}"
    entry = saved.get(key)
    if not entry:
        return None, None
    team_odds_block = entry.get("odds", {}).get(team, {})
    dk = team_odds_block.get("draftkings")
    if dk is None:
        return None, None
    return int(dk), odds_to_implied(dk)
# ────────────────────────────────────────────────────────────────────────────

def load_clv_log():
    try:
        with open("clv_log.json") as f:
            return json.load(f)
    except:
        return []

def save_clv_log(log):
    with open("clv_log.json", "w") as f:
        json.dump(log, f, indent=2)

def check_picks(date_str):
    filename = f"picks_{date_str}.csv"
    if not os.path.exists(filename):
        print(f"No picks file found for {date_str}")
        return

    print(f"\n=== Results Check for {date_str} ===\n")

    results = get_game_results(date_str)
    if not results:
        print("Games not final yet — check back later!")
        return

    print("Pulling closing lines for CLV...")
    closing = get_closing_lines()
    saved_opening = load_opening_lines()   # NEW

    picks = []
    with open(filename, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            picks.append(row)

    total = correct = bet_total = bet_correct = 0
    clv_log = load_clv_log()
    new_clv_entries = []

    for pick in picks:
        away = pick["Away"]; home = pick["Home"]
        key = f"{away}@{home}"
        away_prob = pick["Model Away%"]; home_prob = pick["Model Home%"]
        flag = pick["Flag"]

        if away_prob == "None" or home_prob == "None":
            continue

        model_winner = away if float(away_prob) > float(home_prob) else home
        model_prob = float(away_prob) if float(away_prob) > float(home_prob) else float(home_prob)

        result = results.get(key) or results.get(f"{home}@{away}")
        if not result:
            print(f"  {away} @ {home} — No result found yet")
            continue

        actual_winner = result["winner"]
        score = f"{result['away_score']}-{result['home_score']}"
        correct_flag = "✓" if model_winner == actual_winner else "✗"

        total += 1
        if model_winner == actual_winner:
            correct += 1

        if flag == "** BET **":
            # Grade the side that actually carried the BET flag — often the
            # value dog, NOT the model's pick side (features_v2.flagged_side).
            side = flagged_side(pick)
            bet_team = away if side == "away" else home if side == "home" else model_winner
            bet_total += 1
            if bet_team == actual_winner:
                bet_correct += 1

        # Closing line lookup (existing)
        closing_data = closing.get(model_winner, {})
        closing_implied = closing_data.get("implied")
        closing_odds = closing_data.get("odds")
        clv = round(model_prob - closing_implied, 1) if closing_implied else None
        clv_positive = clv > 0 if clv is not None else None

        # ── NEW: opening line lookup ────────────────────────────────────────
        opening_odds, opening_implied = lookup_opening(saved_opening, away, home, model_winner)
        # Open→close drift = how much the market moved toward the model's pick
        # Positive drift = market agreed with model over the day (sharp confirmation)
        if opening_implied is not None and closing_implied is not None:
            open_close_drift = round(closing_implied - opening_implied, 1)
        else:
            open_close_drift = None
        # ─────────────────────────────────────────────────────────────────────

        already_logged = any(
            e.get("date") == date_str and e.get("away") == away and e.get("home") == home
            for e in clv_log
        )
        if not already_logged:
            new_clv_entries.append({
                "date": date_str, "away": away, "home": home,
                "model_pick": model_winner, "model_prob": model_prob,
                "opening_implied": opening_implied,       # NEW
                "opening_odds": opening_odds,             # NEW
                "closing_implied": closing_implied,
                "closing_odds": closing_odds,
                "open_close_drift": open_close_drift,     # NEW
                "clv": clv, "clv_positive": clv_positive,
                "won": model_winner == actual_winner,
                "flagged": flag == "** BET **"
            })

        print(f"  {correct_flag} {away} @ {home}")
        print(f"     Score: {score} | Winner: {actual_winner}")
        print(f"     Model picked: {model_winner} ({away_prob}% vs {home_prob}%)")
        # NEW: print opening alongside closing when available
        if opening_implied is not None and closing_implied is not None:
            drift_str = f"{open_close_drift:+.1f}%" if open_close_drift is not None else "—"
            print(f"     Open: {opening_implied}% → Close: {closing_implied}% (Δ {drift_str}) | Model: {model_prob}% → CLV: {clv:+.1f}% {'✅' if clv_positive else '❌'}")
        elif clv is not None:
            print(f"     CLV: {model_prob}% model vs {closing_implied}% closing → {clv:+.1f}% {'✅' if clv_positive else '❌'}")
        if flag == "** BET **":
            side = flagged_side(pick)
            bet_team = away if side == "away" else home if side == "home" else model_winner
            result_str = "WIN" if bet_team == actual_winner else "LOSS"
            print(f"     *** FLAGGED BET ({bet_team}) — {result_str} ***")
        print()

    if new_clv_entries:
        clv_log.extend(new_clv_entries)
        save_clv_log(clv_log)
        print(f"CLV logged for {len(new_clv_entries)} games.")

    # Today CLV summary
    dated = [e for e in clv_log if e.get("date") == date_str and e.get("clv") is not None]
    if dated:
        avg = round(sum(e["clv"] for e in dated) / len(dated), 2)
        pos = sum(1 for e in dated if e["clv_positive"])
        print(f"\n📈 CLV for {date_str}:")
        print(f"   Avg CLV: {avg:+.2f}%")
        print(f"   Beat closing line: {pos}/{len(dated)}")
        # NEW: today's drift summary if any opening data captured
        dated_drift = [e for e in dated if e.get("open_close_drift") is not None]
        if dated_drift:
            avg_drift = round(sum(e["open_close_drift"] for e in dated_drift) / len(dated_drift), 2)
            print(f"   Avg Open→Close drift: {avg_drift:+.2f}% ({len(dated_drift)} games)")

    # Season CLV summary
    all_clv = [e for e in clv_log if e.get("clv") is not None]
    if all_clv:
        s_avg = round(sum(e["clv"] for e in all_clv) / len(all_clv), 2)
        s_pos = sum(1 for e in all_clv if e["clv_positive"])
        flagged_clv = [e for e in all_clv if e.get("flagged")]
        f_avg = round(sum(e["clv"] for e in flagged_clv) / len(flagged_clv), 2) if flagged_clv else 0
        print(f"\n📊 Season CLV ({len(all_clv)} games):")
        print(f"   Overall avg: {s_avg:+.2f}%")
        print(f"   Beat close: {s_pos}/{len(all_clv)} ({s_pos/len(all_clv)*100:.1f}%)")
        print(f"   Flagged avg CLV: {f_avg:+.2f}%")
        # NEW: season-level drift on entries where opening was captured
        flagged_drift = [e for e in flagged_clv if e.get("open_close_drift") is not None]
        if flagged_drift:
            f_drift = round(sum(e["open_close_drift"] for e in flagged_drift) / len(flagged_drift), 2)
            print(f"   Flagged Open→Close drift: {f_drift:+.2f}% ({len(flagged_drift)} games)")

    print("=" * 50)
    if total > 0:
        print(f"Overall: {correct}/{total} correct ({correct/total*100:.1f}%)")
    if bet_total > 0:
        print(f"Flagged bets: {bet_correct}/{bet_total} correct ({bet_correct/bet_total*100:.1f}%)")
    else:
        print("No flagged bets today")

if __name__ == '__main__':
    import sys
    lv = timezone(timedelta(hours=-7))
    if len(sys.argv) > 1:
        target = sys.argv[1]   # e.g. "2026-06-02"
    else:
        target = datetime.now(lv).strftime("%Y-%m-%d")
    print(f"Checking results for: {target}")
    check_picks(target)