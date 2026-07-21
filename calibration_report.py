import csv
import os
import sys
import requests

from features_v2 import flagged_side

# Task Scheduler consoles use cp1252, which can't encode emoji glyphs
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
from datetime import datetime, timedelta, timezone
from glob import glob

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
            results[home] = {"winner": winner, "home": home, "away": away}
            results[away] = {"winner": winner, "home": home, "away": away}
    return results

def load_picks(filename):
    picks = []
    try:
        with open(filename, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                picks.append(row)
    except:
        pass
    return picks

def run_calibration():
    print("\n" + "=" * 65)
    print("  MLB MODEL CALIBRATION REPORT")
    print("=" * 65)

    total_games       = 0
    total_correct     = 0
    flagged_games     = 0
    flagged_correct   = 0

    home_fav_total    = 0; home_fav_correct    = 0
    home_dog_total    = 0; home_dog_correct    = 0
    away_fav_total    = 0; away_fav_correct    = 0
    away_dog_total    = 0; away_dog_correct    = 0

    edge_buckets = {
        "0-3%":   [0, 0],
        "3-6%":   [0, 0],
        "6-10%":  [0, 0],
        "10%+":   [0, 0],
    }

    coors_total = 0; coors_correct = 0
    daily_results = []

    # MAE trackers
    mae_errors = []           # all games
    mae_flagged_errors = []   # flagged bets only
    mae_zone_errors = []      # 6-10% zone only
    sharp_confirmed_errors = []
    sharp_fade_errors = []

    picks_files = sorted(glob("picks_2026-*.csv"))

    for filename in picks_files:
        date_str = filename.replace("picks_", "").replace(".csv", "")
        picks = load_picks(filename)
        if not picks:
            continue

        results = get_game_results(date_str)
        if not results:
            continue

        day_total = day_correct = day_flagged = day_flagged_correct = 0

        for pick in picks:
            away = pick.get("Away", "")
            home = pick.get("Home", "")
            away_prob = pick.get("Model Away%", "None")
            home_prob = pick.get("Model Home%", "None")
            flag = pick.get("Flag", "")
            sharp = pick.get("Sharp Signal", "N/A")

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
            model_prob = away_prob if away_prob > home_prob else home_prob
            won = model_winner == actual_winner

            # True outcome for MAE — 100 if won, 0 if lost
            true_outcome = 100.0 if won else 0.0
            abs_error = abs(model_prob - true_outcome)
            mae_errors.append(abs_error)

            total_games += 1; day_total += 1
            if won: total_correct += 1; day_correct += 1

            # Grade flagged bets on the side that carried the flag (often the
            # value dog), not the model's pick side — see features_v2.flagged_side
            is_flagged = "BET" in str(flag)
            if is_flagged:
                side = flagged_side(pick)
                bet_team = away if side == "away" else home if side == "home" else model_winner
                bet_won = bet_team == actual_winner
                flagged_games += 1; day_flagged += 1
                mae_flagged_errors.append(abs_error)
                if bet_won: flagged_correct += 1; day_flagged_correct += 1

            # Edge bucket
            dk_edge_away = pick.get("DK Edge Away", "N/A")
            try:
                e = abs(float(dk_edge_away.replace("%", "").replace("** BET **", "").strip()))
                if e < 3:
                    edge_buckets["0-3%"][0] += 1
                    if won: edge_buckets["0-3%"][1] += 1
                elif e < 6:
                    edge_buckets["3-6%"][0] += 1
                    if won: edge_buckets["3-6%"][1] += 1
                elif e < 10:
                    edge_buckets["6-10%"][0] += 1
                    if won: edge_buckets["6-10%"][1] += 1
                    mae_zone_errors.append(abs_error)
                else:
                    edge_buckets["10%+"][0] += 1
                    if won: edge_buckets["10%+"][1] += 1
            except:
                pass

            # Sharp signal MAE
            if "CONFIRMED" in str(sharp):
                sharp_confirmed_errors.append(abs_error)
            elif "FADE" in str(sharp):
                sharp_fade_errors.append(abs_error)

            # Category tracking
            model_home_fav = home_prob > away_prob
            if model_home_fav and home_prob > 55:
                home_fav_total += 1
                if won and model_winner == home: home_fav_correct += 1
            elif model_home_fav and home_prob <= 55:
                home_dog_total += 1
                if won and model_winner == home: home_dog_correct += 1
            elif not model_home_fav and away_prob > 55:
                away_fav_total += 1
                if won and model_winner == away: away_fav_correct += 1
            else:
                away_dog_total += 1
                if won and model_winner == away: away_dog_correct += 1

            if home == "Colorado Rockies":
                coors_total += 1
                if won: coors_correct += 1

        daily_results.append({
            "date": date_str, "total": day_total, "correct": day_correct,
            "flagged": day_flagged, "flagged_correct": day_flagged_correct
        })

    # ── Display ───────────────────────────────────────────────────

    print("\n📅 Daily Breakdown:")
    print(f"  {'Date':<12} {'Overall':>10} {'Flagged':>10}")
    print(f"  {'-'*35}")
    for d in daily_results:
        overall = f"{d['correct']}/{d['total']} ({d['correct']/d['total']*100:.0f}%)" if d['total'] else "N/A"
        flagged = f"{d['flagged_correct']}/{d['flagged']} ({d['flagged_correct']/d['flagged']*100:.0f}%)" if d['flagged'] else "No flags"
        print(f"  {d['date']:<12} {overall:>10} {flagged:>10}")

    print(f"\n📊 Overall Performance:")
    if total_games:
        print(f"  Total games graded:  {total_games}")
        print(f"  Overall accuracy:    {total_correct}/{total_games} ({total_correct/total_games*100:.1f}%)")
    if flagged_games:
        print(f"  Flagged bets:        {flagged_correct}/{flagged_games} ({flagged_correct/flagged_games*100:.1f}%)")

    # ── MAE Section ───────────────────────────────────────────────
    print(f"\n📐 Mean Absolute Error (MAE):")
    print(f"  MAE = avg distance between model's confidence % and true outcome (0 or 100)")
    print(f"  Lower is better. A perfectly calibrated model at 60% confidence would have MAE ~40.")

    if mae_errors:
        overall_mae = round(sum(mae_errors) / len(mae_errors), 1)
        # Baseline: what MAE would be if model always said 50%
        baseline_mae = round(sum(abs(50 - (100 if i < total_correct else 0)) for i in range(total_games)) / total_games, 1)
        improvement = round(baseline_mae - overall_mae, 1)
        imp_str = f"+{improvement}" if improvement > 0 else str(improvement)
        print(f"\n  Overall MAE:         {overall_mae} (baseline 50% = {baseline_mae}, model {'better' if improvement > 0 else 'worse'} by {abs(improvement)})")

    if mae_flagged_errors:
        flagged_mae = round(sum(mae_flagged_errors) / len(mae_flagged_errors), 1)
        print(f"  Flagged bets MAE:    {flagged_mae}")

    if mae_zone_errors:
        zone_mae = round(sum(mae_zone_errors) / len(mae_zone_errors), 1)
        print(f"  6-10% Zone MAE:      {zone_mae}")

    if sharp_confirmed_errors:
        conf_mae = round(sum(sharp_confirmed_errors) / len(sharp_confirmed_errors), 1)
        print(f"  Sharp CONFIRMED MAE: {conf_mae}")

    if sharp_fade_errors:
        fade_mae = round(sum(sharp_fade_errors) / len(sharp_fade_errors), 1)
        print(f"  Sharp FADE MAE:      {fade_mae}")

    if mae_errors and mae_flagged_errors:
        diff = round((sum(mae_errors)/len(mae_errors)) - (sum(mae_flagged_errors)/len(mae_flagged_errors)), 1)
        if diff > 0:
            print(f"\n  ✅ Model is {diff} MAE points MORE accurate on flagged bets than average")
        elif diff < 0:
            print(f"\n  ⚠️  Model is {abs(diff)} MAE points LESS accurate on flagged bets than average")

    print(f"\n🎯 Accuracy By Category:")
    cats = [
        ("Home favorites (>55%)", home_fav_total, home_fav_correct),
        ("Home underdogs (<55%)", home_dog_total, home_dog_correct),
        ("Away favorites (>55%)", away_fav_total, away_fav_correct),
        ("Away underdogs (<55%)", away_dog_total, away_dog_correct),
    ]
    for label, total, correct in cats:
        if total:
            print(f"  {label:<28} {correct}/{total} ({correct/total*100:.1f}%)")

    print(f"\n📈 Accuracy By Edge Size:")
    for bucket, (total, correct) in edge_buckets.items():
        if total:
            pct = correct/total*100
            bar = "█" * int(pct/5)
            print(f"  {bucket:<8} {correct}/{total} ({pct:.1f}%) {bar}")

    if coors_total:
        print(f"\n🏔️  Coors Field:  {coors_correct}/{coors_total} ({coors_correct/coors_total*100:.1f}%)")

    print(f"\n💡 Bias Check:")
    home_total = home_fav_total + home_dog_total
    away_total = away_fav_total + away_dog_total
    home_correct = home_fav_correct + home_dog_correct
    away_correct = away_fav_correct + away_dog_correct
    if home_total:
        print(f"  When model picks home team: {home_correct}/{home_total} ({home_correct/home_total*100:.1f}%)")
    if away_total:
        print(f"  When model picks away team: {away_correct}/{away_total} ({away_correct/away_total*100:.1f}%)")
    if home_total and away_total:
        diff = (home_correct/home_total*100) - (away_correct/away_total*100)
        if abs(diff) > 5:
            bias = "HOME" if diff > 0 else "AWAY"
            print(f"  ⚠️  Possible {bias} team bias detected ({abs(diff):.1f}% difference)")
        else:
            print(f"  ✅ No significant home/away bias detected")

    print("\n" + "=" * 65)

if __name__ == '__main__':
    run_calibration()