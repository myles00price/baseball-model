"""k_model.py — K WATCH: starting-pitcher strikeout distributions (display only).

For every probable starter on today's slate, estimates tonight's strikeout
total as a full distribution, prices every half-line as fair American odds,
and lays the real book lines (DK / FD / MGM / CZR) beside them. Sister of
hr_model.py / hit_model.py: same shape, same discipline — nothing in the
number that didn't survive a walk-forward holdout. NOT a play, never texted.

Method (no trained model; every input is public, the math is inspectable):

  per-PA K prob   logit(p_i) = logit(p_pit) + logit(p_bat_i) - logit(lg)
      p_pit    2026 K/BF shrunk 200 BF toward the pitcher's 2025 rate
               (itself shrunk 200 BF toward league); league if no 2025
      p_bat_i  each lineup batter's 2026 K/PA shrunk 60 PA toward league
      pK       mean of p_i over the nine (team K% if no lineup at all)
  expected BF     0.75 x mean BF of last 5 starts + 0.25 x season mean BF/start
                  (season mean shrunk 3 starts toward league 21.9)
  distribution    mixture over BF = round(exp_bf) + r, r from the empirical
                  residual table fitted May-Jun 2026, of BetaBinomial(BF, pK,
                  kappa=200) -> P(K >= n) for every n -> fair odds per line

2026-08-16 backtest (k_backtest.py, 2,575 walk-forward starts, May-Jun fit /
Jul-Aug holdout, boxscore rebuild by hit_backtest_data.py + k_backtest_data.py):
  - holdout MAE on the K total 1.82 vs 1.89 for "his season K per start"
    and 2.06 for the league mean; mean Brier over lines 3.5-8.5 160.0 vs
    164.7 naive; Brier at the line nearest the model median 235.6 vs 245.9.
  - KEPT: pitcher K% (2025-anchored prior), lineup K% (a small, real
    sliver: pitcher-only is 163.2), recent-start BF blend, mild
    beta-binomial dispersion (log score, tiny).
  - REJECTED on holdout: batter K% vs pitcher hand, 2025 batter prior,
    lineup-OBP tilt on BF, recency (last-5-start K%) blend, scaling the
    lineup term up or down. Team K% is as good as the lineup on fixed
    lines but worse at the book-style line, so the morning number uses the
    team's PREVIOUS game's lineup as a proxy (beats team K%), and the
    refresh swaps in the confirmed lineup.
  - Calibration within ~3 pts in the populated buckets; the far tails run
    hot on small n (a residual under-dispersion of ~5% in variance).

Regimes / files:
  morning (no lineups)  -> k_watch_{date}.json (display), k_log_{date}.csv
                           (FULL slate + all factors + book prices, frozen
                           training archive), k_batters_{date}.csv (frozen
                           per-batter K% for the refresh to read)
  --refresh             -> re-reads lineups + probables, recomputes with the
                           confirmed lineup from the FROZEN batter file,
                           rewrites the JSON, and appends one row per
                           starter to k_lock_{date}.csv the FIRST time his
                           opponent's lineup posts while the game is still
                           pre-game (the paper "lock" the market compares
                           against). Book prices refetched at most every 3h.
  k_grade.py            -> joins boxscore K totals nightly -> k_training_data.csv

Odds: pitcher_strikeouts (main line) + pitcher_strikeouts_alternate, DK /
FD / MGM / CZR, 2 credits per game per fetch. Edge = model P(side) minus
the book's de-vigged implied probability at that exact line, per book and
per alt line; the best edge on the slate sorts the board. DISPLAY ONLY.

Usage:
    python k_model.py               # today's slate (UTC-7 board day)
    python k_model.py 2026-08-17    # a specific date
    python k_model.py --refresh     # lineup-aware display refresh + lock rows
    python k_model.py --refresh 2026-08-17   # same, for a specific date
"""

import csv
import json
import math
import os
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from pitcher_stats import parse_ip, season_total_split

API = "https://statsapi.mlb.com/api/v1"
ODDS_BASE = "https://api.the-odds-api.com/v4/sports/baseball_mlb"
ODDS_BOOKS = "draftkings,fanduel,betmgm,williamhill_us"
BOOK_COL = {"draftkings": "dk", "fanduel": "fd", "betmgm": "mgm", "williamhill_us": "czr"}
BOOKS = ("dk", "fd", "mgm", "czr")
ODDS_MARKETS = "pitcher_strikeouts,pitcher_strikeouts_alternate"
SEASON = 2026
PRIOR_SEASON = 2025

# ── fitted parameters (k_backtest.py, May-Jun 2026 fit window) ──────────
PIT_PRIOR_BF = 200         # shrink 2026 K/BF toward the 2025-anchored target
PRIOR_ANCHOR_BF = 200      # shrink the 2025 rate itself toward league
BAT_PRIOR_PA = 60          # batter K/PA shrinkage toward league
TEAM_PRIOR_PA = 300        # team K% shrinkage (fallback only)
BF_W_RECENT = 0.75         # weight on last-5-start mean BF
BF_N_RECENT = 5
BF_PRIOR_STARTS = 3        # season mean BF shrunk toward league by 3 starts
LG_BF = 21.9               # league mean BF per start (2026 fit window)
KAPPA = 200                # beta-binomial concentration on the per-PA rate
KMAX = 20
# BF residual table (actual - expected, fit window), integer offsets + weights
RESID_V = [-18, -17, -16, -15, -14, -13, -12, -11, -10, -9, -8, -7, -6, -5, -4, -3, -2, -1,
           0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
RESID_W = [0.00872, 0.00201, 0.00336, 0.00403, 0.00268, 0.00336, 0.00336, 0.00403, 0.00403,
           0.00671, 0.0047, 0.01007, 0.01611, 0.02752, 0.04899, 0.05638, 0.09396, 0.11275,
           0.13624, 0.11409, 0.11275, 0.07718, 0.05973, 0.03826, 0.02752, 0.01409, 0.00336,
           0.00134, 0.00134, 0.00134]
LINES = [2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5]

# ── WEEKLY RETRAIN HOOK (2026-08-19) ────────────────────────────────────
# k_backtest.py refits the tunable parameters on a rolling window and writes
# k_bt_params.json; the live model reads it here so the weekly props retrain
# actually reaches production. Constants above are the fallback defaults.
def _load_bt_params():
    global PIT_PRIOR_BF, BAT_PRIOR_PA, BF_W_RECENT, BF_N_RECENT, BF_PRIOR_STARTS, LG_BF, KAPPA, RESID_V, RESID_W
    try:
        import json as _json
        P = _json.load(open("k_bt_params.json", encoding="utf-8"))
    except Exception:
        return None
    try:
        PIT_PRIOR_BF = int(P.get("pit_prior_bf", PIT_PRIOR_BF))
        BAT_PRIOR_PA = int(P.get("bat_prior_pa", BAT_PRIOR_PA))
        BF_W_RECENT = float(P.get("bf_w_recent", BF_W_RECENT))
        BF_N_RECENT = int(P.get("bf_n_recent", BF_N_RECENT))
        BF_PRIOR_STARTS = int(P.get("bf_prior_starts", BF_PRIOR_STARTS))
        LG_BF = float(P.get("lg_bf", LG_BF))
        KAPPA = float(P.get("kappa", KAPPA))
        r = P.get("resid") or {}
        if r.get("v") and r.get("w") and len(r["v"]) == len(r["w"]):
            RESID_V, RESID_W = [int(x) for x in r["v"]], [float(x) for x in r["w"]]
        return P.get("fit_window")
    except Exception:
        return None
BT_FIT_WINDOW = _load_bt_params()

CSV_LINES = [3.5, 4.5, 5.5, 6.5, 7.5, 8.5]

ODDS_STAMP_FN = "k_odds_stamp.txt"
ODDS_REFRESH_HOURS = 3
PEN_USAGE_FN = "pen_usage.csv"

LOG_COLS = ["date", "pk", "pitcher_id", "name", "team", "opp", "home", "hand",
            "season_so", "season_bf", "season_gs", "season_ip", "prior_so", "prior_bf",
            "bf_l5", "bf_season", "exp_bf", "p_pit", "f_pit",
            "lineup_src", "lineup_n", "lineup_k", "f_lineup", "pk_pa", "exp_k"] + \
           [f"p_over_{L}" for L in CSV_LINES] + \
           [f"{c}_{b}" for b in BOOKS for c in ("line", "over", "under")] + \
           ["alts", "cons_line", "p_over_cons", "fair_over", "fair_under",
            "best_side", "best_book", "best_line", "best_price", "best_edge",
            "odds_at", "built_at"]


# ── small helpers ────────────────────────────────────────────────────────

def board_date():
    return datetime.now(timezone(timedelta(hours=-7))).strftime("%Y-%m-%d")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get(session, path, **params):
    r = session.get(f"{API}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def norm_name(n):
    n = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode()
    n = n.lower().replace(".", "").replace("'", "")
    for suf in (" jr", " sr", " ii", " iii", " iv"):
        if n.endswith(suf):
            n = n[: -len(suf)]
    return " ".join(n.split())


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + math.exp(-x))


def american_from_prob(p):
    if p <= 0.001:
        return "+9900"
    if p >= 0.999:
        return "-9900"
    if p >= 0.5:
        return f"-{round(p / (1 - p) * 100)}"
    return f"+{round((1 - p) / p * 100)}"


def implied(o):
    o = float(o)
    return (-o) / (-o + 100) if o < 0 else 100 / (o + 100)


def fmt_odds(o):
    return f"+{o}" if o > 0 else str(o)


# ── distribution ─────────────────────────────────────────────────────────

def _betabinom_pmf(n, a, b):
    """P(K=k), k=0..n for BetaBinomial(n, a, b)."""
    lb = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    out = []
    for k in range(n + 1):
        lp = (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
              + math.lgamma(k + a) + math.lgamma(n - k + b) - math.lgamma(n + a + b) - lb)
        out.append(math.exp(lp))
    return out


def k_distribution(exp_bf, pk):
    """pmf over K=0..KMAX: mixture over BF residuals of BetaBinomial(BF, pK*kappa, (1-pK)*kappa)."""
    pmf = [0.0] * (KMAX + 1)
    base = int(round(exp_bf))
    a, b = pk * KAPPA, (1 - pk) * KAPPA
    cache = {}
    for w, r in zip(RESID_W, RESID_V):
        n = min(max(base + r, 1), 40)
        if n not in cache:
            cache[n] = _betabinom_pmf(n, a, b)
        for k, pr in enumerate(cache[n]):
            pmf[min(k, KMAX)] += w * pr
    s = sum(pmf)
    return [x / s for x in pmf]


def p_over(pmf, line):
    return sum(pmf[int(math.ceil(line)):])


def mean_of(pmf):
    return sum(k * p for k, p in enumerate(pmf))


# ── statsapi pulls ───────────────────────────────────────────────────────

def fetch_schedule(session, date):
    j = get(session, "/schedule", sportId=1, date=date, gameTypes="R",
            hydrate="probablePitcher,lineups")
    games = []
    for day in j.get("dates", []):
        for g in day.get("games", []):
            lu = g.get("lineups") or {}
            games.append({
                "pk": g["gamePk"],
                "state": g.get("status", {}).get("abstractGameState", "Preview"),
                "away_id": g["teams"]["away"]["team"]["id"],
                "away": g["teams"]["away"]["team"]["name"],
                "home_id": g["teams"]["home"]["team"]["id"],
                "home": g["teams"]["home"]["team"]["name"],
                "away_sp": g["teams"]["away"].get("probablePitcher"),
                "home_sp": g["teams"]["home"].get("probablePitcher"),
                "away_lineup": [p["id"] for p in (lu.get("awayPlayers") or []) if p.get("id")][:9],
                "home_lineup": [p["id"] for p in (lu.get("homePlayers") or []) if p.get("id")][:9],
            })
    return games


def league_and_team_k(session):
    """(league K/PA, {team_id: (so, pa)}) from the season team-hitting table."""
    j = get(session, "/teams/stats", season=SEASON, group="hitting", stats="season", sportId=1)
    so = pa = 0
    teams = {}
    for split in j.get("stats", [{}])[0].get("splits", []):
        st = split.get("stat", {})
        tid = split.get("team", {}).get("id")
        s, p = int(st.get("strikeOuts", 0)), int(st.get("plateAppearances", 0))
        so += s
        pa += p
        if tid:
            teams[tid] = (s, p)
    return (so / pa if pa else 0.22), teams


def _people_stats(session, ids, group, season):
    """{id: (stat dict of the season total split, person)}"""
    out = {}
    ids = [str(i) for i in ids if i]
    for i in range(0, len(ids), 40):
        chunk = ",".join(ids[i:i + 40])
        try:
            j = get(session, "/people", personIds=chunk,
                    hydrate=f"stats(group=[{group}],type=[season],season={season})")
        except Exception as e:
            print(f"WARNING: people stats chunk failed ({e})")
            continue
        for p in j.get("people", []):
            st = {}
            for s in p.get("stats", []):
                if s.get("group", {}).get("displayName") == group:
                    sp = s.get("splits", [])
                    if sp:
                        st = season_total_split(sp).get("stat", {})
            out[p["id"]] = (st, p)
    return out


def load_pen_usage_starts():
    """{pid: [bf of each start, date-ordered]} from pen_usage.csv."""
    starts = defaultdict(list)
    if not os.path.exists(PEN_USAGE_FN):
        return starts
    rows = []
    with open(PEN_USAGE_FN, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("started") == "1" and r.get("batters_faced"):
                try:
                    rows.append((r["date"], int(r["game_pk"]), int(r["pid"]), int(float(r["batters_faced"]))))
                except ValueError:
                    continue
    rows.sort()
    for d, pk, pid, bf in rows:
        starts[pid].append(bf)
    return starts


def gamelog_starts(session, pid):
    """Fallback BF-per-start list from the statsapi game log (pitcher not in pen_usage)."""
    try:
        j = get(session, f"/people/{pid}/stats", stats="gameLog", group="pitching", season=SEASON)
        out = []
        for sp in j.get("stats", [{}])[0].get("splits", []):
            st = sp.get("stat", {})
            if int(st.get("gamesStarted", 0) or 0) >= 1 and st.get("battersFaced"):
                out.append(int(st["battersFaced"]))
        return out
    except Exception:
        return []


def pitcher_factors(session, ids, lg_k, pen_starts):
    """Per pitcher: shrunk per-PA K rate, expected BF, season line, hand."""
    cur = _people_stats(session, ids, "pitching", SEASON)
    pri = _people_stats(session, ids, "pitching", PRIOR_SEASON)
    out = {}
    for pid in ids:
        if not pid:
            continue
        st, person = cur.get(pid, ({}, {}))
        so, bf = int(st.get("strikeOuts", 0) or 0), int(st.get("battersFaced", 0) or 0)
        gs, ip = int(st.get("gamesStarted", 0) or 0), parse_ip(st.get("inningsPitched", 0))
        pst, _ = pri.get(pid, ({}, {}))
        pso, pbf = int(pst.get("strikeOuts", 0) or 0), int(pst.get("battersFaced", 0) or 0)
        target = (pso + PRIOR_ANCHOR_BF * lg_k) / (pbf + PRIOR_ANCHOR_BF) if pbf > 0 else lg_k
        p_pit = (so + PIT_PRIOR_BF * target) / (bf + PIT_PRIOR_BF)
        starts = pen_starts.get(pid) or gamelog_starts(session, pid)
        n_st = len(starts)
        bf_l5 = sum(starts[-BF_N_RECENT:]) / len(starts[-BF_N_RECENT:]) if starts else LG_BF
        bf_season = (sum(starts) + BF_PRIOR_STARTS * LG_BF) / (n_st + BF_PRIOR_STARTS)
        exp_bf = BF_W_RECENT * bf_l5 + (1 - BF_W_RECENT) * bf_season if starts else bf_season
        out[pid] = {
            "name": person.get("fullName", ""), "hand": person.get("pitchHand", {}).get("code", ""),
            "so": so, "bf": bf, "gs": gs, "ip": round(ip, 1), "pso": pso, "pbf": pbf,
            "p_pit": p_pit, "f_pit": p_pit / lg_k, "bf_l5": round(bf_l5, 2),
            "bf_season": round(bf_season, 2), "exp_bf": round(exp_bf, 2), "n_starts": n_st,
        }
    return out


def fetch_team_batters(session, team_id):
    """Active-roster hitters with 2026 K / PA -> {id: (name, so, pa)}."""
    j = get(session, f"/teams/{team_id}/roster", rosterType="active",
            hydrate=f"person(stats(group=[hitting],type=[season],season={SEASON}))")
    out = {}
    for entry in j.get("roster", []):
        p = entry.get("person", {})
        if entry.get("position", {}).get("abbreviation") == "P":
            continue
        st = {}
        for s in p.get("stats", []):
            if s.get("group", {}).get("displayName") == "hitting":
                sp = s.get("splits", [])
                if sp:
                    st = season_total_split(sp).get("stat", {})
        out[p["id"]] = (p.get("fullName", ""), int(st.get("strikeOuts", 0) or 0),
                        int(st.get("plateAppearances", 0) or 0))
    return out


def previous_lineups(session, date, team_ids):
    """{team_id: [9 batter ids]} from each team's most recent FINAL game before date."""
    d1 = datetime.strptime(date, "%Y-%m-%d")
    start = (d1 - timedelta(days=6)).strftime("%Y-%m-%d")
    end = (d1 - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        j = get(session, "/schedule", sportId=1, startDate=start, endDate=end, gameTypes="R",
                fields="dates,date,games,gamePk,status,codedGameState,teams,away,home,team,id")
    except Exception:
        return {}
    last = {}
    for day in j.get("dates", []):
        for g in day.get("games", []):
            if g.get("status", {}).get("codedGameState") != "F":
                continue
            for side in ("away", "home"):
                tid = g["teams"][side]["team"]["id"]
                if tid in team_ids:
                    key = (day["date"], g["gamePk"])
                    if tid not in last or key > last[tid][0]:
                        last[tid] = (key, side)
    out = {}
    box_cache = {}
    for tid, ((d, pk), side) in last.items():
        try:
            if pk not in box_cache:
                box_cache[pk] = get(session, f"/game/{pk}/boxscore")
            players = box_cache[pk]["teams"][side]["players"]
        except Exception:
            continue
        order = []
        for p in players.values():
            bo = p.get("battingOrder")
            if bo and int(bo) % 100 == 0:
                order.append((int(bo), p["person"]["id"]))
        order.sort()
        if len(order) >= 7:
            out[tid] = [pid for _, pid in order[:9]]
    return out


def slate_started(session, date):
    try:
        j = get(session, "/schedule", sportId=1, date=date, gameTypes="R",
                fields="dates,games,status,abstractGameState")
    except Exception:
        return True
    for day in j.get("dates", []):
        for g in day.get("games", []):
            if g.get("status", {}).get("abstractGameState", "Preview") != "Preview":
                return True
    return False


# ── batter side ──────────────────────────────────────────────────────────

def batter_rate(so, pa, lg_k):
    return (so + BAT_PRIOR_PA * lg_k) / (pa + BAT_PRIOR_PA)


def lineup_k(ids, batters, lg_k):
    """(mean shrunk K/PA over the lineup, n found) using the frozen batter table."""
    rates = [batter_rate(batters[b][1], batters[b][2], lg_k) for b in ids if b in batters]
    if not rates:
        return None, 0
    # log-odds average (odds-ratio method), then back to a rate
    return sigmoid(sum(logit(r) for r in rates) / len(rates)), len(rates)


def team_rate(team_id, team_k, lg_k):
    so, pa = team_k.get(team_id, (0, 0))
    return (so + TEAM_PRIOR_PA * lg_k) / (pa + TEAM_PRIOR_PA)


def combine(p_pit, p_bat, lg_k):
    return sigmoid(logit(p_pit) + logit(p_bat) - logit(lg_k))


# ── odds ─────────────────────────────────────────────────────────────────

def fetch_k_odds(date, games):
    """{game_pk: {norm_pitcher_name: {book: {"line": pt, "over": o, "under": u,
                                            "alts": {pt: [o, u]}}}}}
    2 credits per game. Any failure -> no odds, never a crash."""
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("WARNING: ODDS_API_KEY not set - no book odds")
        return {}
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
            cm = datetime.strptime(e["commence_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            ev_date = cm.astimezone(timezone(timedelta(hours=-7))).strftime("%Y-%m-%d")
        except (KeyError, ValueError):
            cm, ev_date = None, date
        if ev_date != date:
            continue
        if cm is not None and cm <= now:      # in-progress prices are live — skip
            skipped_live += 1
            continue
        ev_by_key.setdefault((team_key(e.get("away_team")), team_key(e.get("home_team"))), e["id"])
    out = {}
    remaining = None
    for g in games:
        eid = ev_by_key.get((team_key(g["away"]), team_key(g["home"])))
        if not eid:
            continue
        try:
            r = requests.get(f"{ODDS_BASE}/events/{eid}/odds",
                             params={"apiKey": key, "markets": ODDS_MARKETS,
                                     "oddsFormat": "american", "bookmakers": ODDS_BOOKS},
                             timeout=20)
            remaining = r.headers.get("x-requests-remaining", remaining)
            j = r.json() if r.ok else {}
        except Exception:
            continue
        prices = {}
        for bk in j.get("bookmakers", []):
            col = BOOK_COL.get(bk["key"])
            if not col:
                continue
            for mk in bk.get("markets", []):
                if mk["key"] not in ("pitcher_strikeouts", "pitcher_strikeouts_alternate"):
                    continue
                main = mk["key"] == "pitcher_strikeouts"
                for o in mk.get("outcomes", []):
                    side = (o.get("name") or "").lower()
                    pt = o.get("point")
                    if side not in ("over", "under") or pt is None:
                        continue
                    ent = prices.setdefault(norm_name(o.get("description")), {}) \
                                .setdefault(col, {"line": None, "over": None, "under": None, "alts": {}})
                    if main:
                        ent["line"] = pt
                        ent[side] = o["price"]
                    else:
                        cell = ent["alts"].setdefault(str(pt), [None, None])
                        cell[0 if side == "over" else 1] = o["price"]
        out[g["pk"]] = prices
        time.sleep(0.1)
    print(f"Odds: K lines for {sum(len(v) for v in out.values())} pitcher-games across "
          f"{len(out)} games, {skipped_live} in-progress games skipped (quota remaining {remaining})")
    return out


def price_vs_model(pmf, books):
    """Edges per book/line vs the model. Returns (consensus line, best dict, per-book edges)."""
    lines = [b["line"] for b in books.values() if b.get("line") is not None]
    cons = None
    if lines:
        cnt = defaultdict(int)
        for L in lines:
            cnt[L] += 1
        cons = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    best = None
    edges = {}
    for bk, b in books.items():
        cands = []
        if b.get("line") is not None:
            cands.append((b["line"], b.get("over"), b.get("under"), True))
        for pt, (o, u) in (b.get("alts") or {}).items():
            cands.append((float(pt), o, u, False))
        for L, o, u, is_main in cands:
            po = p_over(pmf, L)
            io = implied(o) if o is not None else None
            iu = implied(u) if u is not None else None
            for side, price, pm_ in (("over", o, po), ("under", u, 1 - po)):
                if price is None:
                    continue
                if io is not None and iu is not None:
                    imp = (io if side == "over" else iu) / (io + iu)
                else:
                    imp = io if side == "over" else iu
                edge = pm_ - imp
                rec = {"side": side, "book": bk, "line": L, "price": price, "p_model": round(pm_, 4),
                       "implied": round(imp, 4), "edge": round(edge, 4), "main": is_main}
                if is_main:
                    edges.setdefault(bk, {})[side] = rec
                if best is None or edge > best["edge"]:
                    best = rec
    return cons, best, edges


# ── build ────────────────────────────────────────────────────────────────

def load_batters_file(fn):
    out = {}
    if not os.path.exists(fn):
        return out
    with open(fn, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[int(r["player_id"])] = (r["name"], int(r["so"]), int(r["pa"]))
    return out


def load_log(fn):
    if not os.path.exists(fn):
        return []
    with open(fn, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _log_books(r):
    """Row of a day log -> {book: {line, over, under, alts}} for the columns present."""
    books = {}
    for b in BOOKS:
        ln = r.get(f"line_{b}")
        if ln not in (None, ""):
            books[b] = {"line": float(ln),
                        "over": int(float(r[f"over_{b}"])) if r.get(f"over_{b}") else None,
                        "under": int(float(r[f"under_{b}"])) if r.get(f"under_{b}") else None,
                        "alts": {}}
    try:
        alts = json.loads(r.get("alts") or "{}")
    except ValueError:
        alts = {}
    for b, a in alts.items():
        books.setdefault(b, {"line": None, "over": None, "under": None, "alts": {}})["alts"] = a
    return books


def evaluate(row, pmf_pk, lg_k):
    """Fill distribution + pricing fields on a starter row given per-PA rate."""
    pmf_pk = min(max(pmf_pk, 0.05), 0.55)
    pmf = k_distribution(row["exp_bf"], pmf_pk)
    row["pk_pa"] = round(pmf_pk, 4)
    row["exp_k"] = round(mean_of(pmf), 2)
    row["dist"] = {str(L): round(p_over(pmf, L), 4) for L in LINES}
    cons, best, edges = price_vs_model(pmf, row.get("books") or {})
    row["cons_line"] = cons
    row["p_over_cons"] = round(p_over(pmf, cons), 4) if cons is not None else None
    row["fair_over"] = american_from_prob(row["p_over_cons"]) if cons is not None else None
    row["fair_under"] = american_from_prob(1 - row["p_over_cons"]) if cons is not None else None
    row["best"] = best
    row["edges"] = edges
    return row


def row_to_csv(row, date, built_at):
    o = {c: "" for c in LOG_COLS}
    o.update({
        "date": date, "pk": row["pk"], "pitcher_id": row["id"], "name": row["name"],
        "team": row["team"], "opp": row["opp"], "home": int(row["home"]), "hand": row["hand"],
        "season_so": row["so"], "season_bf": row["bf"], "season_gs": row["gs"], "season_ip": row["ip"],
        "prior_so": row["pso"], "prior_bf": row["pbf"], "bf_l5": row["bf_l5"],
        "bf_season": row["bf_season"], "exp_bf": row["exp_bf"], "p_pit": round(row["p_pit"], 4),
        "f_pit": round(row["f_pit"], 3), "lineup_src": row["lineup_src"], "lineup_n": row["lineup_n"],
        "lineup_k": round(row["lineup_k"], 4), "f_lineup": round(row["f_lineup"], 3),
        "pk_pa": row["pk_pa"], "exp_k": row["exp_k"],
        "cons_line": row["cons_line"] if row["cons_line"] is not None else "",
        "p_over_cons": row["p_over_cons"] if row["p_over_cons"] is not None else "",
        "fair_over": row["fair_over"] or "", "fair_under": row["fair_under"] or "",
        "odds_at": row.get("odds_at", ""), "built_at": built_at,
    })
    for L in CSV_LINES:
        o[f"p_over_{L}"] = row["dist"][str(L)]
    alts = {}
    for b, bb in (row.get("books") or {}).items():
        if bb.get("line") is not None:
            o[f"line_{b}"] = bb["line"]
            o[f"over_{b}"] = bb["over"] if bb["over"] is not None else ""
            o[f"under_{b}"] = bb["under"] if bb["under"] is not None else ""
        if bb.get("alts"):
            alts[b] = bb["alts"]
    o["alts"] = json.dumps(alts, separators=(",", ":")) if alts else ""
    if row.get("best"):
        b = row["best"]
        o.update({"best_side": b["side"], "best_book": b["book"], "best_line": b["line"],
                  "best_price": b["price"], "best_edge": b["edge"]})
    return o


def public_row(row):
    keep = ("id", "name", "team", "opp", "home", "pk", "hand", "so", "bf", "gs", "ip",
            "f_pit", "bf_l5", "exp_bf", "lineup_src", "lineup_n", "f_lineup", "pk_pa",
            "exp_k", "dist", "books", "cons_line", "p_over_cons", "fair_over", "fair_under",
            "best", "edges", "late", "state")
    out = {k: row.get(k) for k in keep if k in row}
    out["kpct"] = round(100 * row["so"] / row["bf"], 1) if row.get("bf") else None
    out["k9"] = round(9 * row["so"] / row["ip"], 2) if row.get("ip") else None
    return out


def write_json(date, rows, extra):
    rows = sorted(rows, key=lambda r: -(r["best"]["edge"] if r.get("best") else -1))
    out = {"date": date, "generated": now_iso(), "pitchers": [public_row(r) for r in rows]}
    out.update(extra)
    with open(f"k_watch_{date}.json", "w") as f:
        json.dump(out, f, indent=1)
    return out


def main():
    date = (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else board_date())
    session = requests.Session()
    games = fetch_schedule(session, date)
    if not games:
        print(f"No games on {date}; nothing written.")
        return
    lg_k, team_k = league_and_team_k(session)
    print(f"League K/PA {SEASON}: {lg_k:.4f}")
    pen_starts = load_pen_usage_starts()

    sp_ids = [(g["away_sp"] or {}).get("id") for g in games] + [(g["home_sp"] or {}).get("id") for g in games]
    sp = pitcher_factors(session, [i for i in sp_ids if i], lg_k, pen_starts)

    team_ids = sorted({g["away_id"] for g in games} | {g["home_id"] for g in games})
    batters = {}
    for tid in team_ids:
        try:
            batters.update(fetch_team_batters(session, tid))
        except Exception as e:
            print(f"WARNING: roster {tid} failed ({e})")
    prev = previous_lineups(session, date, set(team_ids))
    # previous-lineup batters no longer on an active roster: fetch individually
    missing = {b for ids in prev.values() for b in ids if b not in batters}
    for g in games:
        for side in ("away_lineup", "home_lineup"):
            missing |= {b for b in g[side] if b not in batters}
    if missing:
        for pid, (st, p) in _people_stats(session, sorted(missing), "hitting", SEASON).items():
            batters[pid] = (p.get("fullName", ""), int(st.get("strikeOuts", 0) or 0),
                            int(st.get("plateAppearances", 0) or 0))
    bat_fn = f"k_batters_{date}.csv"
    with open(bat_fn, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["player_id", "name", "so", "pa"])
        for pid, (nm, so, pa) in sorted(batters.items()):
            w.writerow([pid, nm, so, pa])
    print(f"Froze {len(batters)} batter K rates to {bat_fn}; previous lineups for {len(prev)} teams")

    rows = []
    for g in games:
        for side, opp_side in (("away", "home"), ("home", "away")):
            p = g[f"{side}_sp"] or {}
            pid = p.get("id")
            if not pid or pid not in sp:
                continue
            f = sp[pid]
            opp_id = g[f"{opp_side}_id"]
            posted = g[f"{opp_side}_lineup"]
            if len(posted) >= 7:
                lk, n = lineup_k(posted, batters, lg_k)
                src = "confirmed"
            else:
                lk, n = (None, 0)
            if lk is None and prev.get(opp_id):
                lk, n = lineup_k(prev[opp_id], batters, lg_k)
                src = "previous"
            if lk is None:
                lk, n, src = team_rate(opp_id, team_k, lg_k), 0, "team"
            row = {"id": pid, "pk": g["pk"], "team": g[side], "opp": g[opp_side], "home": side == "home",
                   "opp_id": opp_id, "state": g["state"], "lineup_src": src, "lineup_n": n,
                   "lineup_k": lk, "f_lineup": lk / lg_k, **f}
            rows.append(row)

    odds = fetch_k_odds(date, games)
    odds_at = now_iso() if odds else ""
    if odds:
        with open(ODDS_STAMP_FN, "w") as fh:
            fh.write(str(time.time()))
    for r in rows:
        r["books"] = odds.get(r["pk"], {}).get(norm_name(r["name"]), {})
        r["odds_at"] = odds_at
        evaluate(r, combine(r["p_pit"], r["lineup_k"], lg_k), lg_k)

    built_at = now_iso()
    log_fn = f"k_log_{date}.csv"
    # FROZEN-LOG GUARD (2026-08-27 audit): a rebuild after first pitch - or
    # any build for a PAST date - would write live/post-hoc season stats into
    # the frozen training log. Refuse both.
    import requests as _rq
    _sess = _rq.Session()
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    _today = _dt.now(_tz(_td(hours=-7))).strftime("%Y-%m-%d")
    if date < _today:
        print(f"main: {date} is in the past - a rebuilt log would leak post-game "
              f"stats into the training archive. Refusing.")
        return
    if os.path.exists(log_fn) and slate_started(_sess, date):
        print("main: slate already underway and a frozen log exists - refusing "
              "to rebuild it (no leaky log)")
        return
    with open(log_fn, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLS)
        w.writeheader()
        for r in rows:
            w.writerow(row_to_csv(r, date, built_at))
    print(f"Logged {len(rows)} starters to {log_fn}")

    out = write_json(date, rows, {"league_k_pa": round(lg_k, 4), "lineups_confirmed": 0,
                                  "odds_at": odds_at})
    print(f"\nK WATCH {date} — {len(rows)} starters (sorted by best edge):")
    for r in out["pitchers"][:12]:
        b = r.get("best")
        bs = (f"{b['side'].upper()} {b['line']} {b['book'].upper()} {fmt_odds(b['price'])} "
              f"edge {b['edge']*100:+.1f}") if b else "no line"
        print(f"  {r['name']:<22} {r['team'][:14]:<14} exp K {r['exp_k']:4.2f} (BF {r['exp_bf']:.1f}, "
              f"pK {r['pk_pa']*100:.1f}%) | line {r['cons_line']} P(o) {r['p_over_cons']} | {bs}")
    print(f"\nSaved k_watch_{date}.json")


def refresh():
    """Lineup-aware refresh: rewrites k_watch_{date}.json, appends first-confirmation
    rows to k_lock_{date}.csv. Never touches k_log_{date}.csv."""
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    date = args[0] if args else board_date()
    log_fn = f"k_log_{date}.csv"
    session = requests.Session()
    log_rows = load_log(log_fn)
    if not log_rows:
        if slate_started(session, date):
            print("refresh: no morning log and games already underway - skipping (no leaky log)")
            return
        print("refresh: no morning log - running full build instead")
        return main()
    games = fetch_schedule(session, date)
    lg_k, team_k = league_and_team_k(session)
    batters = load_batters_file(f"k_batters_{date}.csv")
    pen_starts = load_pen_usage_starts()
    by_pk_team = {(int(r["pk"]), r["team"]): r for r in log_rows}

    odds = None
    try:
        stamp = float(open(ODDS_STAMP_FN).read().strip())
    except Exception:
        stamp = 0.0
    if time.time() - stamp > ODDS_REFRESH_HOURS * 3600:
        odds = fetch_k_odds(date, games)
        if odds:
            with open(ODDS_STAMP_FN, "w") as fh:
                fh.write(str(time.time()))
    odds_at = now_iso() if odds else ""

    lock_fn = f"k_lock_{date}.csv"
    locked = {(r["pk"], r["pitcher_id"]) for r in load_log(lock_fn)}
    new_lock = []
    rows = []
    n_conf = late = scratched = 0
    late_ids = []
    for g in games:
        for side, opp_side in (("away", "home"), ("home", "away")):
            p = g[f"{side}_sp"] or {}
            pid = p.get("id")
            if not pid:
                continue
            lr = by_pk_team.get((g["pk"], g[side]))
            if lr is not None and int(lr["pitcher_id"]) != pid:
                scratched += 1
                lr = None
            if lr is None:
                late_ids.append((g, side, opp_side, pid))
                continue
            row = _row_from_log(lr)
            _apply_lineup(row, g, opp_side, batters, team_k, lg_k)
            if row["lineup_src"] == "confirmed":
                n_conf += 1
            _apply_odds(row, odds, odds_at, lr)
            evaluate(row, combine(row["p_pit"], row["lineup_k"], lg_k), lg_k)
            row["state"] = g["state"]
            rows.append(row)
    if late_ids:
        # a probable changed since the morning: build his factors fresh (his game
        # hasn't started, so his season line can't include today)
        sp = pitcher_factors(session, sorted({x[3] for x in late_ids}), lg_k, pen_starts)
        # batters not in the frozen file (call-ups) -> league rate via lineup_k fallback
        for g, side, opp_side, pid in late_ids:
            if pid not in sp:
                continue
            row = {"id": pid, "pk": g["pk"], "team": g[side], "opp": g[opp_side], "home": side == "home",
                   "opp_id": g[f"{opp_side}_id"], "state": g["state"], "late": 1, **sp[pid]}
            _apply_lineup(row, g, opp_side, batters, team_k, lg_k)
            if row["lineup_src"] == "confirmed":
                n_conf += 1
            row["books"] = (odds or {}).get(g["pk"], {}).get(norm_name(row["name"]), {})
            row["odds_at"] = odds_at
            evaluate(row, combine(row["p_pit"], row["lineup_k"], lg_k), lg_k)
            rows.append(row)
            late += 1
    stamp_now = now_iso()
    for row in rows:
        key = (str(row["pk"]), str(row["id"]))
        if row["lineup_src"] == "confirmed" and row.get("state") == "Preview" and key not in locked:
            new_lock.append(row_to_csv(row, date, stamp_now))
            locked.add(key)
    if new_lock:
        new_file = not os.path.exists(lock_fn)
        with open(lock_fn, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=LOG_COLS)
            if new_file:
                w.writeheader()
            w.writerows(new_lock)
    write_json(date, rows, {"league_k_pa": round(lg_k, 4), "lineups_confirmed": n_conf,
                            "odds_at": odds_at or (log_rows[0].get("odds_at") if log_rows else ""),
                            "locked": len(locked)})
    print(f"refresh: {n_conf} starters with confirmed opposing lineups, {len(new_lock)} new lock rows "
          f"({len(locked)} total), {late} late-add starters, {scratched} scratched; JSON rewritten")


def _row_from_log(lr):
    return {
        "id": int(lr["pitcher_id"]), "pk": int(lr["pk"]), "name": lr["name"], "team": lr["team"],
        "opp": lr["opp"], "home": lr["home"] == "1", "hand": lr["hand"],
        "so": int(lr["season_so"]), "bf": int(lr["season_bf"]), "gs": int(lr["season_gs"]),
        "ip": float(lr["season_ip"]), "pso": int(lr["prior_so"]), "pbf": int(lr["prior_bf"]),
        "bf_l5": float(lr["bf_l5"]), "bf_season": float(lr["bf_season"]), "exp_bf": float(lr["exp_bf"]),
        "p_pit": float(lr["p_pit"]), "f_pit": float(lr["f_pit"]),
        "lineup_src": lr["lineup_src"], "lineup_n": int(lr["lineup_n"]),
        "lineup_k": float(lr["lineup_k"]), "f_lineup": float(lr["f_lineup"]),
    }


def _apply_lineup(row, g, opp_side, batters, team_k, lg_k):
    posted = g[f"{opp_side}_lineup"]
    if len(posted) >= 7:
        lk, n = lineup_k(posted, batters, lg_k)
        if lk is not None:
            row.update({"lineup_src": "confirmed", "lineup_n": n, "lineup_k": lk, "f_lineup": lk / lg_k})
            return
    if "lineup_k" not in row:      # late-add starter with no lineup yet
        lk = team_rate(g[f"{opp_side}_id"], team_k, lg_k)
        row.update({"lineup_src": "team", "lineup_n": 0, "lineup_k": lk, "f_lineup": lk / lg_k})


def _apply_odds(row, odds, odds_at, lr):
    fresh = (odds or {}).get(row["pk"], {}).get(norm_name(row["name"]), {}) if odds else {}
    if fresh:
        row["books"], row["odds_at"] = fresh, odds_at
    else:
        row["books"], row["odds_at"] = _log_books(lr), lr.get("odds_at", "")


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        refresh()
    else:
        main()
