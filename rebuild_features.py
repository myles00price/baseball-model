"""
rebuild_features.py — ONE-TIME repair.

Undoes the era/whip column drop. Restores training_data.csv from the
pre-FIP backup (which still has era/whip), then re-adds home_fip /
away_fip / fip_diff WITHOUT dropping anything. End result: a CSV with
era, whip, AND fip — the superset the new weekly_retrain.py expects.

Behaviour:
  • Restores training_data.csv from training_data_pre_fip_backup.csv
  • Re-adds FIP columns (resumable, checkpoints every 25 rows)
  • Keeps era/whip/era_diff intact
  • Makes its own safety copy before overwriting the current file

Run:  py -3.11 .\rebuild_features.py

The ~30 recent games that were added during the FIP experiment and
aren't in the backup will be re-pulled automatically on the next
weekly_retrain run (build_new_rows now writes era/whip/fip), so
nothing is permanently lost.
"""

import os
import shutil
import numpy as np
import pandas as pd

from weekly_retrain import get_boxscore_pitchers, get_pitcher_stats

CSV_PATH    = "training_data.csv"
BACKUP_PATH = "training_data_pre_fip_backup.csv"
SAFETY_COPY = "training_data_pre_rebuild.csv"

CHECKPOINT_EVERY = 25


def main():
    if not os.path.exists(BACKUP_PATH):
        print(f"❌ {BACKUP_PATH} not found — cannot restore era/whip. Aborting.")
        return

    # Keep a copy of whatever is currently on disk, just in case.
    if os.path.exists(CSV_PATH) and not os.path.exists(SAFETY_COPY):
        shutil.copy(CSV_PATH, SAFETY_COPY)
        print(f"Current file copied → {SAFETY_COPY}")

    # Restore the era/whip version from backup.
    shutil.copy(BACKUP_PATH, CSV_PATH)
    df = pd.read_csv(CSV_PATH)
    print(f"Restored {len(df)} rows from {BACKUP_PATH} (era/whip intact)")

    # Confirm era/whip are actually present.
    for col in ["home_era", "home_whip", "away_era", "away_whip"]:
        if col not in df.columns:
            print(f"❌ backup is missing {col} — unexpected. Aborting.")
            return

    # Add FIP columns.
    if "home_fip" not in df.columns:
        df["home_fip"] = np.nan
        df["away_fip"] = np.nan
        df["fip_diff"] = np.nan

    todo_idx = df[df["home_fip"].isna()].index.tolist()
    print(f"Rows needing FIP: {len(todo_idx)} / {len(df)}")

    ok = 0
    skipped = 0

    for n, idx in enumerate(todo_idx):
        if n % CHECKPOINT_EVERY == 0:
            print(f"  {n}/{len(todo_idx)}  (ok={ok}, skipped={skipped})")
            if n > 0:
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

    print(f"\nFIP fill done. ok={ok}, skipped={skipped}")

    # Drop any rows we couldn't fill FIP for (keeps the feature matrix clean).
    before = len(df)
    df = df.dropna(subset=["home_fip", "away_fip"])
    dropped = before - len(df)

    df.to_csv(CSV_PATH, index=False)

    print("\n✅ Rebuild complete!")
    print(f"   Rows with FIP filled: {ok}")
    print(f"   Skipped (no data): {skipped}")
    print(f"   Dropped rows missing FIP: {dropped}")
    print(f"   Final training rows: {len(df)}")
    print(f"   Columns now include era, whip, AND fip.")
    print(f"   Pre-rebuild copy preserved at: {SAFETY_COPY}")


if __name__ == "__main__":
    main()