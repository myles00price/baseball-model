"""hr_model.py — daily home-run probability board (display only, no bets).

For every hitter on today's slate, estimates the probability of hitting at
least one home run today and writes the top of the list to
hr_watch_{date}.json for the public board's LONG BALL WATCH section.

Method (deliberately simple, no trained model — every input is public and
the math is inspectable):

  p_PA   = shrunk batter HR/PA × starter factor × park
  p_game = 1 - (1 - p_PA) ^ expected_PA

2026-08-13 backtests (hr_backtest.py / hr_backtest2.py, 21,490
walk-forward batter-games, May-Jun fit / Jul+ holdout): the batter's own
rate does most of the work; starter and park each add a small real
sliver. EVERYTHING else failed the holdout at every tested strength and
is EXCLUDED from the published probability but still computed, shown as
context, and logged nightly for the training archive to re-litigate:
  - platoon vs-hand splits (hurt both windows, drove tail overconfidence)
  - arsenal matchup (wash at quarter strength, hurts at full)
  - wind and temperature (helped in fit, hurt in holdout — likely
    correlated with seasonal environment shifts the base rate absorbs)
Tail runs ~2.5pts hot at p>=16%; under watch nightly.

- Batter HR/PA is shrunk toward the 2026 league rate with a 300-PA prior
  (empirical Bayes) so hot small samples can't top the list.
- Platoon (LOGGED ONLY, not in the number): the batter's HR rate vs the
  opposing starter's hand, shrunk 300-PA, capped 0.8–1.2. Still computed
  for every eligible hitter and written to the training log — the trained
  model gets to re-litigate it with more data — but the backtest showed
  it degrades out-of-sample accuracy, so it no longer touches p.
- Opposing starter factor is his shrunk HR-allowed/BF vs league (300-BF
  prior, capped 0.75–1.35), blended 55/45 toward neutral because the
  starter only faces a bit over half of a lineup's plate appearances.
- Park factor is a static HR park-factor table applied at half strength —
  the table is an approximation, so it is deliberately damped.
- Arsenal: batter's per-pitch-type power (Statcast ISO by pitch type)
  weighted by the opposing starter's actual usage mix, relative to the
  batter's overall ISO. Shrunk per type (50-PA prior), capped 0.85–1.15.
  Profiles come from hr_profiles.json, built by hr_profiles_build.py
  under the Model repo's venv (pybaseball lives there, NEVER in the
  shared interpreter); auto-rebuilt when older than 3 days. Missing
  profile -> 1.0.
- Wind: if the Stats API game feed reports wind blowing Out/In at an
  open-air park, ±2% per mph (capped ±25%). Domes and closed roofs are
  neutral. Morning runs often predate the weather feed — then it's
  neutral and the display says so.
- Temp: warm air carries — +0.5% per °F above 72 (capped ±12%), open-air
  only, neutral when the feed has no reading yet.
- Expected PA is the batter's season PA per game, clamped to 3.2–4.7 —
  until lineups post; see refresh mode below.

Refresh mode (--refresh, called by auto_lineup_push on every lineup
check): reuses the morning log's factors, re-reads lineups + weather,
drops hitters not in a posted lineup (the DNP fix: 17% of logged hitters
never played on night one), sets expected PA from the confirmed batting
slot, and rewrites hr_watch_{date}.json only — the morning training log
is never touched, it is the frozen pre-lineup dataset. Book prices are
refetched at most every 3 hours (quota etiquette).

Book prices: "to hit a HR" (Over 0.5) per game from the Odds API — DK /
MGM / CZR when posted (2 credits per game). Caesars lists it under
batter_home_runs; DK and MGM file the same 0.5 line under
batter_home_runs_alternate, so both markets are requested and the main
key wins if a book ever posts both. Shown next to the model's fair
American odds. STILL DISPLAY ONLY: no bet flags, no texts, no ledger.

Training archive: every run also writes the FULL slate (every eligible
hitter, all factors, model probability, book prices) to hr_log_{date}.csv.
hr_grade.py joins those rows to boxscore outcomes nightly and appends to
hr_training_data.csv — the dataset a real trained HR model will learn
from once the sample is big enough. Good data outlives the hypothesis.

Usage:
    python hr_model.py               # today's slate (UTC-7 board day)
    python hr_model.py 2026-08-12    # a specific date
"""

import csv
import json
import os
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

API = "https://statsapi.mlb.com/api/v1"
ODDS_BASE = "https://api.the-odds-api.com/v4/sports/baseball_mlb"
ODDS_BOOKS = "draftkings,betmgm,williamhill_us"
SEASON = 2026
BATTER_PRIOR_PA = 300      # shrinkage prior for batter HR/PA
                           # 2026-08-15: 200 -> 300 (owner call). Miss audit
                           # showed elite tier ~5pts hot; prior sweep: 300
                           # wins Jul+ holdout (99.557 vs 99.623) and halves
                           # the elite gap, but loses the May-Jun fit window.
                           # Nightly archive adjudicates.
PLATOON_PRIOR_PA = 300     # shrinkage prior for vs-hand split rate (HR
                           # splits are noisy; stiff prior keeps this honest)
PITCHER_PRIOR_BF = 300     # shrinkage prior for pitcher HR/BF
STARTER_PA_SHARE = 0.55    # share of lineup PAs the starter faces
PARK_DAMP = 0.5            # apply park factors at half strength
WIND_PER_MPH = 0.02        # HR rate change per mph of out/in wind
WIND_CAP = 0.25            # max wind adjustment either way
TEMP_PER_F = 0.005         # HR rate change per degF from baseline
TEMP_BASE_F = 72
TEMP_CAP = 0.12            # max temperature adjustment either way
ARSENAL_PRIOR_PA = 50      # per-pitch-type shrinkage prior (ISO)
ARSENAL_LO, ARSENAL_HI = 0.85, 1.15
TOP_N = 15
MIN_PA = 100               # eligibility floor for the public list

VENV_PY = r"C:\Users\Poons\Model\.venv\Scripts\python.exe"  # pybaseball lives here
PROFILES_FN = "hr_profiles.json"
PROFILES_MAX_AGE_DAYS = 3
ODDS_STAMP_FN = "hr_odds_stamp.txt"
ODDS_REFRESH_HOURS = 3     # refresh mode refetches prices at most this often

# Expected PA by confirmed batting-order slot (1-9), 9-inning average.
SLOT_PA = [4.65, 4.53, 4.42, 4.31, 4.20, 4.09, 3.98, 3.87, 3.77]

# Columns of hr_log_{date}.csv, in order. hr_grade.py appends outcome
# columns to these when building hr_training_data.csv — change both
# together (hr_grade migrates the training file's header on change).
# hr_pa is the final per-PA probability, stored so refresh mode can
# re-derive p under new weather/lineup without refetching factors.
LOG_COLS = ["date", "pk", "player_id", "name", "team", "opp", "home",
            "opp_sp", "opp_sp_id", "sp_hand", "season_hr", "season_pa",
            "exp_pa", "f_bat", "f_platoon", "f_arsenal", "f_pit", "f_park",
            "f_wind", "f_temp", "wind", "hr_pa", "p",
            "odds_dk", "odds_mgm", "odds_czr", "fair"]

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


def norm_name(n):
    """Accent-strip + lowercase + drop suffixes, for odds<->statsapi matching."""
    n = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode()
    n = n.lower().replace(".", "").replace("'", "")
    for suf in (" jr", " sr", " ii", " iii", " iv"):
        if n.endswith(suf):
            n = n[: -len(suf)]
    return " ".join(n.split())


def american_from_prob(p):
    """Model probability (0-1) -> fair American odds string."""
    if p <= 0:
        return "—"
    if p >= 0.5:
        return f"-{round(p / (1 - p) * 100)}"
    return f"+{round((1 - p) / p * 100)}"


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


def fetch_pitchers(session, pitcher_ids, league_rate):
    """Per probable starter: shrunk HR-allowed/BF multiplier + throwing hand."""
    info = {}
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
            info[p["id"]] = {
                "mult": max(0.75, min(1.35, shrunk / league_rate)),
                "hand": p.get("pitchHand", {}).get("code"),
            }
    return info


def platoon_mult(session, batter_id, base_rate, sp_hand):
    """Batter's vs-hand HR rate relative to his own overall rate, shrunk."""
    if sp_hand not in ("L", "R"):
        return 1.0
    sit = "vl" if sp_hand == "L" else "vr"
    try:
        j = get(session, f"/people/{batter_id}/stats", stats="statSplits",
                group="hitting", season=SEASON, sitCodes=sit)
        hr = pa = 0
        for s in j.get("stats", []):
            for sp in s.get("splits", []):
                st = sp.get("stat", {})
                pa = int(st.get("plateAppearances", 0))
                hr = int(st.get("homeRuns", 0))
        if pa == 0:
            return 1.0
        split_rate = (hr + PLATOON_PRIOR_PA * base_rate) / (pa + PLATOON_PRIOR_PA)
        return max(0.8, min(1.2, split_rate / base_rate))
    except Exception:
        return 1.0


def fetch_weather(session, game_pk):
    """(wind_mult, temp_mult, label) from the game feed. Neutral if unknown."""
    try:
        r = session.get(f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live",
                        params={"fields": "gameData,weather,condition,temp,wind"},
                        timeout=30)
        w = r.json().get("gameData", {}).get("weather", {}) or {}
    except Exception:
        return 1.0, 1.0, ""
    cond = (w.get("condition") or "").lower()
    wind = w.get("wind") or ""
    if "dome" in cond or "roof closed" in cond:
        return 1.0, 1.0, "ROOF"
    temp_mult = 1.0
    labels = []
    try:
        t = float(w.get("temp"))
        adj = max(-TEMP_CAP, min(TEMP_CAP, (t - TEMP_BASE_F) * TEMP_PER_F))
        temp_mult = 1.0 + adj
        if adj >= 0.05:
            labels.append(f"HOT {round(t)}F")
        elif adj <= -0.05:
            labels.append(f"COLD {round(t)}F")
    except (TypeError, ValueError):
        pass
    wind_mult = 1.0
    try:
        mph = float(wind.split("mph")[0].strip())
        wl = wind.lower()
        sign = 1 if "out to" in wl else -1 if "in from" in wl else 0
        if sign:
            adj = max(-WIND_CAP, min(WIND_CAP, sign * mph * WIND_PER_MPH))
            wind_mult = 1.0 + adj
            labels.append(f"WIND {round(mph)} {'OUT' if sign > 0 else 'IN'}")
    except (ValueError, IndexError):
        pass
    return wind_mult, temp_mult, " · ".join(labels)


def load_profiles():
    """Arsenal profiles, auto-rebuilt via the Model venv when stale."""
    import subprocess
    stale = True
    if os.path.exists(PROFILES_FN):
        age = time.time() - os.path.getmtime(PROFILES_FN)
        stale = age > PROFILES_MAX_AGE_DAYS * 86400
    if stale:
        try:
            print("Rebuilding arsenal profiles (pybaseball, Model venv)…")
            subprocess.run([VENV_PY, "hr_profiles_build.py"], timeout=900)
        except Exception as e:
            print(f"WARNING: profile rebuild failed ({e}) - using cache if any")
    try:
        with open(PROFILES_FN) as f:
            return json.load(f)
    except Exception:
        print("WARNING: no arsenal profiles - arsenal factor neutral")
        return None


def arsenal_mult(profiles, batter_id, sp_id):
    """Batter's expected ISO vs this starter's mix, over his own ISO."""
    if not profiles or not sp_id:
        return 1.0
    bat = profiles["batters"].get(str(batter_id))
    pit = profiles["pitchers"].get(str(sp_id))
    if not bat or not pit or bat["iso"] < 0.05:
        return 1.0
    base = bat["iso"]
    expected = 0.0
    share = 0.0
    for t, u in pit["usage"].items():
        bt = bat["types"].get(t)
        iso_t = base if not bt else \
            (bt["pa"] * bt["iso"] + ARSENAL_PRIOR_PA * base) / (bt["pa"] + ARSENAL_PRIOR_PA)
        expected += u * iso_t
        share += u
    if share < 0.5:
        return 1.0
    return max(ARSENAL_LO, min(ARSENAL_HI, (expected / share) / base))


def fetch_lineups(session, date):
    """{game_pk: {player_id: batting_slot 1-9}} for posted lineups."""
    out = {}
    try:
        j = get(session, "/schedule", sportId=1, date=date, hydrate="lineups")
    except Exception:
        return out
    for day in j.get("dates", []):
        for g in day.get("games", []):
            lu = g.get("lineups") or {}
            slots = {}
            for side in ("awayPlayers", "homePlayers"):
                for i, p in enumerate(lu.get(side) or []):
                    if p.get("id"):
                        slots[p["id"]] = min(i + 1, 9)
            if slots:
                out[g["gamePk"]] = slots
    return out


def load_log_odds(log_fn):
    """{player_id: {dk/mgm/czr: price}} from an existing day log, if any."""
    out = {}
    if not os.path.exists(log_fn):
        return out
    try:
        with open(log_fn, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                o = {bk: int(float(v)) for bk in ("dk", "mgm", "czr")
                     if (v := r.get(f"odds_{bk}"))}
                if o:
                    out[int(r["player_id"])] = o
    except Exception:
        pass
    return out


def fetch_hr_odds(date, games):
    """{game_pk: {norm_player_name: {dk/mgm/czr: price}}} from the Odds API.

    1 credit per game. Any failure degrades to no odds, never a crash."""
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("WARNING: ODDS_API_KEY not set - no book odds")
        return {}
    book_col = {"draftkings": "dk", "betmgm": "mgm", "williamhill_us": "czr"}
    out = {}
    try:
        ev = requests.get(f"{ODDS_BASE}/events", params={"apiKey": key}, timeout=20)
        events = ev.json() if ev.ok else []
    except Exception as e:
        print(f"WARNING: odds events unavailable ({e}) - no book odds")
        return {}

    def team_key(n):
        return norm_name(n).split()[-1] if n else ""

    ev_by_key = {}
    for e in events:
        # pin events to the requested board day (UTC-7) — the events feed
        # only carries upcoming games, so without this a rerun for a past
        # date would silently match the NEXT meeting of the same teams
        try:
            cm = datetime.strptime(e["commence_time"], "%Y-%m-%dT%H:%M:%SZ")
            ev_date = (cm.replace(tzinfo=timezone.utc)
                       .astimezone(timezone(timedelta(hours=-7))).strftime("%Y-%m-%d"))
        except (KeyError, ValueError):
            ev_date = date
        if ev_date != date:
            continue
        ev_by_key.setdefault((team_key(e.get("away_team")), team_key(e.get("home_team"))), e["id"])
    remaining = None
    for g in games:
        eid = ev_by_key.get((team_key(g["away"]), team_key(g["home"])))
        if not eid:
            continue
        try:
            r = requests.get(
                f"{ODDS_BASE}/events/{eid}/odds",
                params={"apiKey": key,
                        "markets": "batter_home_runs,batter_home_runs_alternate",
                        "oddsFormat": "american", "bookmakers": ODDS_BOOKS},
                timeout=20)
            remaining = r.headers.get("x-requests-remaining", remaining)
            j = r.json() if r.ok else {}
        except Exception:
            continue
        prices = {}
        for bk in j.get("bookmakers", []):
            col = book_col.get(bk["key"])
            if not col:
                continue
            # main market first so it wins over alternate if both exist
            mks = sorted(bk.get("markets", []),
                         key=lambda m: m["key"] != "batter_home_runs")
            for mk in mks:
                if mk["key"] not in ("batter_home_runs", "batter_home_runs_alternate"):
                    continue
                for o in mk["outcomes"]:
                    if o.get("name") != "Over" or o.get("point") != 0.5:
                        continue
                    prices.setdefault(norm_name(o.get("description")), {}).setdefault(col, o["price"])
        out[g["pk"]] = prices
        time.sleep(0.1)
    print(f"Odds: prices for {sum(len(v) for v in out.values())} hitter-games "
          f"across {len(out)} games (quota remaining {remaining})")
    return out


def main():
    date = (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--")
            else board_date())
    session = requests.Session()

    games = fetch_schedule(session, date)
    if not games:
        print(f"No games on {date}; nothing written.")
        return

    lg_rate, lg_hr, lg_pa = league_hr_rate(session)
    print(f"League HR/PA {SEASON}: {lg_rate:.4f} ({lg_hr} HR / {lg_pa} PA)")

    sp_ids = [(g["away_sp"] or {}).get("id") for g in games] + \
             [(g["home_sp"] or {}).get("id") for g in games]
    sp_info = fetch_pitchers(session, sp_ids, lg_rate)
    profiles = load_profiles()

    weather = {g["pk"]: fetch_weather(session, g["pk"]) for g in games}
    roster_cache = {}

    def hitters(team_id):
        if team_id not in roster_cache:
            roster_cache[team_id] = fetch_team_hitters(session, team_id)
        return roster_cache[team_id]

    players = []
    for g in games:
        park = PARK_HR.get(g["home"], 100)
        park_mult = 1 + (park - 100) / 100 * PARK_DAMP
        wind_mult, temp_mult, wx_label = weather[g["pk"]]
        for side, opp_side in (("away", "home"), ("home", "away")):
            opp_sp = g[f"{opp_side}_sp"] or {}
            sp = sp_info.get(opp_sp.get("id"), {})
            raw = sp.get("mult", 1.0)
            pitch_mult = STARTER_PA_SHARE * raw + (1 - STARTER_PA_SHARE) * 1.0
            for b in hitters(g[f"{side}_id"]):
                bat_rate = (b["hr"] + BATTER_PRIOR_PA * lg_rate) / (b["pa"] + BATTER_PRIOR_PA)
                exp_pa = max(3.2, min(4.7, b["pa"] / b["g"]))
                ars = arsenal_mult(profiles, b["id"], opp_sp.get("id"))
                players.append({
                    "id": b["id"], "name": b["name"], "team": g[side],
                    "opp": g[opp_side], "home": side == "home", "pk": g["pk"],
                    "opp_sp": opp_sp.get("fullName", "TBD"),
                    "opp_sp_id": opp_sp.get("id"), "sp_hand": sp.get("hand"),
                    "hr": b["hr"], "pa": b["pa"],
                    "bat_rate": bat_rate, "exp_pa": round(exp_pa, 1),
                    "f_bat": round(bat_rate / lg_rate, 2),
                    "f_arsenal": round(ars, 2),
                    "f_pit": round(pitch_mult, 2),
                    "f_park": round(park_mult, 2),
                    "f_wind": round(wind_mult, 2),
                    "f_temp": round(temp_mult, 2),
                    "wind": wx_label,
                    # arsenal/wind/temp logged + displayed, NOT multiplied:
                    # all failed the Jul+ holdout (hr_backtest2.py)
                    "_mult": pitch_mult * park_mult,
                })

    # Doubleheaders list a team twice — keep each hitter's best game only.
    best = {}
    for p in players:
        score = p["bat_rate"] * p["_mult"]
        if p["id"] not in best or score > best[p["id"]][0]:
            best[p["id"]] = (score, p)
    players = [p for _, p in best.values()]

    # Platoon factor for EVERY hitter (1 API call each) — the training log
    # needs consistent features, not just a refined top of the list.
    print(f"Platoon splits for {len(players)} hitters…")
    for p in players:
        p["f_platoon"] = round(
            platoon_mult(session, p["id"], p["bat_rate"], p.get("sp_hand")), 2)
        time.sleep(0.1)
    for p in players:
        # f_platoon logged but NOT multiplied in — backtested harmful
        p_pa = p["bat_rate"] * p["_mult"]
        p["hr_pa"] = round(p_pa, 5)
        p["p"] = round((1 - (1 - p_pa) ** p["exp_pa"]) * 100, 1)
    players.sort(key=lambda x: -x["p"])

    # Book prices for everyone we have them for (the odds calls already
    # return the full slate; matching is free). Reruns after first pitch
    # find the events feed mostly empty, so carry over any prices an
    # earlier log of the same date already captured.
    odds = fetch_hr_odds(date, games)
    if odds:
        with open(ODDS_STAMP_FN, "w") as f:
            f.write(str(time.time()))
    prev = load_log_odds(f"hr_log_{date}.csv")
    for p in players:
        fresh = odds.get(p["pk"], {}).get(norm_name(p["name"]), {})
        p["odds"] = fresh or prev.get(p["id"], {})
        p["fair"] = american_from_prob(p["p"] / 100)

    # Full-slate training log — one row per eligible hitter, graded nightly
    # by hr_grade.py into hr_training_data.csv.
    log_fn = f"hr_log_{date}.csv"
    with open(log_fn, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLS)
        w.writeheader()
        for p in players:
            w.writerow({
                "date": date, "pk": p["pk"], "player_id": p["id"],
                "name": p["name"], "team": p["team"], "opp": p["opp"],
                "home": int(p["home"]), "opp_sp": p["opp_sp"],
                "opp_sp_id": p["opp_sp_id"] or "", "sp_hand": p["sp_hand"] or "",
                "season_hr": p["hr"], "season_pa": p["pa"],
                "exp_pa": p["exp_pa"], "f_bat": p["f_bat"],
                "f_platoon": p["f_platoon"], "f_arsenal": p["f_arsenal"],
                "f_pit": p["f_pit"], "f_park": p["f_park"],
                "f_wind": p["f_wind"], "f_temp": p["f_temp"],
                "wind": p["wind"], "hr_pa": p["hr_pa"], "p": p["p"],
                "odds_dk": p["odds"].get("dk", ""),
                "odds_mgm": p["odds"].get("mgm", ""),
                "odds_czr": p["odds"].get("czr", ""),
                "fair": p["fair"],
            })
    print(f"Logged {len(players)} hitter rows to {log_fn}")

    top = [dict(p) for p in players[:TOP_N]]
    for p in top:
        del p["bat_rate"], p["_mult"], p["sp_hand"]

    out = {
        "date": date,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "league_hr_pa": round(lg_rate, 4),
        "players": top,
    }
    fn = f"hr_watch_{date}.json"
    with open(fn, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\nTop {TOP_N} HR probabilities for {date}:")
    for p in top:
        o = p["odds"]
        books = " ".join(f"{k.upper()} {'+' if v > 0 else ''}{v}" for k, v in o.items()) or "no line"
        extras = " ".join(x for x in [p["wind"]] if x)
        print(f"  {p['p']:5.1f}%  {p['name']:<24} {p['team']} vs {p['opp_sp']}"
              f"  fair {p['fair']} | {books} {extras}")
    print(f"\nSaved {fn}")


def refresh():
    """Lineup-aware display refresh — rewrites hr_watch_{date}.json ONLY.

    Reuses the morning log's factors (no roster/platoon/arsenal refetch),
    re-reads lineups + weather, drops hitters missing from a posted
    lineup, sets expected PA from the confirmed batting slot, and
    refetches book prices at most every ODDS_REFRESH_HOURS. The morning
    training log is never modified."""
    date = board_date()
    log_fn = f"hr_log_{date}.csv"
    if not os.path.exists(log_fn):
        print("refresh: no morning log - running full build instead")
        return main()
    with open(log_fn, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return
    session = requests.Session()
    games = fetch_schedule(session, date)
    lineups = fetch_lineups(session, date)
    weather = {g["pk"]: fetch_weather(session, g["pk"]) for g in games}

    odds = None
    try:
        stamp = float(open(ODDS_STAMP_FN).read().strip())
    except Exception:
        stamp = 0.0
    if time.time() - stamp > ODDS_REFRESH_HOURS * 3600:
        odds = fetch_hr_odds(date, games)
        if odds:
            with open(ODDS_STAMP_FN, "w") as f:
                f.write(str(time.time()))

    out_players = []
    dropped = 0
    for r in rows:
        pk = int(r["pk"])
        pid = int(r["player_id"])
        exp_pa = float(r["exp_pa"])
        slots = lineups.get(pk)
        if slots is not None:
            if pid not in slots:
                dropped += 1
                continue
            exp_pa = SLOT_PA[slots[pid] - 1]
        try:
            hr_pa = float(r["hr_pa"])
        except (KeyError, TypeError, ValueError):
            # pre-schema morning log: invert p to recover the per-PA rate
            hr_pa = 1 - (1 - float(r["p"]) / 100) ** (1 / float(r["exp_pa"]))
        # weather is context/display only (failed the holdout) — refresh
        # the label but never the probability
        wind_mult, temp_mult, wx_label = weather.get(pk, (1.0, 1.0, r.get("wind", "")))
        p = round((1 - (1 - hr_pa) ** exp_pa) * 100, 1)
        o = odds.get(pk, {}).get(norm_name(r["name"]), {}) if odds else {}
        if not o:  # fall back to the log's prices (post-first-pitch fetches go empty)
            o = {bk: int(float(v)) for bk in ("dk", "mgm", "czr")
                 if (v := r.get(f"odds_{bk}"))}
        out_players.append({
            "id": pid, "name": r["name"], "team": r["team"], "opp": r["opp"],
            "home": r["home"] == "1", "pk": pk, "opp_sp": r["opp_sp"],
            "opp_sp_id": int(r["opp_sp_id"]) if r.get("opp_sp_id") else None,
            "p": p, "hr": int(r["season_hr"]), "pa": int(r["season_pa"]),
            "exp_pa": round(exp_pa, 1),
            "f_bat": float(r["f_bat"]), "f_platoon": float(r["f_platoon"]),
            "f_arsenal": float(r.get("f_arsenal") or 1),
            "f_pit": float(r["f_pit"]), "f_park": float(r["f_park"]),
            "f_wind": round(wind_mult, 2), "f_temp": round(temp_mult, 2),
            "wind": wx_label, "odds": o, "fair": american_from_prob(p / 100),
        })
    out_players.sort(key=lambda x: -x["p"])
    out = {
        "date": date,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lineups_confirmed": len(lineups),
        "players": out_players[:TOP_N],
    }
    with open(f"hr_watch_{date}.json", "w") as f:
        json.dump(out, f, indent=1)
    print(f"refresh: {len(lineups)} lineups posted, {dropped} hitters dropped, "
          f"top {TOP_N} rewritten")
    for p in out["players"][:5]:
        print(f"  {p['p']:5.1f}%  {p['name']:<24} expPA {p['exp_pa']}")


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        refresh()
    else:
        main()
