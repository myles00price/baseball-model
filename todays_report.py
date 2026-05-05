from master import run_model
from datetime import datetime, timedelta, timezone

if __name__ == '__main__':
    las_vegas_offset = timezone(timedelta(hours=-7))
    today = datetime.now(las_vegas_offset)
    # Overwrite today's picks with platoon model predictions
    run_model(today, save_csv=True)
    print("\nToday's picks saved — run check_results.py tomorrow to grade!")