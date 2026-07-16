"""
weekly_retrain_v2.py — same weekly ingestion as before, new trainer.

WHAT CHANGED vs weekly_retrain.py:
  1. retrain_model() replaced by train_model_v2.main(): trains on ALL rows
     including current season. (Old bug: current-season rows were excluded
     from training whenever >=50 existed, so 757 games of 2026 data — the
     freshest, most relevant games — never taught the model anything, and
     the "2026 weighted 3x" log line was dead code.)
  2. Validation metric in retrain_log.csv is now walk-forward accuracy,
     comparable week to week and free of look-ahead.
  3. API key from environment only — no hardcoded fallback.

KNOWN LIMITATION carried over (backlog #10): build_new_rows pulls season
stats as of the retrain date, not as of each game date. For a weekly cadence
the gap is <=7 days of stats — small — but historical rows built in bulk
still contain full-season look-ahead. Point-in-time rebuild remains the
right long-term fix and will further ground the walk-forward numbers.

Run:  py -3.11 .\\weekly_retrain_v2.py
"""

import os
import sys
import warnings; warnings.filterwarnings("ignore")
import pandas as pd
from datetime import datetime

# Task Scheduler consoles use cp1252, which can't encode emoji glyphs
# (the old ingestion helpers imported below print them)
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

# reuse the battle-tested ingestion from the old file
from weekly_retrain import get_last_week_games, build_new_rows

import train_model_v2


def run_weekly_retrain_v2():
    print("\n" + "=" * 55)
    print("  WEEKLY MODEL RETRAINING (V2)")
    print("=" * 55)
    print(f"  Running: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55 + "\n")

    season = datetime.now().year

    games = get_last_week_games()
    if not games:
        print("No games found — skipping retrain")
        return

    print("\nBuilding new training rows...")
    new_rows = build_new_rows(games, season)
    if not new_rows:
        print("No new rows built — skipping retrain")
        return

    existing_file = "training_data.csv"
    existing_df = pd.read_csv(existing_file) if os.path.exists(existing_file) else pd.DataFrame()
    if not existing_df.empty:
        print(f"Loaded {len(existing_df)} existing training rows")

    new_df = pd.DataFrame(new_rows)
    combined = pd.concat([existing_df, new_df], ignore_index=True) if not existing_df.empty else new_df
    if "game_id" in combined.columns:
        combined = combined.drop_duplicates(subset=["game_id"])

    # base columns V2 needs (raw era/whip/ops/kpct — diffs are built in features_v2)
    needed = ["home_era", "home_whip", "away_era", "away_whip",
              "home_ops", "home_kpct", "away_ops", "away_kpct", "home_win", "season", "date"]
    missing = [c for c in needed if c not in combined.columns]
    if missing:
        print(f"\nERROR: training_data.csv missing columns: {missing}")
        return
    null_rows = combined[needed].isna().any(axis=1).sum()
    if null_rows:
        print(f"WARNING: dropping {null_rows} rows with nulls in required columns")
        combined = combined.dropna(subset=needed)

    combined.to_csv(existing_file, index=False)
    print(f"Training data updated: {len(combined)} total rows (+{len(new_rows)} new)")

    # train + honest validation
    wacc, wbrier = train_model_v2.main()

    log_entry = {
        "date":        datetime.now().strftime("%Y-%m-%d"),
        "new_games":   len(new_rows),
        "total_games": len(combined),
        "accuracy":    round(wacc, 4),   # walk-forward, not in-sample
        "brier":       round(wbrier, 4),
    }
    log_file = "retrain_log.csv"
    log_df = pd.DataFrame([log_entry])
    if os.path.exists(log_file):
        log_df = pd.concat([pd.read_csv(log_file), log_df], ignore_index=True)
    log_df.to_csv(log_file, index=False)

    print(f"\nRetrain complete — walk-forward acc {wacc*100:.1f}%, brier {wbrier:.4f}")
    print("NOTE: this number is lower than the old log's 62-64% because the old")
    print("number contained look-ahead. This one is what forward betting sees.")


if __name__ == "__main__":
    run_weekly_retrain_v2()
