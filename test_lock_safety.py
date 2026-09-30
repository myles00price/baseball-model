"""Acceptance tests for the two lock-safety guards found by the 2026-09-29
postseason audit.

Run:  py -3.11 .\\test_lock_safety.py

1. notify_pick must never text or lock a game that is already Live/Final.
   Those keys are what every grader treats as proof of a PRE-GAME lock, so a
   late run (the machine booted 2026-09-29 at 21:42 with three Wild Card games
   final) would have made post-hoc plays official at morning prices.

2. The props models must refuse to BUILD a frozen log once the slate is
   underway - log present or not. The old guard read "log exists AND slate
   started", so a missed morning wrote a brand-new log from season stats that
   already contained the day's finished games, and the nightly graders
   archived those rows permanently.

No network: every outbound call is stubbed.
"""

import os
import sys
import tempfile

import notify_pick

# ── shared fixtures ───────────────────────────────────────────────────────
DATE = "2026-09-29"

FINAL_AND_LIVE = [   # real shape of Wild Card game 1 at 21:47 local
    {"away": "Philadelphia Phillies", "home": "Atlanta Braves", "state": "Final",
     "key": "Philadelphia Phillies@Atlanta Braves", "game_no": 1},
    {"away": "Chicago Cubs", "home": "San Diego Padres", "state": "Live",
     "key": "Chicago Cubs@San Diego Padres", "game_no": 1},
]

ALL_PREVIEW = [
    {"away": "Philadelphia Phillies", "home": "Atlanta Braves", "state": "Preview",
     "key": "Philadelphia Phillies@Atlanta Braves", "game_no": 1},
]

def pick_row(away, home):
    return {
        "Away": away, "Home": home, "Model Away%": "53.1", "Model Home%": "46.9",
        "DK Away Odds": "-117", "DK Home Odds": "-103",
        "MGM Away Odds": "-117", "MGM Home Odds": "-103",
        "DK Edge Away": "+4.2% ** BET **", "MGM Edge Away": "+3.9% ** BET **",
        "DK Edge Home": "-5.1%", "MGM Edge Home": "-4.8%",
        "Flag": "** BET **", "Lineup Source": "CONFIRMED+PLATOON",
        "Game#": "1", "GamePk": "849845",
    }


def run_notify(confirmed):
    """Run notify_pick.main() with every side effect captured. Returns
    (pushes, ops_alerts, locked_keys)."""
    pushes, ops, locked = [], [], []
    saved = {k: getattr(notify_pick, k) for k in
             ("get_confirmed_games", "load_picks", "send_push", "send_ops",
              "save_state", "load_state", "fetch_market_odds")}
    import subprocess as _sp
    saved_run = _sp.run
    try:
        notify_pick.get_confirmed_games = lambda d: confirmed
        notify_pick.load_picks = lambda d: {
            g["key"]: pick_row(g["away"], g["home"]) for g in confirmed}
        notify_pick.send_push = lambda title, body, bet: pushes.append(title)
        notify_pick.send_ops = lambda title, body: ops.append(title)
        # heartbeat already sent, so main() goes straight to the lock logic
        notify_pick.load_state = lambda d: {"_heartbeat"}
        notify_pick.save_state = lambda d, n: locked.extend(
            k for k in n if not k.startswith("_") and k not in locked)
        notify_pick.fetch_market_odds = lambda d=None: {}
        _sp.run = lambda *a, **k: _sp.CompletedProcess(a[0] if a else "", 0, "", "")
        try:
            import f5_shadow
            f5_lock = f5_shadow.lock_key
            f5_shadow.lock_key = lambda *a, **k: None
        except Exception:
            f5_lock = None
        notify_pick.main()
    finally:
        for k, v in saved.items():
            setattr(notify_pick, k, v)
        _sp.run = saved_run
        if f5_lock is not None:
            import f5_shadow
            f5_shadow.lock_key = f5_lock
    return pushes, ops, locked


# ── 1. a started game is never texted and never locked ────────────────────
pushes, ops, locked = run_notify(FINAL_AND_LIVE)
assert pushes == [], f"texted a game that was already underway: {pushes}"
assert locked == [], f"wrote official keys for started games: {locked}"
assert ops, "a skipped late run should raise an ops alert on the private topic"

# ── 2. pre-game games still text normally (the guard is not a kill switch) ─
pushes, ops, locked = run_notify(ALL_PREVIEW)
assert len(pushes) == 1, f"expected 1 pre-game text, got {pushes}"
assert locked == ["Philadelphia Phillies@Atlanta Braves"], (
    f"pre-game play should be locked, got {locked}")

# ── 3. the cosmetic 'already started' disclosure is gone ──────────────────
import inspect
assert "started" not in inspect.signature(notify_pick.format_pick).parameters, (
    "format_pick still takes a 'started' flag - a cosmetic line must not look "
    "like a guard")

# ── 4/5. props models refuse to build a log once the slate is underway ─────
import hr_model, hit_model, k_model

for name, mod in (("hr_model", hr_model), ("hit_model", hit_model), ("k_model", k_model)):
    log_name = {"hr_model": f"hr_log_{DATE}.csv",
                "hit_model": f"hit_log_{DATE}.csv",
                "k_model": f"k_log_{DATE}.csv"}[name]
    real_started = mod.slate_started
    real_argv = sys.argv
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            sys.argv = [f"{name}.py", DATE]
            mod.slate_started = lambda session, date: True   # slate underway
            assert not os.path.exists(log_name)
            mod.main()
            assert not os.path.exists(log_name), (
                f"{name}: built {log_name} on a slate that was already "
                f"underway - post-first-pitch stats would be archived as "
                f"pre-game features")
        finally:
            os.chdir(cwd)
            sys.argv = real_argv
            mod.slate_started = real_started

print("All lock-safety tests pass.")
