"""
props_retrain.py — WEEKLY PROPS RETRAIN (owner request 2026-08-19).

The main model retrains weekly; the prop watches (K, Hit, Long Ball) did
not - their parameters were fit once (May-Jun) and hardcoded, so a model
drifting (e.g. K totals running high or low) had no way to correct. This
closes the loop:

  1. refresh each backtest's data (boxscores / priors / Statcast)
  2. refit on a ROLLING window: fit = season start .. today-21d,
     holdout = the last 3 weeks  (PROPS_HOLDOUT_START env)
  3. k_backtest / hit_backtest write k_bt_params.json / hit_bt_params.json,
     which k_model / hit_model now READ at import -> production picks up
     the refit the next morning. hr_backtest refreshes and reports (its
     priors are owner-chosen; it writes eval only).
  4. append a line to props_retrain_log.csv, commit + push params/evals.

Interpreters: K and Hit under the shared 3.11 (statsapi only);
hr_backtest_data needs pybaseball -> Model venv python (never pip-install
into the shared interpreter). Each step is isolated: one failure never
blocks the others.

Scheduled: BaseballPropsRetrain, Thursdays 6:15 AM (before the 8:00 report).
Run manually:  py -3.11 .\props_retrain.py
"""

import csv
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

REPO = r"C:\Users\Poons\baseball-model"
PY311 = r"C:\Users\Poons\AppData\Local\Python\pythoncore-3.11-64\python.exe"
PYVENV = r"C:\Users\Poons\Model\.venv\Scripts\python.exe"
HOLDOUT_DAYS = 21
LOG = "props_retrain_log.csv"


def run(label, args, py=PY311, timeout=3600, env=None):
    t0 = time.time()
    try:
        r = subprocess.run([py] + args, cwd=REPO, env=env, timeout=timeout,
                           capture_output=True, text=True, errors="replace")
        ok = r.returncode == 0
        tail = (r.stdout or "").strip().splitlines()[-6:]
        print(f"[{label}] {'ok' if ok else 'FAILED rc='+str(r.returncode)} in {time.time()-t0:.0f}s")
        for ln in tail:
            print("   ", ln)
        if not ok:
            print("   stderr:", (r.stderr or "").strip()[-600:])
        return ok, "\n".join(tail)
    except Exception as e:
        print(f"[{label}] EXCEPTION {e}")
        return False, str(e)


def main():
    os.chdir(REPO)
    holdout = (date.today() - timedelta(days=HOLDOUT_DAYS)).isoformat()
    env = dict(os.environ, PROPS_HOLDOUT_START=holdout)
    print(f"props retrain {datetime.now():%Y-%m-%d %H:%M} | rolling holdout from {holdout}")

    results = {}
    # K WATCH
    ok1, _ = run("k data", ["k_backtest_data.py"], env=env)
    ok2, tail = run("k backtest", ["k_backtest.py"], env=env) if ok1 else (False, "data step failed")
    results["k"] = (ok1 and ok2, tail)
    # HIT WATCH
    ok1, _ = run("hit data", ["hit_backtest_data.py"], env=env)
    ok2, tail = run("hit backtest", ["hit_backtest.py"], env=env) if ok1 else (False, "data step failed")
    results["hit"] = (ok1 and ok2, tail)
    # LONG BALL (Statcast pull needs the Model venv)
    ok1, _ = run("hr data", ["hr_backtest_data.py"], py=PYVENV, env=env)
    ok2, tail = run("hr backtest", ["hr_backtest.py"], env=env) if ok1 else (False, "data step failed")
    results["hr"] = (ok1 and ok2, tail)

    # log
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "holdout_start", "k_ok", "hit_ok", "hr_ok"])
        w.writerow([date.today().isoformat(), holdout,
                    int(results["k"][0]), int(results["hit"][0]), int(results["hr"][0])])

    # push refit params + evals so the morning build (and the board) pick them up
    try:
        files = ["k_bt_params.json", "k_bt_eval.csv", "hit_bt_params.json", "hit_bt_eval.csv",
                 "hr_bt_eval.csv", LOG]
        subprocess.run(["git", "add"] + [f for f in files if os.path.exists(f)], cwd=REPO, timeout=60)
        subprocess.run(["git", "commit", "-m", f"props retrain {date.today()} (holdout from {holdout})"],
                       cwd=REPO, timeout=60)
        subprocess.run(["git", "push"], cwd=REPO, timeout=180)
    except Exception as e:
        print(f"git push failed: {e}")

    print("summary:", {k: ("ok" if v[0] else "FAILED") for k, v in results.items()})
    return results


if __name__ == "__main__":
    main()
