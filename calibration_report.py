import csv
import os
import requests
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

    # Stats trackers
    total_games       = 0
    total_correct     = 0
    flagged_games     = 0
    flagged_correct   = 0

    # Category trackers
    home_fav_total    = 0; home_fav_correct    = 0
    home_dog_total    = 0; home_dog_correct    = 0
    away_fav_total    = 0; away_fav_correct    = 0
    away_dog_total    = 0; away_dog_correct    = 0

    # Edge bucket trackers
    edge_buckets = {
        "0-3%":   [0, 0],
        "3-6%":   [0, 0],
        "6-10%":  [0, 0],
        "10%+":   [0, 0],
    }

    # Park trackers
    coors_total = 0; coors_correct = 0

    # Day by day
    daily_results = []

    picks_files = sorted(glob("picks_2026-*.csv"))

    for filename in picks_files:
        date_str = filename.replace("picks_", "").replace(".csv", "")
        picks = load_picks(filename)
        if not picks:
            continue

        results = get_game_results(date_str)
        if not results:
            continue

        day_total = 0
        day_correct = 0
        day_flagged = 0
        day_flagged_correct = 0

        for pick in picks:
            away = pick.get("Away", "")
            home = pick.get("Home", "")
            away_prob = pick.get("Model Away%", "None")
            home_prob = pick.get("Model Home%", "None")
            flag = pick.get("Flag", "")

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

            # Flag tracking
            is_flagged = "BET" in str(flag)
            if is_flagged:
                flagged_games += 1
                day_flagged += 1
                if won:
                    flagged_correct += 1
                    day_flagged_correct += 1

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
                else:
                    edge_buckets["10%+"][0] += 1
                    if won: edge_buckets["10%+"][1] += 1
            except:
                pass

            # Coors tracking
            if home == "Colorado Rockies":
                coors_total += 1
                if won: coors_correct += 1

        daily_results.append({
            "date": date_str,
            "total": day_total,
            "correct": day_correct,
            "flagged": day_flagged,
            "flagged_correct": day_flagged_correct
        })

    # ── Display Results ───────────────────────────────────────────

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
        home_pct = home_correct/home_total*100
        away_pct = away_correct/away_total*100
        diff = home_pct - away_pct
        if abs(diff) > 5:
            bias = "HOME" if diff > 0 else "AWAY"
            print(f"  ⚠️  Possible {bias} team bias detected ({abs(diff):.1f}% difference)")
        else:
            print(f"  ✅ No significant home/away bias detected")

    print("\n" + "=" * 65)

if __name__ == '__main__':
    run_calibration()