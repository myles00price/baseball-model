"""hr_model.py — daily home-run probability board (display only, no bets).

For every hitter on today's slate, estimates the probability of hitting at
least one home run today and writes the top of the list to
hr_watch_{date}.json for the public board's LONG BALL WATCH section.

Method (deliberately simple, no trained model — every input is public and
the math is inspectable):

  p_PA   = shrunk batter HR/PA  ×  opposing-starter factor  ×  park factor
  p_game = 1 - (1 - p_PA) ^ expected_PA

- Batter HR/PA is shrunk toward the 2026 league rate with a 200-PA prior
  (empirical Bayes) so hot small samples can't top the list.
- Opposing starter factor is his shrunk HR-allowed/BF vs league (300-BF
  prior, capped 0.75–1.35), blended 55/45 toward neutral because the
  starter only faces a bit over half of a lineup's plate appearances.
- Park factor is a static HR park-factor table applied at half strength —
  the table is an approximation, so it is deliberately damped.
- Expected PA is the batter's season PA per game, clamped to 3.2–4.7.

No platoon adjustment, no weather, no lineup confirmation in v1 — noted
in the board copy. Roster comes from each team's active roster, so an
off-day for a star is not knowable pre-lineup; that caveat ships with it.

Usage:
    python hr_model.py               # today's slate (UTC-7 board day)
    python hr_model.py 2026-08-12    # a specific date
"""

import json
import sys
from datetime import datetime, timedelta, timezone

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

API = "https://statsapi.mlb.com/api/v1"
SEASON = 2026
BATTER_PRIOR_PA = 200      # shrinkage prior for batter HR/PA
PITCHER_PRIOR_BF = 300     # shrinkage prior for pitcher HR/BF
STARTER_PA_SHARE = 0.55    # share of lineup PAs the starter faces
PARK_DAMP = 0.5            # apply park factors at half strength
TOP_N = 15
MIN_PA = 100               # eligibility floor for the public list

# Approximate 3-year HR park factors (100 = neutral), keyed by home team.
# Deliberately damped by PARK_DAMP above because these are estimates.
PARK_HR = {
    "Cincinnati Reds": 128, "Los Angeles Dodgers": 120, "New York Yankees": 117,
    "Philadelphia Phillies": 113, "Milwaukee Brewers": 111, "Colorado Rockies": 110,
    "Chicago White Sox": 110, "Houston Astros": 108, "Baltimore Orioles": 106,
    "Atlanta Braves": 105, "Los Angeles Angels": 104, "Arizona Diamondbacks": 103,
    "Texas Rangers": 102, "Toronto Blue Jays": 102, "Chicago Cubs": 101,
    "Washington Nationals": 101, "Athletics": 100, "Seattle Mariners": 99,
    "Minnesota Twins": 99, "Cleveland Guardians": 97, "Tampa Bay Rays": 96,
    "San Diego Padres": 96, "New York Mets": 95, "Boston Red Sox": 92,
    "Detroit Tigers": 91, "St. Louis Cardinals": 89, "Pittsburgh Pirates": 88,
    "Kansas City Royals": 86, "Miami Marlins": 84, "San Francisco Giants": 82,
}


def board_date() -> str:
    return datetime.now(timezone(timedelta(hours=-7))).strftime("%Y-%m-%d")


def get(session, path, **params):
    r = session.get(f"{API}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_schedule(session, date):
    j = get(session, "/schedule", sportId=1, date=date, gameTypes="R",
            hydrate="probablePitcher")
    games = []
    for day in j.get("dates", []):
        for g in day.get("games", []):
            games.append({
                "pk": g["gamePk"],
                "away_id": g["teams"]["away"]["team"]["id"],
                "away": g["teams"]["away"]["team"]["name"],
                "home_id": g["teams"]["home"]["team"]["id"],
                "home": g["teams"]["home"]["team"]["name"],
                "away_sp": g["teams"]["away"].get("probablePitcher"),
                "home_sp": g["teams"]["home"].get("probablePitcher"),
            })
    return games


def league_hr_rate(session):
    j = get(session, "/teams/stats", season=SEASON, group="hitting",
            stats="season", sportId=1)
    hr = pa = 0
    for split in j.get("stats", [{}])[0].get("splits", []):
        st = split.get("stat", {})
        hr += int(st.get("homeRuns", 0))
        pa += int(st.get("plateAppearances", 0))
    return hr / pa if pa else 0.031, hr, pa


def fetch_team_hitters(session, team_id):
    """Active-roster position players with 2026 season hitting stats."""
    j = get(session, f"/teams/{team_id}/roster", rosterType="active",
            hydrate=f"person(stats(group=[hitting],type=[season],season={SEASON}))")
    out = []
    for entry in j.get("roster", []):
        p = entry.get("person", {})
        if entry.get("position", {}).get("abbreviation") == "P":
            continue
        st = {}
        for s in p.get("stats", []):
            if s.get("group", {}).get("displayName") == "hitting":
                sp = s.get("splits", [])
                if sp:
                    st = sp[0].get("stat", {})
        pa = int(st.get("plateAppearances", 0))
        if pa < MIN_PA:
            continue
        out.append({
            "id": p["id"], "name": p.get("fullName", ""),
            "pa": pa, "hr": int(st.get("homeRuns", 0)),
            "g": int(st.get("gamesPlayed", 0)) or 1,
        })
    return out


def fetch_pitcher_rates(session, pitcher_ids, league_rate):
    """Shrunk HR-allowed/BF multiplier vs league, per probable starter."""
    mult = {}
    ids = [str(i) for i in pitcher_ids if i]
    for i in range(0, len(ids), 40):
        chunk = ",".join(ids[i:i + 40])
        j = get(session, "/people", personIds=chunk,
                hydrate=f"stats(group=[pitching],type=[season],season={SEASON})")
        for p in j.get("people", []):
            hr = bf = 0
            for s in p.get("stats", []):
                if s.get("group", {}).get("displayName") == "pitching":
                    sp = s.get("splits", [])
                    if sp:
                        st = sp[0].get("stat", {})
                        hr = int(st.get("homeRuns", 0))
                        bf = int(st.get("battersFaced", 0))
            shrunk = (hr + PITCHER_PRIOR_BF * league_rate) / (bf + PITCHER_PRIOR_BF)
            m = max(0.75, min(1.35, shrunk / league_rate))
            mult[p["id"]] = m
    return mult


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else board_date()
    session = requests.Session()

    games = fetch_schedule(session, date)
    if not games:
        print(f"No games on {date}; nothing written.")
        return

    lg_rate, lg_hr, lg_pa = league_hr_rate(session)
    print(f"League HR/PA {SEASON}: {lg_rate:.4f} ({lg_hr} HR / {lg_pa} PA)")

    sp_ids = [(g["away_sp"] or {}).get("id") for g in games] + \
             [(g["home_sp"] or {}).get("id") for g in games]
    sp_mult = fetch_pitcher_rates(session, sp_ids, lg_rate)

    roster_cache = {}

    def hitters(team_id):
        if team_id not in roster_cache:
            roster_cache[team_id] = fetch_team_hitters(session, team_id)
        return roster_cache[team_id]

    players = []
    for g in games:
        park = PARK_HR.get(g["home"], 100)
        park_mult = 1 + (park - 100) / 100 * PARK_DAMP
        for side, opp_side in (("away", "home"), ("home", "away")):
            opp_sp = g[f"{opp_side}_sp"] or {}
            raw = sp_mult.get(opp_sp.get("id"), 1.0)
            pitch_mult = STARTER_PA_SHARE * raw + (1 - STARTER_PA_SHARE) * 1.0
            for b in hitters(g[f"{side}_id"]):
                bat_rate = (b["hr"] + BATTER_PRIOR_PA * lg_rate) / (b["pa"] + BATTER_PRIOR_PA)
                p_pa = bat_rate * pitch_mult * park_mult
                exp_pa = max(3.2, min(4.7, b["pa"] / b["g"]))
                p_game = 1 - (1 - p_pa) ** exp_pa
                players.append({
                    "id": b["id"], "name": b["name"], "team": g[side],
                    "opp": g[opp_side], "home": side == "home",
                    "opp_sp": opp_sp.get("fullName", "TBD"),
                    "opp_sp_id": opp_sp.get("id"),
                    "p": round(p_game * 100, 1),
                    "hr": b["hr"], "pa": b["pa"],
                    "f_bat": round(bat_rate / lg_rate, 2),
                    "f_pit": round(pitch_mult, 2),
                    "f_park": round(park_mult, 2),
                    "exp_pa": round(exp_pa, 1),
                })

    # Doubleheaders list a team twice — keep each hitter's best game only.
    best = {}
    for p in players:
        if p["id"] not in best or p["p"] > best[p["id"]]["p"]:
            best[p["id"]] = p
    players = sorted(best.values(), key=lambda x: -x["p"])
    out = {
        "date": date,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "league_hr_pa": round(lg_rate, 4),
        "players": players[:TOP_N],
    }
    fn = f"hr_watch_{date}.json"
    with open(fn, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\nTop {TOP_N} HR probabilities for {date}:")
    for p in out["players"]:
        print(f"  {p['p']:5.1f}%  {p['name']:<24} {p['team']} vs {p['opp_sp']}"
              f"  ({p['hr']} HR / {p['pa']} PA)")
    print(f"\nSaved {fn}")


if __name__ == "__main__":
    main()
