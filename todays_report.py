import sys
from datetime import datetime, timedelta, timezone

# Task Scheduler consoles use cp1252, which can't encode emoji glyphs
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from master_v2 import run_model

if __name__ == '__main__':
    las_vegas_offset = timezone(timedelta(hours=-7))
    today = datetime.now(las_vegas_offset)
    # Overwrite today's picks with V2 predictions at current odds
    run_model(today, save_csv=True)
    print("\nToday's picks saved - run check_results.py tomorrow to grade!")
