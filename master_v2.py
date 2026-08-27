import requests
import pandas as pd
from pybaseball import statcast_pitcher, playerid_lookup
from datetime import datetime, timedelta, timezone
import csv
import pickle
import numpy as np
import warnings
warnings.filterwarnings("ignore")
import os
import sys
# Task Scheduler consoles use cp1252, which can't encode → / emoji glyphs
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from pitcher_stats import get_blended_pitcher_stats
from lineup_stats import get_platoon_lineup_ops
from bullpen_stats import get_bullpen_stats
from line_tracker import save_current_lines, get_line_movement
from features_v2 import (predict_home_win_prob_v2, is_bet, BET_MIN, BET_MAX,
                         commence_lv_date, key_from_sched, key_from_row)
import f5_shadow  # SHADOW ONLY — logs would-be F5 plays, never texts/flags real bets

# ─────────────────────────────────────────────────────────────
# master_v2.py — V2 inference. Four fixes vs master.py:
#
# 1. LINEUP SWAP BUG FIXED. Old code assigned the away lineup's
#    OPS to home_lineup_ops and vice versa whenever lineups were
#    confirmed — the model received each team's offense under the
#    other team's label, flipping the sign of ops_diff. Training
#    (weekly_retrain) used the correct assignment, so inference
#    contradicted training on every confirmed-lineup game.
#
# 2. POST-MODEL ADJUSTMENT LAYERS REMOVED (park factor, +0.5 home
#    boost, bullpen nudge, 30-70 clamp). The model is calibrated;
#    additive tweaks after calibration destroy it. Re-scoring the
#    117 live-graded games: these layers flipped the pick in 28%
#    of games and the raw model won 57.6% of those flips vs 42.4%
#    for the adjusted pipeline. Park effects already live inside
#    season stats (the backlog-#2 double count — now gone because
#    the whole layer is gone). Park factor and bullpen numbers are
#    still DISPLAYED as context; they just don't move the number.
#
# 3. V2 MODEL: 4-feature calibrated logistic regression
#    (features_v2.py). Walk-forward 60.2% / 0.2325 Brier vs the
#    old 18-feature XGBoost's 58.7% / 0.2372. Loads once per run.
#
# 4. BET WINDOW moved to 3–8% (EDGE_MIN/EDGE_MAX below). Graded
#    data: 3–6% edges hit 57.5%, 6–10% hit 38.9% — huge model
#    edges were mostly model error. Kept configurable.
#
# Kept: Sharp FADE veto (2/15 = 13.3% empirical, keep it),
# Coors exclusion, pitcher reliability gate, frozen Live/Final
# rows, CSV schema (downstream dashboard unchanged).
# ─────────────────────────────────────────────────────────────

# ** BET ** window lives in features_v2 (BET_MIN/BET_MAX) — single source
# of truth shared with graders and notifications. Revisit after 100+ graded
# V2 picks.
EDGE_MIN = BET_MIN
EDGE_MAX = BET_MAX

# Starter-sample gate (side-aware, refined 2026-07-30 same night):
#  - The starter on OUR side of the bet must have >= 25% season reliability
#    (bets trusting our own thin data went 11-22, -$759).
#  - A thin OPPOSING starter is fadeable (16-13, +$269) UNLESS his whiff rate
#    says the stuff is real (>= 11%): thin+good-stuff starters' teams win 55%
#    - the "returning ace" profile the market prices and career-blends miss.
RELIABILITY_MIN = 25
THIN_ACE_WHIFF = 11.0


def bet_side_ok(bet_rel, opp_rel, opp_whiff):
    if bet_rel < RELIABILITY_MIN:
        return False
    if opp_rel < RELIABILITY_MIN:
        try:
            if opp_whiff is None or float(opp_whiff) >= THIN_ACE_WHIFF:
                return False  # never fade a thin starter with real stuff
        except (TypeError, ValueError):
            return False
    return True

PARK_FACTORS = {
    "Colorado Rockies":        118,
    "Cincinnati Reds":         106,
    "Philadelphia Phillies":   105,
    "Boston Red Sox":          104,
    "Chicago Cubs":            104,
    "Texas Rangers":           103,
    "Baltimore Orioles":       102,
    "Atlanta Braves":          102,
    "New York Yankees":        101,
    "Milwaukee Brewers":       100,
    "Toronto Blue Jays":       100,
    "Minnesota Twins":         100,
    "Detroit Tigers":          100,
    "Houston Astros":          99,
    "Kansas City Royals":      99,
    "Washington Nationals":    99,
    "Chicago White Sox":       99,
    "Cleveland Guardians":     98,
    "Tampa Bay Rays":          98,
    "Pittsburgh Pirates":      98,
    "St. Louis Cardinals":     98,
    "Arizona Diamondbacks":    97,
    "New York Mets":           97,
    "Los Angeles Angels":      97,
    "Miami Marlins":           96,
    "Los Angeles Dodgers":     96,
    "Seattle Mariners":        96,
    "San Francisco Giants":    95,
    "Athletics":               95,
    "San Diego Padres":        94,
}

VIG_MIN = 102.0
VIG_MAX = 108.0

def check_vig(away_prob, home_prob, bookmaker):
    """Returns a warning string if vig is outside the normal 102–108% range,
    or None if vig is normal or odds are missing."""
    if away_prob is None or home_prob is None:
        return None
    vig = away_prob + home_prob
    if VIG_MIN <= vig <= VIG_MAX:
        return None
    return f"{bookmaker} vig {vig:.1f}%"

# V2: apply_park_factor and apply_bullpen_adjustment REMOVED.
# They were additive tweaks applied AFTER isotonic calibration, which
# un-calibrates the output. Park factor also double-counted park effects
# already baked into season stats (backlog #2). PARK_FACTORS is retained
# above for display context only.

def get_team_stats(season):
    data = requests.get(
        "https://statsapi.mlb.com/api/v1/teams/stats",
        params={"season": season, "sportId": 1, "group": "hitting", "stats": "season"}
    ).json()
    team_stats = {}
    for team in data["stats"][0]["splits"]:
        name = team["team"]["name"]
        s = team["stat"]
        team_stats[name] = {
            "ops":  float(s.get("ops", 0)),
            "kpct": round(int(s.get("strikeOuts", 0)) / max(int(s.get("plateAppearances", 1)), 1) * 100, 1),
            "runs": float(s.get("runs", 0))
        }
    return team_stats

def get_todays_lineups(date_str, season):
    data = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={"sportId": 1, "date": date_str, "hydrate": "lineups"}
    ).json()
    lineups = {}
    for d in data.get("dates", []):
        for g in d.get("games", []):
            home = g["teams"]["home"]["team"]["name"]
            away = g["teams"]["away"]["team"]["name"]
            lineup_data = g.get("lineups", {})
            home_players = lineup_data.get("homePlayers", [])
            away_players = lineup_data.get("awayPlayers", [])
            # keyed by team (legacy) AND by game key, so a doubleheader's
            # two games keep their own lineups
            gk = key_from_sched(g)
            lineups[(gk, "home")] = home_players if home_players else []
            lineups[(gk, "away")] = away_players if away_players else []
            lineups[home] = home_players if home_players else []
            lineups[away] = away_players if away_players else []
    return lineups

# V2: prediction now lives in features_v2.predict_home_win_prob_v2.
# 4 winsorized features, calibrated logistic regression, model loaded
# once per process (old code unpickled model.pkl for every single game).
# Feature definition is shared with the trainer so it can't drift.

def american_to_prob(odds):
    try:
        odds = float(odds)
        if odds < 0:
            return round((-odds) / (-odds + 100) * 100, 1)
        else:
            return round(100 / (odds + 100) * 100, 1)
    except:
        return None

def edge(model_p, market_p, reliable=True):
    if model_p and market_p:
        e = round(model_p - market_p, 1)
        flag = " ** BET **" if (is_bet(e) and reliable) else ""
        return f"{e:+.1f}%{flag}"
    return "N/A"

PICK_COLUMNS = [
    "Date", "Away", "Home",
    "Model Away%", "Model Home%",
    "DK Away Odds", "DK Home Odds",
    "MGM Away Odds", "MGM Home Odds",
    "DK Edge Away", "MGM Edge Away",
    "DK Edge Home", "MGM Edge Home",
    "Away SP", "Away Hand", "Away Reliability%",
    "Away SP Velo", "Away SP Spin", "Away SP Whiff",
    "Home SP", "Home Hand", "Home Reliability%",
    "Home SP Velo", "Home SP Spin", "Home SP Whiff",
    "Away Lineup OPS", "Home Lineup OPS",
    "Away BP ERA(7d)", "Home BP ERA(7d)",
    "Away Line Move", "Home Line Move",
    "Sharp Signal",
    "Lineup Source", "Park Factor", "Flag",
    "Odds Warning",
    "Devig DK Edge Away", "Devig DK Edge Home",
    "Devig MGM Edge Away", "Devig MGM Edge Home",
    "Devig Bet",
    "CZR Away Odds", "CZR Home Odds",
    # doubleheader support (2026-08-17): game number within the day (1 for
    # single games) + MLB gamePk. Appended LAST so positional consumers of
    # the older columns are unaffected.
    "Game#", "GamePk",
    # runline shadow (2026-08-24): flagged-side +/-1.5 point@price per book
    "DK RL Away", "DK RL Home", "MGM RL Away", "MGM RL Home",
]


def save_picks_to_csv(picks, date_str):
    filename = f"picks_{date_str}.csv"
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(PICK_COLUMNS)
        for pick in picks:
            writer.writerow([str(p) for p in pick])
    print(f"\nPicks saved to {filename}")

def run_model(target_date, save_csv=True):
    las_vegas_offset = timezone(timedelta(hours=-7))
    target = target_date
    target_str = target.strftime("%Y-%m-%d")
    season = target.year
    season_start = f"{season}-04-01"

    print(f"Loading data for {target_str}...\n")

    odds_resp = requests.get(
        "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/",
        params={
            "apiKey": os.environ["ODDS_API_KEY"],  # V2: env only — rotate the old key, it was committed in plain text
            "regions": "us",
            "markets": "h2h,spreads",
            "oddsFormat": "american",
            "bookmakers": "draftkings,williamhill_us,betmgm"
        }
    ).json()

    odds_lookup = {}
    # doubleheader-safe: per-event odds keyed by (away, home, commence_time),
    # so game 1 and game 2 of a DH keep their own prices
    odds_events = []
    if not isinstance(odds_resp, list):
        # API error object (quota exhausted, bad key, outage). Run degraded:
        # model probabilities still compute; edges/flags need odds and will be N/A.
        print(f"WARNING: odds API unavailable ({str(odds_resp)[:120]}) - running without odds")
        odds_resp = []
    for game in odds_resp:
        if commence_lv_date(game.get("commence_time")) != target_str:
            continue  # only THIS slate's games — the API returns multiple days
        ev = {"away": game.get("away_team"), "home": game.get("home_team"),
              "t": game.get("commence_time"), "odds": {}}
        ev["rl"] = {}
        for bookmaker in game["bookmakers"]:
            bk = bookmaker["key"]
            for market in bookmaker["markets"]:
                if market["key"] == "h2h":
                    for outcome in market["outcomes"]:
                        team = outcome["name"]
                        if team not in odds_lookup:
                            odds_lookup[team] = {}
                        odds_lookup[team][bk] = outcome["price"]
                        ev["odds"].setdefault(team, {})[bk] = outcome["price"]
                elif market["key"] == "spreads":
                    # RUNLINE SHADOW (2026-08-24): capture the +/-1.5 prices so a
                    # paper runline ledger can grade every flagged play vs real
                    # prices (44% of losses are one-run; +1.5 covered 71% in
                    # backtest - but only live prices can say if it pays).
                    for outcome in market["outcomes"]:
                        team = outcome["name"]
                        pt = outcome.get("point")
                        if pt is None:
                            continue
                        ev["rl"].setdefault(team, {})[bk] = f"{pt:+g}@{outcome['price']}"
        odds_events.append(ev)

    def rl_for_game(away, home, game_date_iso):
        """Runline prices for THIS game (DH-safe, mirrors odds_for_game)."""
        evs = [e for e in odds_events if e["away"] == away and e["home"] == home]
        if not evs:
            return {}
        if len(evs) == 1:
            return evs[0].get("rl", {})
        try:
            gt = datetime.fromisoformat(str(game_date_iso).replace("Z", "+00:00"))
            best = min(evs, key=lambda e: abs(
                (datetime.fromisoformat(str(e["t"]).replace("Z", "+00:00")) - gt).total_seconds()))
            return best.get("rl", {})
        except Exception:
            return evs[0].get("rl", {})

    def odds_for_game(away, home, game_date_iso):
        """Odds for THIS game: if the matchup has multiple events today (DH),
        pick the event whose start is closest to the game's start time.
        Falls back to the team-level lookup (single games)."""
        evs = [e for e in odds_events if e["away"] == away and e["home"] == home]
        if len(evs) <= 1:
            return odds_lookup
        try:
            gt = datetime.fromisoformat(str(game_date_iso).replace("Z", "+00:00"))
            best = min(evs, key=lambda e: abs(
                (datetime.fromisoformat(str(e["t"]).replace("Z", "+00:00")) - gt).total_seconds()))
            return best["odds"]
        except Exception:
            return odds_lookup

    # F5 SHADOW: event ids for per-game F5 odds calls (map itself is free)
    f5_events = f5_shadow.event_id_map(odds_resp, target_str)
    f5_on = f5_shadow.f5_available()
    if not f5_on:
        print("F5 shadow: model_f5.pkl not found - shadow capture skipped")

    schedule = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={"sportId": 1, "date": target_str, "hydrate": "probablePitcher"}
    ).json()

    team_stats = get_team_stats(season)

    print("Pulling confirmed lineups...")
    lineups = get_todays_lineups(target_str, season)
    confirmed = sum(1 for v in lineups.values() if v)
    print(f"Lineups confirmed for {confirmed} teams")

    print("Pulling bullpen stats...")
    bullpen = get_bullpen_stats(season)
    print(f"Bullpen data loaded for {len(bullpen)} teams")

    print("Pulling line movement...")
    try:
        save_current_lines(target_str)
        movement = get_line_movement(target_str)
    except Exception as e:
        print(f"WARNING: line movement unavailable ({e})")
        movement = {}
    print(f"Line movement data for {len(movement)} games\n")

    def get_pitcher_whiff(full_name, pid=None):
        if not full_name or full_name == "TBD":
            return None, None, None, "TBD"
        try:
            if pid is None:  # fallback only — the schedule id is authoritative
                from pitcher_stats import resolve_pid
                pid = resolve_pid(full_name, playerid_lookup, season)
            if pid is None:
                return None, None, None, f"{full_name} | Not found"
            data = statcast_pitcher(season_start, target_str, player_id=int(pid))
            if data.empty:
                return None, None, None, f"{full_name} | No data yet"
            velo  = round(data['release_speed'].mean(), 1)
            spin  = round(data['release_spin_rate'].mean(), 0)
            whiff = round((data['description'] == 'swinging_strike').mean() * 100, 1)
            return velo, spin, whiff, f"{full_name} | Velo: {velo} | Spin: {spin:.0f} | Whiff: {whiff:.1f}%"
        except:
            return None, None, None, f"{full_name} | Error"

    print("=" * 75)
    print(f"  MLB MODEL REPORT — {target_str}")
    print("=" * 75)

    picks = []

    existing_picks = {}
    existing_csv = f"picks_{target_str}.csv"
    if os.path.exists(existing_csv):
        import csv as csv_module
        with open(existing_csv, encoding="utf-8-sig") as f:
            for row in csv_module.DictReader(f):
                key = key_from_row(row)
                existing_picks[key] = row
        print(f"Loaded {len(existing_picks)} existing picks to freeze Live/Final games\n")

    # LOCK-ON-TEXT: once a pick has been texted to subscribers it is the
    # official play — later pre-game reruns must NOT change its flag or odds.
    # (2026-07-28 bug: a rerun dropped the texted Cardinals flag, so the
    # nightly grade missed a play subscribers had bet.)
    texted_keys = set()
    try:
        import json as json_module
        with open(f"notified_{target_str}.json") as f:
            texted_keys = {k for k in json_module.load(f) if not k.startswith("_")}
        if texted_keys:
            print(f"{len(texted_keys)} texted picks are locked and will not be re-evaluated\n")
    except OSError:
        pass

    # Session-level FADE veto counter for end-of-run summary
    fade_vetoes = []

    for date in schedule.get("dates", []):
        for game in date.get("games", []):
            game_status = game.get("status", {}).get("abstractGameState", "")
            home = game["teams"]["home"]["team"]["name"]
            away = game["teams"]["away"]["team"]["name"]
            game_key = key_from_sched(game)          # 'Away@Home' or 'Away@Home#2' (DH)
            game_no = int(game.get("gameNumber", 1) or 1)
            game_pk = game.get("gamePk", "")

            if game_status in ["Live", "Final"] or game_key in texted_keys:
                if game_key in existing_picks:
                    row = existing_picks[game_key]
                    frozen = [row.get(col, "") for col in PICK_COLUMNS]
                    # backfill DH columns on rows written before they existed
                    frozen[PICK_COLUMNS.index("Game#")] = row.get("Game#") or game_no
                    frozen[PICK_COLUMNS.index("GamePk")] = row.get("GamePk") or game_pk
                    picks.append(frozen)
                    status_label = ("🔴 LIVE" if game_status == "Live"
                                    else "✅ FINAL" if game_status == "Final"
                                    else "🔒 TEXTED/LOCKED")
                    print(f"  {status_label} — {away} @ {home} [FROZEN — using pre-game pick]")
                if f5_on:
                    # game locked -> freeze its F5 shadow row at last snapshot
                    f5_shadow.capture(target_str, game_key, None, away, home,
                                      None, False, False, frozen=True)
                continue
            home_p = game["teams"]["home"].get("probablePitcher", {}).get("fullName", "TBD")
            away_p = game["teams"]["away"].get("probablePitcher", {}).get("fullName", "TBD")
            # authoritative MLB ids from the schedule — no name lookup collisions
            home_sched_id = game["teams"]["home"].get("probablePitcher", {}).get("id")
            away_sched_id = game["teams"]["away"].get("probablePitcher", {}).get("id")

            home_stats, home_pid = get_blended_pitcher_stats(home_p, season, playerid_lookup, pid=home_sched_id)
            away_stats, away_pid = get_blended_pitcher_stats(away_p, season, playerid_lookup, pid=away_sched_id)

            home_hand = home_stats["hand"] if home_stats else "R"
            away_hand = away_stats["hand"] if away_stats else "R"
            home_rel  = home_stats.get("reliability", 0) if home_stats else 0
            away_rel  = away_stats.get("reliability", 0) if away_stats else 0

            away_velo, away_spin, away_whiff, away_str = get_pitcher_whiff(away_p, away_sched_id)
            home_velo, home_spin, home_whiff, home_str = get_pitcher_whiff(home_p, home_sched_id)

            # per-game lineups (doubleheader-safe), team-level fallback
            home_players = lineups.get((game_key, "home"), lineups.get(home, []))
            away_players = lineups.get((game_key, "away"), lineups.get(away, []))
            # per-game odds (DH: nearest-start event), team-level fallback
            g_odds = odds_for_game(away, home, game.get("gameDate"))
            g_rl = rl_for_game(away, home, game.get("gameDate"))

            # V2 FIX — lineup swap bug. home_lineup_ops is the HOME team's
            # offense: home batters vs the AWAY pitcher's hand. The old code
            # fed away batters into home_lineup_ops (and vice versa), so the
            # model received each offense under the other team's label on
            # every confirmed-lineup game. Training used the correct
            # assignment (weekly_retrain.py builds home_lineup_ops from
            # home_batters), so inference contradicted training.
            if home_players and away_players:
                home_lineup_ops = get_platoon_lineup_ops(home_players, season, away_hand)
                away_lineup_ops = get_platoon_lineup_ops(away_players, season, home_hand)
                lineup_source = "CONFIRMED+PLATOON"
            elif home_players or away_players:
                home_lineup_ops = get_platoon_lineup_ops(home_players, season, away_hand) if home_players else None
                away_lineup_ops = get_platoon_lineup_ops(away_players, season, home_hand) if away_players else None
                lineup_source = "PARTIAL"
            else:
                home_lineup_ops = None
                away_lineup_ops = None
                lineup_source = "ESTIMATED"

            home_off = team_stats.get(home, {})
            away_off = team_stats.get(away, {})
            home_ops  = home_lineup_ops if home_lineup_ops else home_off.get("ops", 0.72)
            away_ops  = away_lineup_ops if away_lineup_ops else away_off.get("ops", 0.72)
            home_kpct = home_off.get("kpct", 20)
            away_kpct = away_off.get("kpct", 20)

            park_factor = PARK_FACTORS.get(home, 100)
            home_bull = bullpen.get(home)
            away_bull = bullpen.get(away)

            # line movement is tracked per matchup (team key); a DH shares it
            move_data = movement.get(f"{away}@{home}", {})
            away_move = move_data.get("teams", {}).get(away, {})
            home_move = move_data.get("teams", {}).get(home, {})

            away_prob = None
            home_prob = None
            try:
                if home_stats and away_stats:
                    # V2: calibrated output used AS-IS. No home boost, no
                    # park layer, no bullpen nudge — those cost ~4 pts of
                    # pick accuracy on the 117 live-graded games.
                    home_prob = predict_home_win_prob_v2(
                        home_stats["era"], home_stats["whip"],
                        away_stats["era"], away_stats["whip"],
                        home_ops, home_kpct,
                        away_ops, away_kpct
                    )
                    away_prob = round(100 - home_prob, 1)
            except:
                pass

            def _devig_edges(imp_a, imp_h):
                """SHADOW de-vig edges (no behavior change): remove the vig by
                scaling both implied probs to sum to 100, then edge vs model.
                Logged to the CSV so live data can confirm the backtest before
                any switch of the real flag logic."""
                if imp_a is None or imp_h is None or away_prob is None or home_prob is None:
                    return "N/A", "N/A"
                tot = imp_a + imp_h
                dva, dvh = imp_a / tot * 100, imp_h / tot * 100
                return f"{away_prob - dva:+.1f}%", f"{home_prob - dvh:+.1f}%"

            dk_away  = american_to_prob(g_odds.get(away, {}).get("draftkings"))
            mgm_away = american_to_prob(g_odds.get(away, {}).get("betmgm"))
            dk_home  = american_to_prob(g_odds.get(home, {}).get("draftkings"))
            mgm_home = american_to_prob(g_odds.get(home, {}).get("betmgm"))

            # ── Vig sanity check (diagnostic only — does not change picking) ──
            dk_warning  = check_vig(dk_away,  dk_home,  "DK")
            mgm_warning = check_vig(mgm_away, mgm_home, "MGM")
            warnings_list = [w for w in [dk_warning, mgm_warning] if w]
            odds_warning = " | ".join(warnings_list) if warnings_list else ""

            # ── SHADOW: de-vig edges + would-be flag (logged only) ──
            dv_dk_away, dv_dk_home = _devig_edges(dk_away, dk_home)
            dv_mgm_away, dv_mgm_home = _devig_edges(mgm_away, mgm_home)

            def _in_window(s):
                try:
                    return is_bet(float(str(s).replace("%", "")))
                except (ValueError, TypeError):
                    return False
            if _in_window(dv_dk_away) or _in_window(dv_mgm_away):
                devig_bet = away
            elif _in_window(dv_dk_home) or _in_window(dv_mgm_home):
                devig_bet = home
            else:
                devig_bet = ""

            # ── Sharp signal — computed BEFORE the reliable check so it can veto BETs ──
            sharp_signal = "N/A"
            if away_move and home_move and away_prob and home_prob:
                model_favors = away if away_prob > home_prob else home
                away_movement = away_move.get("movement", 0)
                home_movement = home_move.get("movement", 0)
                away_mov = abs(away_movement)
                home_mov = abs(home_movement)
                if max(away_mov, home_mov) < 1.5:
                    sharp_signal = "N/A"
                else:
                    market_moving_toward = away if away_movement > home_movement else home
                    if model_favors == market_moving_toward:
                        sharp_signal = "CONFIRMED ✓"
                    else:
                        sharp_signal = "FADE ✗"

            # ── Reliable: pitcher reliability + Coors exclusion + Sharp FADE veto ──
            # FADE bets went 2/15 (13.3%) for -$1,062 P&L over 6 weeks of paper trading.
            # When sharps move against the model, we suppress the BET flag.
            min_reliability = min(home_rel, away_rel)
            # SHARP VETO NEUTRALIZED 2026-08-27: the signal's line-movement
            # source was measured against date-less "openings" (a prior
            # game's line, 615/619 cases), so every sharp-based decision -
            # including the veto's founding 2-15 evidence - was built on
            # noise. Signal still computed+logged on CLEAN date-scoped
            # openings for the record; it gates nothing until re-founded.
            sharp_veto = False
            base_ok = home != "Colorado Rockies"
            # side-aware gate: our side's SP must be sampled; thin opposing
            # SPs are fadeable only if their stuff is unproven (whiff < 11)
            reliable_away = base_ok and bet_side_ok(away_rel, home_rel, home_whiff)
            reliable_home = base_ok and bet_side_ok(home_rel, away_rel, away_whiff)
            reliable = reliable_away or reliable_home  # for veto bookkeeping

            # Track veto for end-of-run summary (only flag if BET would have fired otherwise)
            if sharp_veto and min_reliability >= RELIABILITY_MIN and home != "Colorado Rockies":
                # Check if any edge column would have triggered BET without the veto
                would_have_bet = any(
                    market_p is not None
                    and model_p is not None
                    and EDGE_MIN <= round(model_p - market_p, 1) <= EDGE_MAX
                    for model_p, market_p in [
                        (away_prob, dk_away), (away_prob, mgm_away),
                        (home_prob, dk_home), (home_prob, mgm_home),
                    ]
                )
                if would_have_bet:
                    fade_vetoes.append(f"{away} @ {home}")

            print(f"\n{away} @ {home} [{lineup_source}] [Park: {park_factor}]")
            if odds_warning:
                print(f"  ⚠️  ODDS WARNING: {odds_warning}  (logged; pick proceeds normally)")
            if sharp_veto and min_reliability >= RELIABILITY_MIN and home != "Colorado Rockies":
                print(f"  🚫 SHARP FADE VETO — BET flag suppressed (sharps moving against model)")
            print(f"  {away_p} ({away_hand}) rel:{away_rel}% | {home_p} ({home_hand}) rel:{home_rel}%")
            print(f"  Platoon OPS — {away}: {away_ops:.3f} vs {home_hand}HP | {home}: {home_ops:.3f} vs {away_hand}HP")
            if home_bull and away_bull:
                print(f"  Away BP: ERA(7d): {away_bull['era_recent']} | "
                      f"Sv/BSv: {away_bull['saves']}/{away_bull['blown_saves']} | "
                      f"Score: {away_bull['bullpen_score']}")
                print(f"  Home BP: ERA(7d): {home_bull['era_recent']} | "
                      f"Sv/BSv: {home_bull['saves']}/{home_bull['blown_saves']} | "
                      f"Score: {home_bull['bullpen_score']}")
            if away_move and home_move:
                print(f"  Line Move — "
                      f"{away}: {away_move.get('open_odds')} → {away_move.get('current_odds')} "
                      f"({away_move.get('movement', 0):+.1f}%) {away_move.get('direction', '')} | "
                      f"{home}: {home_move.get('open_odds')} → {home_move.get('current_odds')} "
                      f"({home_move.get('movement', 0):+.1f}%) {home_move.get('direction', '')} | "
                      f"Sharp: {sharp_signal}")
            print(f"  {'Team':<30} {'Model%':>7} {'DK Imp%':>8} {'MGM Imp%':>9} {'DK Edge':>8} {'MGM Edge':>9}")
            print(f"  {'-'*70}")
            print(f"  {away:<30} {str(away_prob)+'%' if away_prob else 'N/A':>7} "
                  f"{str(dk_away)+'%' if dk_away else 'N/A':>8} "
                  f"{str(mgm_away)+'%' if mgm_away else 'N/A':>9} "
                  f"{edge(away_prob, dk_away, reliable_away):>8} {edge(away_prob, mgm_away, reliable_away):>9}")
            print(f"  {home:<30} {str(home_prob)+'%' if home_prob else 'N/A':>7} "
                  f"{str(dk_home)+'%' if dk_home else 'N/A':>8} "
                  f"{str(mgm_home)+'%' if mgm_home else 'N/A':>9} "
                  f"{edge(home_prob, dk_home, reliable_home):>8} {edge(home_prob, mgm_home, reliable_home):>9}")
            print(f"  Away SP: {away_str}")
            print(f"  Home SP: {home_str}")
            print("-" * 75)

            # ── F5 SHADOW capture (paper only, same gates, de-vig window) ──
            if f5_on and home_prob is not None and home_stats and away_stats:
                try:
                    f5_prob = f5_shadow.predict_f5_home_prob(
                        home_stats["era"], home_stats["whip"],
                        away_stats["era"], away_stats["whip"],
                        home_ops, home_kpct, away_ops, away_kpct)
                    f5_row = f5_shadow.capture(
                        target_str, game_key, f5_events.get(game_key),
                        away, home, f5_prob, reliable_away, reliable_home,
                        frozen=False)
                    if f5_row and f5_row.get("flag"):
                        side = f5_row["flag"]
                        tm = away if side == "away" else home
                        e = f5_row["dv_edge_away"] if side == "away" else f5_row["dv_edge_home"]
                        print(f"  🕐 F5 SHADOW (paper): {tm} first-5 ML, de-vig edge {e:+.1f}%")
                except Exception as e:
                    print(f"  F5 shadow error (ignored): {e}")

            bet_flag = "** BET **" if any(
                "BET" in str(edge(p, m, r))
                for p, m, r in [(away_prob, dk_away, reliable_away),
                                (away_prob, mgm_away, reliable_away),
                                (home_prob, dk_home, reliable_home),
                                (home_prob, mgm_home, reliable_home)]
            ) else ""

            picks.append([
                target_str, away, home,
                away_prob, home_prob,
                g_odds.get(away, {}).get("draftkings", "N/A"),
                g_odds.get(home, {}).get("draftkings", "N/A"),
                g_odds.get(away, {}).get("betmgm", "N/A"),
                g_odds.get(home, {}).get("betmgm", "N/A"),
                edge(away_prob, dk_away, reliable_away), edge(away_prob, mgm_away, reliable_away),
                edge(home_prob, dk_home, reliable_home), edge(home_prob, mgm_home, reliable_home),
                away_p, away_hand, away_rel,
                away_velo, away_spin, away_whiff,
                home_p, home_hand, home_rel,
                home_velo, home_spin, home_whiff,
                away_ops, home_ops,
                away_bull["era_recent"] if away_bull else "N/A",
                home_bull["era_recent"] if home_bull else "N/A",
                away_move.get("movement", "N/A") if away_move else "N/A",
                home_move.get("movement", "N/A") if home_move else "N/A",
                sharp_signal,
                lineup_source, park_factor, bet_flag,
                odds_warning,
                dv_dk_away, dv_dk_home,
                dv_mgm_away, dv_mgm_home,
                devig_bet,
                g_odds.get(away, {}).get("williamhill_us", "N/A"),
                g_odds.get(home, {}).get("williamhill_us", "N/A"),
                game_no, game_pk,
                g_rl.get(away, {}).get("draftkings", ""), g_rl.get(home, {}).get("draftkings", ""),
                g_rl.get(away, {}).get("betmgm", ""), g_rl.get(home, {}).get("betmgm", ""),
            ])

    # End-of-run FADE veto summary
    if fade_vetoes:
        print("\n" + "=" * 75)
        print(f"  🚫 SHARP FADE VETO SUMMARY — {len(fade_vetoes)} BET(s) suppressed today:")
        for g in fade_vetoes:
            print(f"     • {g}")
        print("=" * 75)

    if save_csv:
        save_picks_to_csv(picks, target_str)
    if f5_on:
        f5_shadow.save(target_str)

if __name__ == '__main__':
    # Optional YYYY-MM-DD argument (used by notify_pick.py / auto_lineup_push.py
    # to refresh TODAY's picks when lineups confirm). Default: tomorrow's slate.
    las_vegas_offset = timezone(timedelta(hours=-7))
    if len(sys.argv) > 1:
        target = datetime.strptime(sys.argv[1], "%Y-%m-%d")
    else:
        target = datetime.now(las_vegas_offset) + timedelta(days=1)
    run_model(target, save_csv=True)


