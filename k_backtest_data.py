"""k_backtest_data.py — extra inputs for the strikeout backtest.

The per-game K / BF / PA / hand data the K backtest needs already lives in
hit_bt_pitchers.csv / hit_bt_batters.csv / hit_bt_games.csv (built by
hit_backtest_data.py from final boxscores, point-in-time safe). This script
adds the one thing those files can't give: a PRIOR-SEASON rate for every
pitcher and batter seen in 2026, so the shrinkage target can be tested as
"2025 rate" instead of "league average". Writes k_bt_priors.csv:

    id, kind (P|B), so, denom (BF for pitchers, PA for batters), season=2025

Also refreshes the hit_bt_* files through yesterday (resume-safe) so the
backtest sees the whole season to date.

Run:  C:\\Users\\Poons\\Model\\.venv\\Scripts\\python.exe k_backtest_data.py
"""

import csv
import subprocess
import sys

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

API = "https://statsapi.mlb.com/api/v1"
PRIOR_SEASON = 2025
OUT = "k_bt_priors.csv"


def ids_from(fn, col):
    with open(fn, encoding="utf-8") as f:
        return {int(r[col]) for r in csv.DictReader(f)}


def pull(session, ids, group, so_key, den_key, stype="season", season=PRIOR_SEASON):
    out = {}
    ids = sorted(ids)
    for i in range(0, len(ids), 40):
        chunk = ",".join(str(x) for x in ids[i:i + 40])
        hyd = (f"stats(group=[{group}],type=[career])" if stype == "career"
               else f"stats(group=[{group}],type=[season],season={season})")
        try:
            j = session.get(f"{API}/people", params={
                "personIds": chunk, "hydrate": hyd,
            }, timeout=60).json()
        except Exception as e:
            print(f"chunk {i} failed: {e}")
            continue
        for p in j.get("people", []):
            for s in p.get("stats", []):
                if s.get("group", {}).get("displayName") != group:
                    continue
                sp = s.get("splits", [])
                if sp:
                    st = sp[0].get("stat", {})
                    out[p["id"]] = (int(st.get(so_key, 0) or 0), int(st.get(den_key, 0) or 0))
        if (i // 40) % 10 == 0:
            print(f"  {group}: {i}/{len(ids)}", flush=True)
    return out


def main():
    subprocess.run([sys.executable, "hit_backtest_data.py"], timeout=3600)
    session = requests.Session()
    pids = ids_from("hit_bt_pitchers.csv", "pitcher")
    bids = ids_from("hit_bt_batters.csv", "batter")
    print(f"{len(pids)} pitchers, {len(bids)} batters -> {PRIOR_SEASON} priors")
    P = pull(session, pids, "pitching", "strikeOuts", "battersFaced")
    B = pull(session, bids, "hitting", "strikeOuts", "plateAppearances")
    # career THROUGH 2025 = career-to-date minus the 2026 season (both pulled now,
    # so the difference is exactly the pre-2026 record — no leak into the backtest)
    C = pull(session, pids, "pitching", "strikeOuts", "battersFaced", stype="career")
    S = pull(session, pids, "pitching", "strikeOuts", "battersFaced", season=2026)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "kind", "so", "denom", "season"])
        for pid, (so, bf) in sorted(P.items()):
            w.writerow([pid, "P", so, bf, PRIOR_SEASON])
        for bid, (so, pa) in sorted(B.items()):
            w.writerow([bid, "B", so, pa, PRIOR_SEASON])
        nC = 0
        for pid, (so, bf) in sorted(C.items()):
            s26 = S.get(pid, (0, 0))
            so_c, bf_c = so - s26[0], bf - s26[1]
            if bf_c > 0:
                w.writerow([pid, "C", so_c, bf_c, "career-thru-2025"])
                nC += 1
    print(f"wrote {OUT}: {len(P)} pitcher priors, {len(B)} batter priors, {nC} career priors")


if __name__ == "__main__":
    main()
