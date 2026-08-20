"""
bullpen_rankings.py — BULLPEN RANKINGS board section (IDEA BOX request,
2026-08-19: "Bullpen Rankings!!"). Display only — the model itself uses no
bullpen input (four separate bullpen features tested and rejected walk-
forward); this is context for readers, not a betting signal.

Per team:
  quality : 7-day bullpen ERA, season save/blown-save record and the
            composite bullpen score (bullpen_stats.py, already computed
            for the game cards)
  fatigue : from pen_usage.csv (the nightly pitch-by-pitch usage archive) -
            reliever pitches thrown over the last 2 days, tired arms
            (20+ pitches yesterday or back-to-back outings), and how many
            of the team's six most-used relievers are fully rested

Writes bullpen_rankings.json, ranked by bullpen score.
Run:  py -3.11 .\bullpen_rankings.py   (hooked into morning_report)
"""

import csv
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from bullpen_stats import get_bullpen_stats

SEASON = 2026
OUT = "bullpen_rankings.json"


def usage_metrics(today):
    """(team) -> {pitches2, tired, fresh_top} from pen_usage.csv."""
    usage = defaultdict(dict)          # (team, date) -> {pid: pitches}
    apps = defaultdict(int)            # (team, pid) -> relief appearances
    try:
        rows = list(csv.DictReader(open("pen_usage.csv", encoding="utf-8-sig")))
    except OSError:
        return {}
    for r in rows:
        if r["started"] == "1":
            continue
        try:
            p = float(r["pitches"] or 0)
        except ValueError:
            p = 0.0
        usage[(r["team"], r["date"])][r["pid"]] = usage[(r["team"], r["date"])].get(r["pid"], 0) + p
        apps[(r["team"], r["pid"])] += 1
    teams = {t for t, _ in usage}
    d1 = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    d2 = (date.fromisoformat(today) - timedelta(days=2)).isoformat()
    out = {}
    for t in teams:
        arms = sorted(((n, pid) for (tm, pid), n in apps.items() if tm == t), reverse=True)
        top6 = {pid for _, pid in arms[:6]}
        u1, u2 = usage.get((t, d1), {}), usage.get((t, d2), {})
        out[t] = {
            "pitches2": int(sum(u1.values()) + sum(u2.values())),
            "tired": sum(1 for pid in set(u1) | set(u2)
                         if u1.get(pid, 0) >= 20 or (pid in u1 and pid in u2)),
            "fresh_top": sum(1 for pid in top6 if pid not in u1 and pid not in u2),
        }
    return out


def main():
    today = datetime.now(timezone(timedelta(hours=-7))).strftime("%Y-%m-%d")
    bp = get_bullpen_stats(SEASON)
    um = usage_metrics(today)
    rows = []
    for team, s in bp.items():
        u = um.get(team, {})
        rows.append({
            "team": team, "score": s.get("bullpen_score"),
            "era7": s.get("era_recent"), "whip7": s.get("whip_recent"),
            "sv": s.get("saves"), "bsv": s.get("blown_saves"),
            "pitches2": u.get("pitches2"), "tired": u.get("tired"),
            "fresh_top": u.get("fresh_top"),
        })
    # bullpen_score: lower = better (era/whip normalized); rank ascending
    rows.sort(key=lambda r: (r["score"] is None, r["score"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"updated": today, "teams": rows}, f, indent=1)
    print(f"{OUT}: {len(rows)} teams ranked (1={rows[0]['team']}, 30={rows[-1]['team']})")


if __name__ == "__main__":
    main()
