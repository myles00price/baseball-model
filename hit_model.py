"""hit_model.py — daily "to record a hit" probability board (display only).

For every hitter on today's slate, estimates the probability of recording
at least one hit today (and, as a side number, two or more) and writes the
top of the list to hit_watch_{date}.json for the public board's HIT WATCH
section. Sister of hr_model.py: same shape, same discipline — nothing in
the number that didn't survive a walk-forward holdout.

Method (no trained model — every input is public and the math is inspectable):

  h_PA   = shrunk batter H/PA × starter H/BF factor × park factor
  P(1+)  = 1 - (1 - h_PA) ^ n_eff
  P(2+)  = 1 - (1-h_PA)^n_eff - n_eff·h_PA·(1-h_PA)^(n_eff-1)

2026-08-16 backtest (hit_backtest.py, 22,162 walk-forward starter-games,
May-Jun fit / Jul+ holdout, hit_backtest_data.py boxscore rebuild):

  - The batter's own rate is the signal; the opposing starter's H/BF and
    the park each add a small real sliver on holdout (same as HR). Kept.
  - Recency (last-15 blend), the starter's K-rate, and a home-team PA
    haircut were washes or worse out of sample. Excluded.
  - THE HIT-SPECIFIC LESSON: you cannot plug expected PA straight into the
    exponent the way the HR watch does. 11% of starter-games end with <=2
    PA (subs, early exits, ejections) and PA is endogenous (more hits ->
    more trips), so a raw expected PA runs 3-6 pts hot everywhere. n_eff
    is therefore an EFFECTIVE PA fitted on the May-Jun window:
        morning (no lineups): n_eff = 0.96 × season PA/G
        lineups posted:       n_eff = 0.96 × (0.25·slot-mean PA + 0.75·PA/G)
    A hitter's own PA/G beats his batting slot outright (it carries his
    sub/pinch-hit tendency); the 25% slot blend is the best holdout.
  - Holdout calibration lands within ~2 pts through p=72%; the p>=75%
    tail runs hot (small n) — under watch nightly.

- Batter H/PA shrunk toward the 2026 league rate with a 400-PA prior
  (300-600 flat on Brier; 400 slightly better tail).
- Starter factor: shrunk H-allowed/BF vs league (300-BF prior, capped
  0.80–1.25), blended 55/45 toward neutral for the starter's PA share.
- Park: static HITS park-factor table at half strength (hits factors are
  compressed; Coors is the only big one).

Refresh mode (--refresh): reuses the morning log's factors, re-reads
lineups, drops hitters not in a posted lineup, sets n_eff from the slot
blend, rewrites hit_watch_{date}.json ONLY (the morning training log is
the frozen pre-lineup dataset). Book prices refetched at most every 3h.

Book prices: batter_hits Over 0.5 ("to record a hit") and Over 1.5 (2+)
per game from the Odds API — DK / MGM / CZR when posted. Both
batter_hits and batter_hits_alternate are requested (books split lines
across the two keys); the main key wins if a book posts both. Shown next
to the model's fair American odds. DISPLAY ONLY: no bet flags, no texts,
no ledger.

Training archive: every run writes the FULL slate to hit_log_{date}.csv;
hit_grade.py joins boxscore outcomes nightly into hit_training_data.csv.

Usage:
    python hit_model.py               # today's slate (UTC-7 board day)
    python hit_model.py 2026-08-16    # a specific date
    python hit_model.py --refresh     # lineup-aware display refresh
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
ODDS_MARKETS = "batter_hits,batter_hits_alternate"
SEASON = 2026
BATTER_PRIOR_PA = 400      # shrinkage prior for batter H/PA
PITCHER_PRIOR_BF = 300     # shrinkage prior for pitcher H/BF
PIT_LO, PIT_HI = 0.80, 1.25
STARTER_PA_SHARE = 0.55    # share of lineup PAs the starter faces
PARK_DAMP = 0.5            # apply park factors at half strength
EFF_PA_K = 0.96            # effective-PA scale (fitted May-Jun 2026)
SLOT_W = 0.25              # weight on slot-mean PA once lineups post
PA_G_LO, PA_G_HI = 2.0, 5.0
TOP_N = 15
MIN_PA = 100               # eligibility floor for the public list
ODDS_STAMP_FN = "hit_odds_stamp.txt"
ODDS_REFRESH_HOURS = 3

# Mean ACTUAL PA per starter-game by batting slot (2026 May-Jun, from the
# backtest) — not the full-game table the HR watch uses; see docstring.
SLOT_MEAN_PA = [4.42, 4.31, 4.19, 4.04, 3.89, 3.75, 3.58, 3.30, 3.08]

# Columns of hit_log_{date}.csv, in order. hit_grade.py appends outcome
# columns to these when building hit_training_data.csv — change both
# together (hit_grade migrates the training file's header on change).
LOG_COLS = ["date", "pk", "player_id", "name", "team", "opp", "home",
            "opp_sp", "opp_sp_id", "sp_hand", "season_h", "season_pa",
            "season_g", "pa_g", "n_eff", "f_bat", "f_pit", "f_park",
            "h_pa", "p", "p2",
            "odds_dk", "odds_mgm", "odds_czr",
            "odds2_dk", "odds2_mgm", "odds2_czr", "fair", "fair2"]

# Approximate multi-year HITS park factors (100 = neutral), keyed by home
# team name. Compressed relative to HR factors; damped further by PARK_DAMP.
PARK_H = {
    "Colorado Rockies": 114, "Boston Red Sox": 106, "Kansas City Royals": 104,
    "Cincinnati Reds": 103, "Arizona Diamondbacks": 103, "Texas Rangers": 102,
    "Miami Marlins": 102, "Pittsburgh Pirates": 102, "Los Angeles Angels": 101,
    "Toronto Blue Jays": 101, "Baltimore Orioles": 101, "Minnesota Twins": 101,
    "Philadelphia Phillies": 100, "Chicago White Sox": 100, "Atlanta Braves": 100,
    "Washington Nationals": 100, "Chicago Cubs": 100, "Milwaukee Brewers": 100,
    "Athletics": 100, "St. Louis Cardinals": 99, "Houston Astros": 99,
    "Detroit Tigers": 99, "Tampa Bay Rays": 98, "San Diego Padres": 98,
    "New York Yankees": 98, "Los Angeles Dodgers": 98, "Cleveland Guardians": 98,
    "San Francisco Giants": 97, "New York Mets": 97, "Seattle Mariners": 96,
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


def probs(h_pa, n_eff):
    """(P(1+ hit), P(2+ hits)) in percent from per-PA rate and effective PA."""
    q = max(1e-4, min(0.8, h_pa))
    p0 = (1 - q) ** n_eff
    p1 = n_eff * q * (1 - q) ** (n_eff - 1)
    return round((1 - p0) * 100, 1), round(max(0.0, 1 - p0 - p1) * 100, 1)


def n_eff_for(pa_g, slot=None):
    """Effective PA: morning uses season PA/G; with a lineup slot, blend."""
    pa_g = max(PA_G_LO, min(PA_G_HI, pa_g))
    if slot:
        base = SLOT_W * SLOT_MEAN_PA[min(slot, 9) - 1] + (1 - SLOT_W) * pa_g
    else:
        base = pa_g
    return round(EFF_PA_K * base, 2)


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


def league_hit_rate(session):
    j = get(session, "/teams/stats", season=SEASON, group="hitting",
            stats="season", sportId=1)
    h = pa = 0
    for split in j.get("stats", [{}])[0].get("splits", []):
        st = split.get("stat", {})
        h += int(st.get("hits", 0))
        pa += int(st.get("plateAppearances", 0))
    return h / pa if pa else 0.22, h, pa


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
            "pa": pa, "h": int(st.get("hits", 0)),
            "g": int(st.get("gamesPlayed", 0)) or 1,
        })
    return out


def fetch_pitchers(session, pitcher_ids, league_rate):
    """Per probable starter: shrunk H-allowed/BF multiplier + throwing hand."""
    info = {}
    ids = [str(i) for i in pitcher_ids if i]
    for i in range(0, len(ids), 40):
        chunk = ",".join(ids[i:i + 40])
        j = get(session, "/people", personIds=chunk,
                hydrate=f"stats(group=[pitching],type=[season],season={SEASON})")
        for p in j.get("people", []):
            h = bf = 0
            for s in p.get("stats", []):
                if s.get("group", {}).get("displayName") == "pitching":
                    sp = s.get("splits", [])
                    if sp:
                        st = sp[0].get("stat", {})
                        h = int(st.get("hits", 0))
                        bf = int(st.get("battersFaced", 0))
            shrunk = (h + PITCHER_PRIOR_BF * league_rate) / (bf + PITCHER_PRIOR_BF)
            info[p["id"]] = {
                "mult": max(PIT_LO, min(PIT_HI, shrunk / league_rate)),
                "hand": p.get("pitchHand", {}).get("code"),
            }
    return info


def slate_started(session, date):
    """True if any game on the date is past Preview (live or final)."""
    try:
        j = get(session, "/schedule", sportId=1, date=date, gameTypes="R",
                fields="dates,games,status,abstractGameState")
    except Exception:
        return True  # can't tell -> be safe, don't build
    for day in j.get("dates", []):
        for g in day.get("games", []):
            if g.get("status", {}).get("abstractGameState", "Preview") != "Preview":
                return True
    return False


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


ODDS_KEYS = ("dk", "mgm", "czr", "dk2", "mgm2", "czr2")


def _log_odds(r):
    """Row of a day log -> {dk/mgm/czr[/2]: price} for the columns present."""
    o = {}
    for bk in ("dk", "mgm", "czr"):
        v = r.get(f"odds_{bk}")
        if v:
            o[bk] = int(float(v))
        v = r.get(f"odds2_{bk}")
        if v:
            o[bk + "2"] = int(float(v))
    return o


def load_log_odds(log_fn):
    """{player_id: {dk/mgm/czr/dk2/...: price}} from an existing day log."""
    out = {}
    if not os.path.exists(log_fn):
        return out
    try:
        with open(log_fn, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                o = _log_odds(r)
                if o:
                    out[int(r["player_id"])] = o
    except Exception:
        pass
    return out


def fetch_hit_odds(date, games):
    """{game_pk: {norm_player_name: {dk/mgm/czr: over-0.5 price,
                                     dk2/mgm2/czr2: over-1.5 price}}}

    2 credits per game (two market keys). Any failure -> no odds, never a crash."""
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
    now = datetime.now(timezone.utc)
    skipped_live = 0
    for e in events:
        try:
            cm = datetime.strptime(e["commence_time"], "%Y-%m-%dT%H:%M:%SZ") \
                         .replace(tzinfo=timezone.utc)
            ev_date = cm.astimezone(timezone(timedelta(hours=-7))).strftime("%Y-%m-%d")
        except (KeyError, ValueError):
            cm, ev_date = None, date
        if ev_date != date:
            continue
        # The events feed keeps in-progress games for a while and their
        # prices are LIVE (an 0-for-3 Arraez shows "+165 to record a hit").
        # Pre-game only: skip anything already underway; the day log's
        # morning prices carry over for those games.
        if cm is not None and cm <= now:
            skipped_live += 1
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
                params={"apiKey": key, "markets": ODDS_MARKETS,
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
            mks = sorted(bk.get("markets", []), key=lambda m: m["key"] != "batter_hits")
            for mk in mks:
                if mk["key"] not in ("batter_hits", "batter_hits_alternate"):
                    continue
                for o in mk["outcomes"]:
                    if o.get("name") != "Over":
                        continue
                    pt = o.get("point")
                    suffix = "" if pt == 0.5 else "2" if pt == 1.5 else None
                    if suffix is None:
                        continue
                    prices.setdefault(norm_name(o.get("description")), {}) \
                          .setdefault(col + suffix, o["price"])
        out[g["pk"]] = prices
        time.sleep(0.1)
    print(f"Odds: prices for {sum(len(v) for v in out.values())} hitter-games "
          f"across {len(out)} games, {skipped_live} in-progress games skipped "
          f"(quota remaining {remaining})")
    return out


def _fmt_books(o, keys=("dk", "mgm", "czr")):
    return " ".join(f"{k.upper()} {'+' if o[k] > 0 else ''}{o[k]}" for k in keys if k in o) or "no line"


def main():
    date = (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--")
            else board_date())
    session = requests.Session()

    games = fetch_schedule(session, date)
    if not games:
        print(f"No games on {date}; nothing written.")
        return

    lg_rate, lg_h, lg_pa = league_hit_rate(session)
    print(f"League H/PA {SEASON}: {lg_rate:.4f} ({lg_h} H / {lg_pa} PA)")

    sp_ids = [(g["away_sp"] or {}).get("id") for g in games] + \
             [(g["home_sp"] or {}).get("id") for g in games]
    sp_info = fetch_pitchers(session, sp_ids, lg_rate)
    roster_cache = {}

    def hitters(team_id):
        if team_id not in roster_cache:
            roster_cache[team_id] = fetch_team_hitters(session, team_id)
        return roster_cache[team_id]

    players = []
    for g in games:
        park = PARK_H.get(g["home"], 100)
        park_mult = 1 + (park - 100) / 100 * PARK_DAMP
        for side, opp_side in (("away", "home"), ("home", "away")):
            opp_sp = g[f"{opp_side}_sp"] or {}
            sp = sp_info.get(opp_sp.get("id"), {})
            pitch_mult = STARTER_PA_SHARE * sp.get("mult", 1.0) + (1 - STARTER_PA_SHARE)
            for b in hitters(g[f"{side}_id"]):
                bat_rate = (b["h"] + BATTER_PRIOR_PA * lg_rate) / (b["pa"] + BATTER_PRIOR_PA)
                pa_g = round(b["pa"] / b["g"], 2)
                h_pa = bat_rate * pitch_mult * park_mult
                players.append({
                    "id": b["id"], "name": b["name"], "team": g[side],
                    "opp": g[opp_side], "home": side == "home", "pk": g["pk"],
                    "opp_sp": opp_sp.get("fullName", "TBD"),
                    "opp_sp_id": opp_sp.get("id"), "sp_hand": sp.get("hand"),
                    "h": b["h"], "pa": b["pa"], "g": b["g"], "pa_g": pa_g,
                    "n_eff": n_eff_for(pa_g),
                    "f_bat": round(bat_rate / lg_rate, 2),
                    "f_pit": round(pitch_mult, 2),
                    "f_park": round(park_mult, 2),
                    "h_pa": round(h_pa, 5),
                })

    # Doubleheaders list a team twice — keep each hitter's best game only.
    best = {}
    for p in players:
        if p["id"] not in best or p["h_pa"] > best[p["id"]]["h_pa"]:
            best[p["id"]] = p
    players = list(best.values())
    for p in players:
        p["p"], p["p2"] = probs(p["h_pa"], p["n_eff"])
    players.sort(key=lambda x: -x["p"])

    odds = fetch_hit_odds(date, games)
    if odds:
        with open(ODDS_STAMP_FN, "w") as f:
            f.write(str(time.time()))
    prev = load_log_odds(f"hit_log_{date}.csv")
    for p in players:
        fresh = odds.get(p["pk"], {}).get(norm_name(p["name"]), {})
        p["odds"] = fresh or prev.get(p["id"], {})
        p["fair"] = american_from_prob(p["p"] / 100)
        p["fair2"] = american_from_prob(p["p2"] / 100)

    log_fn = f"hit_log_{date}.csv"
    with open(log_fn, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLS)
        w.writeheader()
        for p in players:
            o = p["odds"]
            w.writerow({
                "date": date, "pk": p["pk"], "player_id": p["id"],
                "name": p["name"], "team": p["team"], "opp": p["opp"],
                "home": int(p["home"]), "opp_sp": p["opp_sp"],
                "opp_sp_id": p["opp_sp_id"] or "", "sp_hand": p["sp_hand"] or "",
                "season_h": p["h"], "season_pa": p["pa"], "season_g": p["g"],
                "pa_g": p["pa_g"], "n_eff": p["n_eff"],
                "f_bat": p["f_bat"], "f_pit": p["f_pit"], "f_park": p["f_park"],
                "h_pa": p["h_pa"], "p": p["p"], "p2": p["p2"],
                "odds_dk": o.get("dk", ""), "odds_mgm": o.get("mgm", ""),
                "odds_czr": o.get("czr", ""),
                "odds2_dk": o.get("dk2", ""), "odds2_mgm": o.get("mgm2", ""),
                "odds2_czr": o.get("czr2", ""),
                "fair": p["fair"], "fair2": p["fair2"],
            })
    print(f"Logged {len(players)} hitter rows to {log_fn}")

    top = [dict(p) for p in players[:TOP_N]]
    for p in top:
        del p["sp_hand"]

    out = {
        "date": date,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "league_h_pa": round(lg_rate, 4),
        "players": top,
    }
    fn = f"hit_watch_{date}.json"
    with open(fn, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\nTop {TOP_N} hit probabilities for {date}:")
    for p in top:
        print(f"  {p['p']:5.1f}%  {p['name']:<24} {p['team']} vs {p['opp_sp']}"
              f"  fair {p['fair']} | {_fmt_books(p['odds'])} | 2+ {p['p2']:.0f}% {p['fair2']}")
    print(f"\nSaved {fn}")


def refresh():
    """Lineup-aware display refresh — rewrites hit_watch_{date}.json ONLY."""
    date = board_date()
    log_fn = f"hit_log_{date}.csv"
    session = requests.Session()
    if not os.path.exists(log_fn):
        # Full-build fallback ONLY while the whole slate is still pre-game:
        # a log built after first pitch carries same-day stats (season
        # totals update live) and would poison the training archive.
        if slate_started(session, date):
            print("refresh: no morning log and games already underway - "
                  "skipping (no leaky log)")
            return
        print("refresh: no morning log - running full build instead")
        return main()
    with open(log_fn, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return
    games = fetch_schedule(session, date)
    lineups = fetch_lineups(session, date)

    odds = None
    try:
        stamp = float(open(ODDS_STAMP_FN).read().strip())
    except Exception:
        stamp = 0.0
    if time.time() - stamp > ODDS_REFRESH_HOURS * 3600:
        odds = fetch_hit_odds(date, games)
        if odds:
            with open(ODDS_STAMP_FN, "w") as f:
                f.write(str(time.time()))

    out_players = []
    dropped = 0
    for r in rows:
        pk = int(r["pk"])
        pid = int(r["player_id"])
        pa_g = float(r["pa_g"])
        slots = lineups.get(pk)
        slot = None
        if slots is not None:
            if pid not in slots:
                dropped += 1
                continue
            slot = slots[pid]
        n_eff = n_eff_for(pa_g, slot)
        p, p2 = probs(float(r["h_pa"]), n_eff)
        o = odds.get(pk, {}).get(norm_name(r["name"]), {}) if odds else {}
        if not o:
            o = _log_odds(r)
        out_players.append({
            "id": pid, "name": r["name"], "team": r["team"], "opp": r["opp"],
            "home": r["home"] == "1", "pk": pk, "opp_sp": r["opp_sp"],
            "opp_sp_id": int(r["opp_sp_id"]) if r.get("opp_sp_id") else None,
            "p": p, "p2": p2, "h": int(r["season_h"]), "pa": int(r["season_pa"]),
            "g": int(r["season_g"]), "pa_g": pa_g, "n_eff": n_eff, "slot": slot,
            "f_bat": float(r["f_bat"]), "f_pit": float(r["f_pit"]),
            "f_park": float(r["f_park"]), "h_pa": float(r["h_pa"]),
            "odds": o, "fair": american_from_prob(p / 100),
            "fair2": american_from_prob(p2 / 100),
        })
    out_players.sort(key=lambda x: -x["p"])
    out = {
        "date": date,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lineups_confirmed": len(lineups),
        "players": out_players[:TOP_N],
    }
    with open(f"hit_watch_{date}.json", "w") as f:
        json.dump(out, f, indent=1)
    print(f"refresh: {len(lineups)} lineups posted, {dropped} hitters dropped, "
          f"top {TOP_N} rewritten")
    for p in out["players"][:5]:
        print(f"  {p['p']:5.1f}%  {p['name']:<24} slot {p['slot']} n_eff {p['n_eff']}")


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        refresh()
    else:
        main()
