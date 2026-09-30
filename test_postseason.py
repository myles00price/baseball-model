"""Acceptance tests for postseason schedule handling in the props models.

Run:  py -3.11 .\test_postseason.py
Origin: 2026-09-29 audit — the first Wild Card day. hr_model, hit_model and
k_model filtered every schedule fetch to gameTypes="R", so on 9/29 they saw
ZERO games: no HR/hit/K boards for the whole postseason, and slate_started()
returned False while games were live, which defeated the frozen-log guard
(a late rebuild would have archived live-updated season stats as pre-game).

No network: a stub session replays a captured statsapi postseason payload and
records the params each call sends.
"""

import hr_model, hit_model, k_model

MODELS = (("hr_model", hr_model), ("hit_model", hit_model), ("k_model", k_model))

# statsapi codes: F=wild card, D=division, L=championship, W=World Series
POSTSEASON_CODES = ("F", "D", "L", "W")

# Real shape of 2026-09-29 (Wild Card game 1): three finals, one live.
WILD_CARD_DAY = {
    "dates": [{"date": "2026-09-29", "games": [
        {"gamePk": 849845, "gameType": "F", "gameDate": "2026-09-29T18:00:00Z",
         "status": {"abstractGameState": "Final", "codedGameState": "F"},
         "teams": {"away": {"team": {"id": 143, "name": "Philadelphia Phillies"},
                            "probablePitcher": {"id": 1, "fullName": "Starter A"}},
                   "home": {"team": {"id": 144, "name": "Atlanta Braves"},
                            "probablePitcher": {"id": 2, "fullName": "Starter B"}}}},
        {"gamePk": 849843, "gameType": "F", "gameDate": "2026-09-30T02:00:00Z",
         "status": {"abstractGameState": "Live", "codedGameState": "I"},
         "teams": {"away": {"team": {"id": 112, "name": "Chicago Cubs"},
                            "probablePitcher": {"id": 3, "fullName": "Starter C"}},
                   "home": {"team": {"id": 135, "name": "San Diego Padres"},
                            "probablePitcher": {"id": 4, "fullName": "Starter D"}}}},
    ]}]
}

PREGAME_DAY = {
    "dates": [{"date": "2026-09-30", "games": [
        {"gamePk": 849841, "gameType": "F", "gameDate": "2026-09-30T18:00:00Z",
         "status": {"abstractGameState": "Preview", "codedGameState": "S"},
         "teams": {"away": {"team": {"id": 143, "name": "Philadelphia Phillies"},
                            "probablePitcher": {"id": 5, "fullName": "Starter E"}},
                   "home": {"team": {"id": 144, "name": "Atlanta Braves"},
                            "probablePitcher": {"id": 6, "fullName": "Starter F"}}}},
    ]}]
}


class StubResponse:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self._payload


class StubSession:
    """Replays one payload and records every request's params."""
    def __init__(self, payload):
        self.payload = payload
        self.calls = []
    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params or {}})
        return StubResponse(self.payload)


# ── 1. every schedule fetch must admit postseason game types ──────────────
for name, mod in MODELS:
    assert hasattr(mod, "SCHEDULE_GAME_TYPES"), f"{name}: no SCHEDULE_GAME_TYPES constant"
    codes = [c.strip() for c in mod.SCHEDULE_GAME_TYPES.split(",")]
    assert "R" in codes, f"{name}: regular season dropped from {codes}"
    for code in POSTSEASON_CODES:
        assert code in codes, f"{name}: postseason type {code!r} missing from {codes}"

# ── 2. the params actually sent carry those types (not a stale literal) ────
for name, mod in MODELS:
    session = StubSession(PREGAME_DAY)
    mod.fetch_schedule(session, "2026-09-30")
    sent = session.calls[0]["params"].get("gameTypes", "")
    assert sent == mod.SCHEDULE_GAME_TYPES, f"{name}: fetch_schedule sent gameTypes={sent!r}"
    for code in POSTSEASON_CODES:
        assert code in sent, f"{name}: fetch_schedule filtered out {code!r}"

# ── 3. a postseason slate parses into games (was silently empty) ───────────
for name, mod in MODELS:
    games = mod.fetch_schedule(StubSession(PREGAME_DAY), "2026-09-30")
    assert len(games) == 1, f"{name}: postseason slate parsed to {len(games)} games, expected 1"

# ── 4. frozen-log guard: live/final postseason games mean STARTED ──────────
for name, mod in MODELS:
    session = StubSession(WILD_CARD_DAY)
    assert mod.slate_started(session, "2026-09-29") is True, (
        f"{name}: slate_started() said not-started on a postseason day with a "
        f"final and a live game - the frozen-log guard would be inert")
    sent = session.calls[0]["params"].get("gameTypes", "")
    for code in POSTSEASON_CODES:
        assert code in sent, f"{name}: slate_started filtered out {code!r}"

# ── 5. all-Preview postseason day is NOT started (pre-game builds allowed) ─
for name, mod in MODELS:
    assert mod.slate_started(StubSession(PREGAME_DAY), "2026-09-30") is False, (
        f"{name}: slate_started() said started on an all-Preview day - "
        f"pre-game log builds would be refused")

# ── 6. unreachable schedule still fails closed (no leaky rebuild) ──────────
class ExplodingSession:
    def get(self, *a, **k):
        raise RuntimeError("statsapi unreachable")

for name, mod in MODELS:
    assert mod.slate_started(ExplodingSession(), "2026-09-29") is True, (
        f"{name}: slate_started() must fail closed when the schedule is unreachable")

print("All postseason schedule tests pass.")
