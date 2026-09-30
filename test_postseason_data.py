"""Acceptance tests for the 2026-09-29 postseason audit's data fixes.

Run:  py -3.11 .\\test_postseason_data.py

Covers:
  * k_close/settle housekeeping runs even when nothing is pending (a 2-4 game
    postseason slate is fully texted in one cycle, and the old placement below
    notify_pick's early returns meant no closing line was ever captured - those
    plays fell out of the bet-side CLV gate that governs real-money sizing).
  * "Game Over" (abstractGameState Final, codedGameState "O") counts as final
    in pen_usage_log - it was skipped, so both bullpens in Wild Card game 1
    read as fully rested going into game 2.
  * a pen_usage collection gap reports None, never a rested bullpen.
  * bullpen_stats byDateRange carries the postseason game types (the window
    returns nothing at all once it sits fully inside October).
  * bullpen_rankings fails closed instead of publishing an empty board.
  * the training ingest is regular-season-only by decision.

No network: requests is stubbed in every module under test.
"""

import csv
import json
import os
import sys
import tempfile

# ── stub plumbing ─────────────────────────────────────────────────────────

class StubResponse:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self._payload


class StubRequests:
    """Records every call; replays payloads chosen by a router callable."""
    def __init__(self, router):
        self.router = router
        self.calls = []
    def get(self, url, params=None, timeout=None, **kw):
        self.calls.append({"url": url, "params": params or {}})
        return StubResponse(self.router(url, params or {}))


def swap(mod, name, value):
    old = getattr(mod, name)
    setattr(mod, name, value)
    return lambda: setattr(mod, name, old)


# ── 1. housekeeping reachability in notify_pick ────────────────────────────
import notify_pick
import k_close
import settle_notify

def run_notify_with(confirmed, notified_keys):
    calls = {"k_close": 0, "settle": 0}
    undo = [
        swap(notify_pick, "get_confirmed_games", lambda d: confirmed),
        swap(notify_pick, "load_state", lambda d: set(notified_keys)),
        swap(notify_pick, "save_state", lambda d, n: None),
        swap(notify_pick, "load_picks", lambda d: {}),
        swap(notify_pick, "send_push", lambda *a, **k: None),
        swap(notify_pick, "send_ops", lambda *a, **k: None),
        swap(notify_pick, "fetch_market_odds", lambda d=None: {}),
        swap(k_close, "capture", lambda d: calls.__setitem__("k_close", calls["k_close"] + 1)),
        swap(settle_notify, "main", lambda d=None: calls.__setitem__("settle", calls["settle"] + 1)),
    ]
    import subprocess as _sp
    real_run = _sp.run
    _sp.run = lambda *a, **k: _sp.CompletedProcess(a[0] if a else "", 0, "", "")
    try:
        notify_pick.main()
    finally:
        _sp.run = real_run
        for u in undo:
            u()
    return calls

PREVIEW_GAME = {"away": "Chicago Cubs", "home": "San Diego Padres",
                "state": "Preview", "key": "Chicago Cubs@San Diego Padres",
                "game_no": 1}

# every confirmed game already texted -> `pending` is empty
calls = run_notify_with([PREVIEW_GAME], {"_heartbeat", PREVIEW_GAME["key"]})
assert calls["k_close"] == 1, (
    "k_close.capture skipped when nothing was pending - a fully-texted "
    "postseason slate would never get a true closing line")
assert calls["settle"] == 1, "settle_notify skipped when nothing was pending"

# no lineups posted anywhere -> `confirmed` is empty
calls = run_notify_with([], {"_heartbeat"})
assert calls["k_close"] == 1, "k_close.capture skipped when no lineups were posted"
assert calls["settle"] == 1, "settle_notify skipped when no lineups were posted"

# ── 2. "Game Over" is final for bullpen usage collection ───────────────────
import pen_usage_log

GAME_OVER_SCHEDULE = {"dates": [{"games": [
    {"gamePk": 849843,
     "status": {"abstractGameState": "Final", "codedGameState": "O"}},
]}]}

BOXSCORE = {"teams": {
    "away": {"team": {"name": "Chicago Cubs"},
             "players": {"ID1": {"person": {"id": 1, "fullName": "Reliever One"},
                                 "stats": {"pitching": {"battersFaced": 4,
                                                        "inningsPitched": "1.0",
                                                        "numberOfPitches": 18,
                                                        "gamesStarted": 0}}}}},
    "home": {"team": {"name": "San Diego Padres"},
             "players": {"ID2": {"person": {"id": 2, "fullName": "Reliever Two"},
                                 "stats": {"pitching": {"battersFaced": 3,
                                                        "inningsPitched": "1.0",
                                                        "numberOfPitches": 12,
                                                        "gamesStarted": 0}}}}},
}}

def pen_router(url, params):
    return BOXSCORE if "boxscore" in url else GAME_OVER_SCHEDULE

cwd = os.getcwd()
with tempfile.TemporaryDirectory() as tmp:
    undo = swap(pen_usage_log, "requests", StubRequests(pen_router))
    try:
        os.chdir(tmp)
        n = pen_usage_log.collect("2026-09-29")
        assert n == 2, f'"Game Over" game not collected (wrote {n} rows)'
        rows = list(csv.DictReader(open("pen_usage.csv", encoding="utf-8-sig")))
        assert {r["game_pk"] for r in rows} == {"849843"}, rows
    finally:
        os.chdir(cwd)
        undo()

# ── 3. a collection gap is None, never a rested bullpen ───────────────────
import bullpen_rankings

with tempfile.TemporaryDirectory() as tmp:
    try:
        os.chdir(tmp)
        with open("pen_usage.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=pen_usage_log.FIELDS)
            w.writeheader()
            # Cubs pitched on 9/28 only; their 9/29 game is MISSING from the file
            w.writerow({"date": "2026-09-28", "game_pk": "1", "team": "Chicago Cubs",
                        "pid": "10", "name": "A", "started": "0", "ip": "1.0",
                        "pitches": "15", "batters_faced": "3"})
            w.writerow({"date": "2026-09-29", "game_pk": "2", "team": "San Diego Padres",
                        "pid": "20", "name": "B", "started": "0", "ip": "1.0",
                        "pitches": "17", "batters_faced": "4"})
        undo = swap(bullpen_rankings, "teams_that_played",
                    lambda d: {"Chicago Cubs", "San Diego Padres"} if d == "2026-09-29" else set())
        try:
            um = bullpen_rankings.usage_metrics("2026-09-30")
        finally:
            undo()
        assert um["Chicago Cubs"]["pitches2"] is None, (
            f"missing game read as usable data: {um['Chicago Cubs']}")
        assert um["Chicago Cubs"].get("stale") is True
        assert um["Chicago Cubs"]["fresh_top"] is None, (
            "a collection gap must never publish fresh arms")
        assert um["San Diego Padres"]["pitches2"] == 17, (
            f"complete data mis-flagged: {um['San Diego Padres']}")
    finally:
        os.chdir(cwd)

# ── 4. bullpen byDateRange must admit postseason ──────────────────────────
import bullpen_stats

TEAM_STATS = {"stats": [{"splits": [
    {"team": {"name": "Atlanta Braves"},
     "stat": {"era": "3.00", "whip": "1.10", "saves": 40, "blownSaves": 10,
              "holds": 50, "inningsPitched": "9.0"}},
]}]}

stub = StubRequests(lambda url, params: TEAM_STATS)
undo = swap(bullpen_stats, "requests", stub)
try:
    bp = bullpen_stats.get_bullpen_stats(2026, as_of="2026-10-10")
finally:
    undo()
ranged = [c for c in stub.calls if c["params"].get("stats") == "byDateRange"]
assert ranged, "no byDateRange call issued"
sent = ranged[0]["params"].get("gameType", "")
for code in ("R", "F", "D", "L", "W"):
    assert code in sent, f"byDateRange dropped game type {code!r} (sent {sent!r})"
assert ranged[0]["params"]["endDate"] == "2026-10-10", (
    "as_of ignored - a replay would use today's window")
assert bp, "postseason-only window produced no bullpen data"

# ── 5. bullpen_rankings fails closed on an empty table ────────────────────
with tempfile.TemporaryDirectory() as tmp:
    try:
        os.chdir(tmp)
        good = {"updated": "2026-09-29", "teams": [{"team": "Atlanta Braves", "rank": 1}]}
        with open("bullpen_rankings.json", "w", encoding="utf-8") as f:
            json.dump(good, f)
        undo = [swap(bullpen_rankings, "get_bullpen_stats", lambda *a, **k: {}),
                swap(bullpen_rankings, "usage_metrics", lambda d: {})]
        try:
            rc = bullpen_rankings.main()
        finally:
            for u in undo:
                u()
        assert rc, f"empty bullpen table should exit non-zero, got {rc!r}"
        assert json.load(open("bullpen_rankings.json")) == good, (
            "empty table overwrote the last good bullpen_rankings.json")
    finally:
        os.chdir(cwd)

# ── 6. training ingest is regular-season only, by decision ────────────────
import weekly_retrain

POSTSEASON_FINAL = {"dates": [{"games": [
    {"gamePk": 849845, "gameType": "F",
     "status": {"abstractGameState": "Final"},
     "teams": {"away": {"team": {"id": 143, "name": "Philadelphia Phillies"}, "score": 3},
               "home": {"team": {"id": 144, "name": "Atlanta Braves"}, "score": 2}}},
]}]}

stub = StubRequests(lambda url, params: POSTSEASON_FINAL)
undo = swap(weekly_retrain, "requests", stub)
try:
    games = weekly_retrain.get_last_week_games()
finally:
    undo()
sent = [c["params"].get("gameTypes") for c in stub.calls]
assert all(s == "R" for s in sent), (
    f"training ingest must ask for regular season only, sent {set(sent)}")

print("All postseason data tests pass.")

# ── 7. opening lines are per-game, with no bare-key fallback ───────────────
from check_results import lookup_opening

SAVED = {
    # the date-less legacy key (April price) that used to satisfy every lookup
    "Philadelphia Phillies@Atlanta Braves": {
        "odds": {"Atlanta Braves": {"draftkings": -143}}},
    "2026-09-30|Philadelphia Phillies@Atlanta Braves": {
        "odds": {"Atlanta Braves": {"draftkings": -103}}},
    "2026-09-29|Philadelphia Phillies@Atlanta Braves": {
        "odds": {"Atlanta Braves": {"draftkings": -118}}},
    "2026-09-30|Chicago Cubs@San Diego Padres#2": {
        "odds": {"San Diego Padres": {"draftkings": 120}}},
}

o30, _ = lookup_opening(SAVED, "2026-09-30", "Philadelphia Phillies",
                        "Atlanta Braves", "Atlanta Braves")
o29, _ = lookup_opening(SAVED, "2026-09-29", "Philadelphia Phillies",
                        "Atlanta Braves", "Atlanta Braves")
assert o30 == -103 and o29 == -118, (
    f"consecutive games of one series must get their own openings, got "
    f"{o29} and {o30}")
assert o30 != o29, "two games of a series shared one opening line"

missing, _ = lookup_opening(SAVED, "2026-10-01", "Philadelphia Phillies",
                            "Atlanta Braves", "Atlanta Braves")
assert missing is None, (
    f"fell back to the date-less legacy key and invented an opening: {missing}")

dh2, _ = lookup_opening(SAVED, "2026-09-30", "Chicago Cubs",
                        "San Diego Padres", "San Diego Padres", 2)
assert dh2 == 120, f"doubleheader game 2 opening not resolved: {dh2}"

# ── 8. the picks writer refuses to drop a texted row ──────────────────────
import master_v2

with tempfile.TemporaryDirectory() as tmp:
    try:
        os.chdir(tmp)
        cols = master_v2.PICK_COLUMNS
        def row_for(away, home):
            r = {c: "" for c in cols}
            r.update({"Date": "2026-09-30", "Away": away, "Home": home,
                      "Game#": "1", "Flag": "** BET **"})
            return [r[c] for c in cols]
        keep = row_for("Philadelphia Phillies", "Atlanta Braves")
        drop = row_for("Chicago Cubs", "San Diego Padres")
        with open("picks_2026-09-30.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerow(keep)
            w.writerow(drop)
        with open("notified_2026-09-30.json", "w") as f:
            json.dump(["Philadelphia Phillies@Atlanta Braves",
                       "Chicago Cubs@San Diego Padres", "_heartbeat"], f)
        before = open("picks_2026-09-30.csv", "rb").read()
        raised = False
        try:
            # the Cubs game has vanished from this run's schedule response
            master_v2.save_picks_to_csv([list(keep)], "2026-09-30")
        except RuntimeError:
            raised = True
        assert raised, "writer accepted a run that dropped a texted play's row"
        assert open("picks_2026-09-30.csv", "rb").read() == before, (
            "picks file was modified despite the refusal")

        # the normal case still writes
        master_v2.save_picks_to_csv([list(keep), list(drop)], "2026-09-30")
        rows = list(csv.DictReader(open("picks_2026-09-30.csv", encoding="utf-8-sig")))
        assert len(rows) == 2, f"normal write broke: {len(rows)} rows"
    finally:
        os.chdir(cwd)

print("All postseason data tests pass (incl. openings + writer guard).")
