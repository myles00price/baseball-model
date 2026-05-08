# auto_lineup_push.py
import subprocess
import requests
from datetime import datetime, timedelta, timezone

def count_confirmed_lineups(date_str):
    try:
        data = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": date_str, "hydrate": "lineups"},
            timeout=10
        ).json()
        confirmed = 0
        for d in data.get("dates", []):
            for g in d.get("games", []):
                lineups = g.get("lineups", {})
                if lineups.get("homePlayers") or lineups.get("awayPlayers"):
                    confirmed += 1
        return confirmed
    except:
        return 0

def read_last_confirmed():
    try:
        with open("last_confirmed.txt") as f:
            return int(f.read().strip())
    except:
        return 0

def write_last_confirmed(n):
    with open("last_confirmed.txt", "w") as f:
        f.write(str(n))

def git_push():
    subprocess.run(
        'cd C:\\Users\\Poons\\baseball-model && git add . && git commit -m "lineup update" && git push',
        shell=True
    )

if __name__ == "__main__":
    lv = timezone(timedelta(hours=-7))
    today = datetime.now(lv).strftime("%Y-%m-%d")
    
    current = count_confirmed_lineups(today)
    last = read_last_confirmed()
    
    if current > last:
        print(f"New lineups confirmed: {current} (was {last}) — running todays_report and pushing")
        subprocess.run(["py", "-3.11", "C:\\Users\\Poons\\baseball-model\\todays_report.py"])
        git_push()
        write_last_confirmed(current)
    else:
        print(f"No new lineups ({current} confirmed) — skipping push")