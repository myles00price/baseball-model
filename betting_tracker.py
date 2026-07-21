import csv
import os
import sys
import requests
from glob import glob
from datetime import datetime, timedelta, timezone

from features_v2 import flagged_side

# Task Scheduler consoles use cp1252, which can't encode emoji glyphs
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

# ─────────────────────────────────────────────────────────────
# betting_tracker.py — Additions:
#   • BUGFIX: edge bucket assignment now uses the edge column
#     matching the model's pick (was: always DK Edge Away)
#   • NEW: flagged-bet breakdown by Sharp signal (CONFIRMED/FADE/N/A)
#   • NEW: flagged-bet breakdown by Lineup Source (CONFIRMED/PARTIAL/ESTIMATED)
#   • NEW: hypothetical filter P&L — what would season P&L look like
#     if we had vetoed certain BET flags? Pure analysis, no behavior change.
#
# P&L math already used real moneyline payout (american_to_payout) — unchanged.
# ─────────────────────────────────────────────────────────────

def get_game_results(date_str):
    schedule = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={"sportId": 1, "date": date_str, "hydrate": "linescore"}
    ).json()
    results = {}
    for date in schedule.get("dates", []):
        for game in date.get("games", []):
            if game.get("status", {}).get("abstractGameState") != "Final":
                continue
            home = game["teams"]["home"]["team"]["name"]
            away = game["teams"]["away"]["team"]["name"]
            home_score = game["teams"]["home"].get("score", 0)
            away_score = game["teams"]["away"].get("score", 0)
            winner = home if home_score > away_score else away
            results[home] = {"winner": winner, "home": home, "away": away,
                           "home_score": home_score, "away_score": away_score}
            results[away] = results[home]
    return results

def american_to_prob(odds):
    try:
        odds = float(odds)
        if odds < 0:
            return round((-odds) / (-odds + 100) * 100, 1)
        else:
            return round(100 / (odds + 100) * 100, 1)
    except:
        return None

def american_to_payout(odds, stake=100):
    """Win amount on a given stake at American odds. -200 stake $100 wins $50."""
    try:
        odds = float(odds)
        if odds < 0:
            return round(stake * (100 / -odds), 2)
        else:
            return round(stake * (odds / 100), 2)
    except:
        return None

def categorize_sharp(sharp_str):
    """Bucket the Sharp Signal column into clean categories."""
    s = str(sharp_str)
    if "CONFIRMED" in s: return "CONFIRMED"
    if "FADE" in s:      return "FADE"
    return "N/A"

def categorize_lineup(lineup_str):
    """Bucket Lineup Source — same vocabulary master.py writes."""
    s = str(lineup_str).upper()
    if "CONFIRMED" in s: return "CONFIRMED"
    if "PARTIAL"   in s: return "PARTIAL"
    return "ESTIMATED"

def run_tracker():
    print("\n" + "=" * 65)
    print("  MLB BETTING TRACKER — FULL SEASON")
    print("=" * 65)

    stake = 100.0
    total_games = 0
    total_correct = 0
    flagged_total = 0
    flagged_correct = 0
    total_profit = 0.0

    # Streak tracking (overall, not flagged)
    best_win_streak = 0
    worst_loss_streak = 0
    temp_streak = 0
    temp_type = None

    # Category tracking — overall (all games, flagged or not)
    sharp_confirmed_total = 0
    sharp_confirmed_correct = 0
    sharp_fade_total = 0
    sharp_fade_correct = 0

    # Edge bucket tracking
    buckets = {
        "0-3%":  {"total": 0, "correct": 0, "profit": 0.0},
        "3-6%":  {"total": 0, "correct": 0, "profit": 0.0},
        "6-10%": {"total": 0, "correct": 0, "profit": 0.0},
        "10%+":  {"total": 0, "correct": 0, "profit": 0.0},
    }

    # ── NEW: flagged-bet breakdown by sharp signal and lineup source ──
    flag_by_sharp = {
        "CONFIRMED": {"total": 0, "correct": 0, "profit": 0.0},
        "FADE":      {"total": 0, "correct": 0, "profit": 0.0},
        "N/A":       {"total": 0, "correct": 0, "profit": 0.0},
    }
    flag_by_lineup = {
        "CONFIRMED": {"total": 0, "correct": 0, "profit": 0.0},
        "PARTIAL":   {"total": 0, "correct": 0, "profit": 0.0},
        "ESTIMATED": {"total": 0, "correct": 0, "profit": 0.0},
    }

    # ── NEW: hypothetical filter P&L scenarios ──
    # Each scenario tracks the P&L you'd have if certain BET flags were vetoed.
    hypo = {
        "no_fade":           {"bets": 0, "wins": 0, "profit": 0.0},  # skip Sharp FADE
        "no_estimated":      {"bets": 0, "wins": 0, "profit": 0.0},  # skip ESTIMATED lineups
        "no_fade_no_est":    {"bets": 0, "wins": 0, "profit": 0.0},  # skip either
    }

    daily = []

    picks_files = sorted(glob("picks_2026-*.csv"))

    for filename in picks_files:
        date_str = filename.replace("picks_", "").replace(".csv", "")
        picks = []
        try:
            with open(filename, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    picks.append(row)
        except:
            continue

        if not picks:
            continue

        results = get_game_results(date_str)
        if not results:
            continue

        day_total = 0
        day_correct = 0
        day_flagged = 0
        day_flagged_correct = 0
        day_profit = 0.0

        for pick in picks:
            away = pick.get("Away", "")
            home = pick.get("Home", "")
            away_prob = pick.get("Model Away%", "None")
            home_prob = pick.get("Model Home%", "None")
            flag = pick.get("Flag", "")
            sharp = pick.get("Sharp Signal", "N/A")
            lineup_src = pick.get("Lineup Source", "")
            dk_away = pick.get("DK Away Odds", "N/A")
            dk_home = pick.get("DK Home Odds", "N/A")

            if away_prob == "None" or home_prob == "None":
                continue
            try:
                away_prob = float(away_prob)
                home_prob = float(home_prob)
            except:
                continue

            result = results.get(home) or results.get(away)
            if not result:
                continue

            actual_winner = result["winner"]
            model_winner = away if away_prob > home_prob else home
            picked_home = (home_prob > away_prob)
            won = model_winner == actual_winner

            total_games += 1
            day_total += 1
            if won:
                total_correct += 1
                day_correct += 1

            # Overall streak tracking
            if won:
                if temp_type == "W": temp_streak += 1
                else: temp_streak = 1; temp_type = "W"
                best_win_streak = max(best_win_streak, temp_streak)
            else:
                if temp_type == "L": temp_streak += 1
                else: temp_streak = 1; temp_type = "L"
                worst_loss_streak = max(worst_loss_streak, temp_streak)

            sharp_cat = categorize_sharp(sharp)
            lineup_cat = categorize_lineup(lineup_src)

            # Flagged bet tracking — grade the side that carried the BET flag
            # (features_v2.flagged_side): often the value dog, NOT model_winner.
            is_flagged = "BET" in str(flag)
            bet_profit = 0.0
            if is_flagged:
                flagged_total += 1
                day_flagged += 1
                side = flagged_side(pick)
                bet_team = away if side == "away" else home if side == "home" else model_winner
                bet_won = bet_team == actual_winner
                bet_odds = dk_home if bet_team == home else dk_away
                payout = american_to_payout(bet_odds, stake)

                if bet_won:
                    flagged_correct += 1
                    day_flagged_correct += 1
                    bet_profit = payout if payout else 0
                else:
                    bet_profit = -stake

                total_profit += bet_profit
                day_profit += bet_profit

                # NEW: per-sharp and per-lineup flagged breakdowns
                flag_by_sharp[sharp_cat]["total"] += 1
                if bet_won: flag_by_sharp[sharp_cat]["correct"] += 1
                flag_by_sharp[sharp_cat]["profit"] += bet_profit

                flag_by_lineup[lineup_cat]["total"] += 1
                if bet_won: flag_by_lineup[lineup_cat]["correct"] += 1
                flag_by_lineup[lineup_cat]["profit"] += bet_profit

                # NEW: hypothetical veto P&L
                # Scenario: skip if Sharp FADE
                if sharp_cat != "FADE":
                    hypo["no_fade"]["bets"] += 1
                    if won: hypo["no_fade"]["wins"] += 1
                    hypo["no_fade"]["profit"] += bet_profit
                # Scenario: skip if ESTIMATED lineup
                if lineup_cat != "ESTIMATED":
                    hypo["no_estimated"]["bets"] += 1
                    if won: hypo["no_estimated"]["wins"] += 1
                    hypo["no_estimated"]["profit"] += bet_profit
                # Scenario: skip if EITHER
                if sharp_cat != "FADE" and lineup_cat != "ESTIMATED":
                    hypo["no_fade_no_est"]["bets"] += 1
                    if won: hypo["no_fade_no_est"]["wins"] += 1
                    hypo["no_fade_no_est"]["profit"] += bet_profit

            # Overall sharp tracking (all games, not just flagged)
            if sharp_cat == "CONFIRMED":
                sharp_confirmed_total += 1
                if won: sharp_confirmed_correct += 1
            elif sharp_cat == "FADE":
                sharp_fade_total += 1
                if won: sharp_fade_correct += 1

            # ── BUGFIX: edge bucket now uses the edge matching the picked side ──
            try:
                edge_col = "DK Edge Home" if picked_home else "DK Edge Away"
                dk_edge_str = pick.get(edge_col, "N/A")
                if dk_edge_str and dk_edge_str != "N/A":
                    e = abs(float(str(dk_edge_str).replace("%", "")
                                                  .replace("** BET **", "")
                                                  .replace("+", "")
                                                  .strip()))
                    if   e < 3:  b = "0-3%"
                    elif e < 6:  b = "3-6%"
                    elif e < 10: b = "6-10%"
                    else:        b = "10%+"
                    buckets[b]["total"] += 1
                    if won: buckets[b]["correct"] += 1
            except:
                pass

        daily.append({
            "date": date_str,
            "total": day_total, "correct": day_correct,
            "flagged": day_flagged, "flagged_correct": day_flagged_correct,
            "profit": day_profit
        })

    # ── Display ──────────────────────────────────────────────────────

    print("\n📅 Daily Breakdown:")
    print(f"  {'Date':<12} {'Overall':>10} {'Flagged':>10} {'P&L':>8}")
    print(f"  {'-'*44}")
    for d in daily:
        overall = f"{d['correct']}/{d['total']} ({d['correct']/d['total']*100:.0f}%)" if d['total'] else "N/A"
        flagged = f"{d['flagged_correct']}/{d['flagged']} ({d['flagged_correct']/d['flagged']*100:.0f}%)" if d['flagged'] else "No flags"
        pnl = f"+${d['profit']:.2f}" if d['profit'] >= 0 else f"-${abs(d['profit']):.2f}"
        print(f"  {d['date']:<12} {overall:>10} {flagged:>10} {pnl:>8}")

    print(f"\n📊 Season Summary:")
    if total_games:
        print(f"  Total games graded:    {total_games}")
        print(f"  Overall accuracy:      {total_correct}/{total_games} ({total_correct/total_games*100:.1f}%)")
    if flagged_total:
        roi = (total_profit / (flagged_total * stake)) * 100
        pnl_str = f"+${total_profit:.2f}" if total_profit >= 0 else f"-${abs(total_profit):.2f}"
        print(f"  Flagged bets:          {flagged_correct}/{flagged_total} ({flagged_correct/flagged_total*100:.1f}%)")
        print(f"  P&L ($100/bet):        {pnl_str}")
        print(f"  ROI:                   {roi:+.1f}%")
    print(f"  Best win streak:       {best_win_streak}")
    print(f"  Worst loss streak:     {worst_loss_streak}")

    print(f"\n📈 Accuracy By Edge Size (picked-side edge):")
    for bucket, data in buckets.items():
        if data["total"]:
            pct = data["correct"] / data["total"] * 100
            bar = "█" * int(pct / 5)
            print(f"  {bucket:<8} {data['correct']}/{data['total']} ({pct:.1f}%) {bar}")

    # ── NEW: Flagged breakdown by Sharp signal ──
    if flagged_total:
        print(f"\n🎯 Flagged Bets — by Sharp Signal:")
        for cat in ["CONFIRMED", "FADE", "N/A"]:
            d = flag_by_sharp[cat]
            if d["total"]:
                pct = d["correct"]/d["total"]*100
                pnl = f"+${d['profit']:.2f}" if d['profit'] >= 0 else f"-${abs(d['profit']):.2f}"
                print(f"  {cat:<10} {d['correct']}/{d['total']} ({pct:.1f}%) — P&L {pnl}")

    # ── NEW: Flagged breakdown by Lineup Source ──
    if flagged_total:
        print(f"\n📋 Flagged Bets — by Lineup Source:")
        for cat in ["CONFIRMED", "PARTIAL", "ESTIMATED"]:
            d = flag_by_lineup[cat]
            if d["total"]:
                pct = d["correct"]/d["total"]*100
                pnl = f"+${d['profit']:.2f}" if d['profit'] >= 0 else f"-${abs(d['profit']):.2f}"
                print(f"  {cat:<10} {d['correct']}/{d['total']} ({pct:.1f}%) — P&L {pnl}")

    # ── Overall Sharp signal (all games, kept for reference) ──
    if sharp_confirmed_total or sharp_fade_total:
        print(f"\n🎯 Sharp Signal — All Games (not just flagged):")
        if sharp_confirmed_total:
            cp = sharp_confirmed_correct/sharp_confirmed_total*100
            print(f"  CONFIRMED ✓:  {sharp_confirmed_correct}/{sharp_confirmed_total} ({cp:.1f}%)")
        if sharp_fade_total:
            fp = sharp_fade_correct/sharp_fade_total*100
            print(f"  FADE ✗:       {sharp_fade_correct}/{sharp_fade_total} ({fp:.1f}%)")

    # ── NEW: Hypothetical filter P&L — does NOT change behavior ──
    if flagged_total:
        print(f"\n🧪 Hypothetical Filter P&L (read-only — what if these BETs had been vetoed):")
        print(f"  {'Scenario':<28} {'Bets':>6} {'Wins':>6} {'Win%':>7} {'P&L':>10} {'ROI':>8}")
        print(f"  {'-'*70}")

        actual = {"bets": flagged_total, "wins": flagged_correct, "profit": total_profit}
        scenarios = [
            ("Current (no filter)",     actual),
            ("Skip Sharp FADE",         hypo["no_fade"]),
            ("Skip ESTIMATED lineups",  hypo["no_estimated"]),
            ("Skip both",               hypo["no_fade_no_est"]),
        ]
        for label, d in scenarios:
            bets = d["bets"] if "bets" in d else d.get("bets", 0)
            wins = d.get("wins", d.get("correct", 0))
            profit = d["profit"]
            win_pct = wins/bets*100 if bets else 0
            roi = (profit/(bets*stake))*100 if bets else 0
            pnl = f"+${profit:.2f}" if profit >= 0 else f"-${abs(profit):.2f}"
            print(f"  {label:<28} {bets:>6} {wins:>6} {win_pct:>6.1f}% {pnl:>10} {roi:>+7.1f}%")

    print(f"\n💡 Betting Confidence:")
    if flagged_total >= 10:
        flag_pct = flagged_correct/flagged_total*100
        if flag_pct >= 57 and flagged_total >= 30:
            print(f"  ✅ READY — {flag_pct:.1f}% on {flagged_total} bets → consider $100 bets")
        elif flag_pct >= 55 and flagged_total >= 20:
            print(f"  🟡 CLOSE — {flag_pct:.1f}% on {flagged_total} bets → paper trade only")
        else:
            print(f"  🔴 NOT YET — {flag_pct:.1f}% on {flagged_total} bets → need 55%+ over 30+ bets")
    else:
        print(f"  ⏳ Need more data — only {flagged_total} flagged bets so far")

    print("\n" + "=" * 65)

if __name__ == "__main__":
    run_tracker()