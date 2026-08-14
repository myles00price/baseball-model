"""hr_bt_weather_pull.py — game-time weather for every backtest game.

One fields-filtered live-feed call per game_pk in hr_bt_games.csv (the
feed returns full gameData for completed games). Writes
hr_bt_weather.csv: game_pk, condition, temp, wind. Resume-safe.

Run (any interpreter with requests + pandas):
    C:\\Users\\Poons\\Model\\.venv\\Scripts\\python.exe hr_bt_weather_pull.py
"""

import os
import sys
import time

import pandas as pd
import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

FN = "hr_bt_weather.csv"


def main():
    games = pd.read_csv("hr_bt_games.csv").drop_duplicates("game_pk")
    have = set()
    if os.path.exists(FN):
        have = set(pd.read_csv(FN, usecols=["game_pk"])["game_pk"])
    todo = [pk for pk in games["game_pk"] if pk not in have]
    print(f"{len(todo)} games to fetch")
    session = requests.Session()
    rows = []
    for i, pk in enumerate(todo):
        try:
            r = session.get(
                f"https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live",
                params={"fields": "gameData,weather,condition,temp,wind"},
                timeout=20)
            w = r.json().get("gameData", {}).get("weather", {}) or {}
        except Exception:
            w = {}
        rows.append({"game_pk": pk, "condition": w.get("condition", ""),
                     "temp": w.get("temp", ""), "wind": w.get("wind", "")})
        if len(rows) >= 100:
            pd.DataFrame(rows).to_csv(FN, mode="a", index=False,
                                      header=not os.path.exists(FN))
            rows = []
            print(f"{i+1}/{len(todo)}", flush=True)
        time.sleep(0.08)
    if rows:
        pd.DataFrame(rows).to_csv(FN, mode="a", index=False,
                                  header=not os.path.exists(FN))
    print("done")


if __name__ == "__main__":
    main()
