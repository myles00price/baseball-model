"""
backfill_fip.py — ONE-TIME migration.

Adds home_fip / away_fip / fip_diff columns to existing training_data.csv
by re-fetching historical pitcher stats and computing FIP for each game's
home and away starter. Then drops home_era / home_whip / away_era /
away_whip / era_diff.

After this finishes successfully, the new FIP-based weekly_retrain.py
can run normally.

Behaviour:
  • Backs up training_data.csv → training_data_pre_fip_backup.csv (first run)
  • Resumable — already-backfilled rows are skipped on rerun
  • Checkpoints every 25 rows so a crash/interrupt doesn't lose progress
  • Drops rows where FIP couldn't be recovered (no boxscore / no pitcher data)
  • Cleans up old era/whip columns only at the very end

Run:  py -3.11 .\backfill_fip.py

Expected runtime: roughly 30–60 min for a 7,800-row training set
(MLB Stats API has no documented hard rate limit, but be reasonable).
"""

import os
import numpy as np
import pandas as pd

from weekly_retrain import get_boxscore_pitchers, get_pitcher_stats

CSV_PATH    = "training_data.csv"
BACKUP_PATH = "training_data_pre_fip_backup.csv"

OLD_COLS_TO_DROP = [
    "home_era", "home_whip", "away_era", "away_whip", "era_diff",
]

CHECKPOINT_EVERY = 25


def main():
    if not os.path.exists(CSV_PATH):
        print(f"❌ {CSV_PATH} not found in current directory")
        return

    df = pd.read_csv(CSV_PATH)
    print(f"Loaded {len(df)} rows from {CSV_PATH}")

    # Safety backup before mutating anything (only created once)
    if not os.path.exists(BACKUP_PATH):
        df.to_csv(BACKUP_PATH, index=False)
        print(f"Backup saved → {BACKUP_PATH}")
    else:
        print(f"Backup already exists at {BACKUP_PATH} (skipping)")

    # Initialise FIP columns if not present
    if "home_fip" not in df.columns:
        df["home_fip"] = np.nan
        df["away_fip"] = np.nan
        df["fip_diff"] = np.nan

    todo_idx = df[df["home_fip"].isna()].index.tolist()
    print(f"Rows needing backfill: {len(todo_idx)} / {len(df)}")

    if not todo_idx:
        print("Nothing to do. Cleaning up old columns and exiting.")
        finalise(df)
        return

    ok = 0
    skipped = 0

    for n, idx in enumerate(todo_idx):
        if n % CHECKPOINT_EVERY == 0:
            print(f"  {n}/{len(todo_idx)}  (ok={ok}, skipped={skipped})")
            if n > 0:
                # Checkpoint — keeps old columns around in case we crash;
                # they're only dropped at the end in finalise().
                df.to_csv(CSV_PATH, index=False)

        row = df.loc[idx]
        try:
            game_id = int(row["game_id"])
            season  = int(row["season"])
            home_sp_id, away_sp_id, _, _ = get_boxscore_pitchers(game_id)
            if not home_sp_id or not away_sp_id:
                skipped += 1
                continue
            home_p = get_pitcher_stats(home_sp_id, season)
            away_p = get_pitcher_stats(away_sp_id, season)
            if not home_p or not away_p:
                skipped += 1
                continue
            df.at[idx, "home_fip"] = home_p["fip"]
            df.at[idx, "away_fip"] = away_p["fip"]
            df.at[idx, "fip_diff"] = away_p["fip"] - home_p["fip"]
            ok += 1
        except Exception:
            skipped += 1
            continue

    print(f"\nBackfill loop done. ok={ok}, skipped={skipped}")
    finalise(df, ok=ok, skipped=skipped)


def finalise(df, ok=None, skipped=None):
    """Drop unfilled rows + old era/whip columns, then save."""
    before = len(df)
    df = df.dropna(subset=["home_fip", "away_fip"])
    dropped = before - len(df)

    for col in OLD_COLS_TO_DROP:
        if col in df.columns:
            df = df.drop(columns=[col])

    df.to_csv(CSV_PATH, index=False)

    print("\n✅ Backfill complete!")
    if ok is not None:
        print(f"   Filled this run: {ok}")
    if skipped is not None:
        print(f"   Skipped (no boxscore / no pitcher data): {skipped}")
    print(f"   Dropped rows missing FIP: {dropped}")
    print(f"   Final training rows: {len(df)}")
    print(f"   Backup preserved at: {BACKUP_PATH}")
    print(f"   Old era/whip columns removed.")


if __name__ == "__main__":
    main()