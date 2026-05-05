import csv
import os
from datetime import datetime, timedelta, timezone

def save_picks_to_csv(picks):
    las_vegas_offset = timezone(timedelta(hours=-7))
    today = datetime.now(las_vegas_offset).strftime("%Y-%m-%d")
    filename = f"picks_{today}.csv"
    filepath = os.path.join(os.path.dirname(__file__), filename)

    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Date", "Away", "Home",
            "Model Away%", "Model Home%",
            "DK Away", "DK Home",
            "MGM Away", "MGM Home",
            "DK Edge Away", "MGM Edge Away",
            "DK Edge Home", "MGM Edge Home",
            "Away SP", "Home SP",
            "Flag"
        ])
        for pick in picks:
            writer.writerow(pick)

    print(f"\n✅ Picks saved to {filename}")
    return filename