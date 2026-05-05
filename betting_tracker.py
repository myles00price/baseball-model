import csv
import os
import requests
from glob import glob
from datetime import datetime, timedelta, timezone

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
    try:
        odds = float(odds)
        if odds < 0:
            return round(stake * (100 / -odds), 2)
        else:
            return round(stake * (odds / 100), 2)
    except:
        return None

def run_tracker():
    print("\n" + "=" * 65)
    print("  MLB BETTING TRACKER — FULL SEASON")
    print("=" * 65)

    # Tracking variables
    total_games = 0
    total_correct = 0
    flagged_total = 0
    flagged_correct = 0
    total_profit = 0.0
    stake = 100.0

    # Streak tracking
    current_streak = 0
    streak_type = None
    best_win_streak = 0
    worst_loss_streak = 0
    temp_streak = 0
    temp_type = None

    # Category tracking
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

    # Day by day
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
            won = model_winner == actual_winner

            total_games += 1
            day_total += 1
            if won:
                total_correct += 1
                day_correct += 1

            # Streak tracking
            if won:
                if temp_type == "W":
                    temp_streak += 1
                else:
                    temp_streak = 1
                    temp_type = "W"
                best_win_streak = max(best_win_streak, temp_streak)
            else:
                if temp_type == "L":
                    temp_streak += 1
                else:
                    temp_streak = 1
                    temp_type = "L"
                worst_loss_streak = max(worst_loss_streak, temp_streak)

            # Flagged bet tracking
            is_flagged = "BET" in str(flag)
            if is_flagged:
                flagged_total += 1
                day_flagged += 1
                bet_odds = dk_home if model_winner == home else dk_away
                payout = american_to_payout(bet_odds, stake)

                if won:
                    flagged_correct += 1
                    day_flagged_correct += 1
                    profit = payout if payout else 0
                    total_profit += profit
                    day_profit += profit
                else:
                    total_profit -= stake
                    day_profit -= stake

            # Sharp signal tracking
            if "CONFIRMED" in str(sharp):
                sharp_confirmed_total += 1
                if won:
                    sharp_confirmed_correct += 1
            elif "FADE" in str(sharp):
                sharp_fade_total += 1
                if won:
                    sharp_fade_correct += 1

            # Edge bucket tracking
            try:
                dk_edge_str = pick.get("DK Edge Away", "N/A")
                if dk_edge_str and dk_edge_str != "N/A":
                    e = abs(float(dk_edge_str.replace("%", "")
                                            .replace("** BET **", "")
                                            .replace("+", "")
                                            .strip()))
                    if e < 3:
                        b = "0-3%"
                    elif e < 6:
                        b = "3-6%"
                    elif e < 10:
                        b = "6-10%"
                    else:
                        b = "10%+"
                    buckets[b]["total"] += 1
                    if won:
                        buckets[b]["correct"] += 1
            except:
                pass

        daily.append({
            "date": date_str,
            "total": day_total,
            "correct": day_correct,
            "flagged": day_flagged,
            "flagged_correct": day_flagged_correct,
            "profit": day_profit
        })

    # ── Display ───────────────────────────────────────────────────

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
        print(f"  P&L ($100/bet):         {pnl_str}")
        print(f"  ROI:                   {roi:+.1f}%")
    print(f"  Best win streak:       {best_win_streak}")
    print(f"  Worst loss streak:     {worst_loss_streak}")

    print(f"\n📈 Accuracy By Edge Size:")
    for bucket, data in buckets.items():
        if data["total"]:
            pct = data["correct"] / data["total"] * 100
            bar = "█" * int(pct / 5)
            print(f"  {bucket:<8} {data['correct']}/{data['total']} ({pct:.1f}%) {bar}")

    if sharp_confirmed_total:
        print(f"\n🎯 Sharp Signal Performance:")
        conf_pct = sharp_confirmed_correct/sharp_confirmed_total*100
        fade_pct = sharp_fade_correct/sharp_fade_total*100 if sharp_fade_total else 0
        print(f"  CONFIRMED ✓:  {sharp_confirmed_correct}/{sharp_confirmed_total} ({conf_pct:.1f}%)")
        if sharp_fade_total:
            print(f"  FADE ✗:       {sharp_fade_correct}/{sharp_fade_total} ({fade_pct:.1f}%)")

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