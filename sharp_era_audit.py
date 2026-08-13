"""Did sharp money get worse after the trade deadline (7/31)?
For every game with a meaningful line move (>=1.5, the veto threshold),
grade the side the market moved TOWARD. Split pre/post deadline.
Also split the veto phantom ledger the same way."""
import csv, re, sys, os
from glob import glob

sys.stdout.reconfigure(errors="replace")
os.chdir(r"C:\Users\Poons\baseball-model")
from features_v2 import is_bet
from master_v2 import bet_side_ok
from check_results import get_game_results

DEADLINE = "2026-07-31"

def f(x):
    m = re.search(r"-?\d+\.?\d*", str(x or ""))
    return float(m.group()) if m else None

def payout(o):
    o = float(o)
    return o if o > 0 else 10000.0 / abs(o)

sharp = {"pre": [0, 0, 0.0], "post": [0, 0, 0.0]}     # sharp-side w, l, pnl@DK
phantom = {"pre": [0, 0, 0.0], "post": [0, 0, 0.0]}   # vetoed would-be bets

for fn in sorted(glob("picks_2026-*.csv")):
    d = fn.replace("picks_", "").replace(".csv", "")
    try:
        R = get_game_results(d)
    except Exception:
        continue
    if not R:
        continue
    era = "pre" if d < DEADLINE else "post"
    for row in csv.DictReader(open(fn, encoding="utf-8-sig")):
        a, h = row.get("Away"), row.get("Home")
        r = R.get(f"{a}@{h}")
        if not r:
            continue
        am, hm = f(row.get("Away Line Move")), f(row.get("Home Line Move"))
        if am is None or hm is None or max(abs(am), abs(hm)) < 1.5:
            continue
        sside = a if am > hm else h
        sodds = f(row.get("DK Away Odds") if sside == a else row.get("DK Home Odds"))
        if sodds is None:
            continue
        won = sside == r["winner"]
        s = sharp[era]
        s[0] += won; s[1] += not won
        s[2] += payout(sodds) if won else -100.0

        # veto phantom split (live era only, same rules as the audit)
        if (d >= "2026-07-17" and "FADE" in str(row.get("Sharp Signal", ""))
                and "BET" not in str(row.get("Flag", "")) and h != "Colorado Rockies"):
            arel, hrel = f(row.get("Away Reliability%")), f(row.get("Home Reliability%"))
            awhf, hwhf = f(row.get("Away SP Whiff")), f(row.get("Home SP Whiff"))
            for side in ("away", "home"):
                e1 = f(row.get("DK Edge Away") if side == "away" else row.get("DK Edge Home"))
                e2 = f(row.get("MGM Edge Away") if side == "away" else row.get("MGM Edge Home"))
                if not ((e1 is not None and is_bet(e1)) or (e2 is not None and is_bet(e2))):
                    continue
                brel, orel, owhf = (arel, hrel, hwhf) if side == "away" else (hrel, arel, awhf)
                if brel is None or orel is None or not bet_side_ok(brel, orel, owhf):
                    continue
                team = a if side == "away" else h
                odds = f(row.get("DK Away Odds") if side == "away" else row.get("DK Home Odds"))
                if odds is None:
                    continue
                pwon = team == r["winner"]
                p = phantom[era]
                p[0] += pwon; p[1] += not pwon
                p[2] += payout(odds) if pwon else -100.0
                break

print(f"SHARP SIDE (team the line moved toward, moves >= 1.5)")
for era in ("pre", "post"):
    w, l, pnl = sharp[era]
    n = w + l
    lab = f"before {DEADLINE}" if era == "pre" else f"after  {DEADLINE}"
    print(f"  {lab}: {w:.0f}-{l:.0f} ({w/n*100 if n else 0:.1f}%)  flat-bet P&L {pnl:+.0f}")
print(f"\nVETOED WOULD-BE BETS (live era)")
for era in ("pre", "post"):
    w, l, pnl = phantom[era]
    lab = f"before {DEADLINE}" if era == "pre" else f"after  {DEADLINE}"
    print(f"  {lab}: {w:.0f}-{l:.0f}  P&L {pnl:+.0f}")
