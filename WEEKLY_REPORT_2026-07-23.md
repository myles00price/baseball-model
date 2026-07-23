# MLB Model — Weekly Performance Report
**Week of July 16–23, 2026 · V2 launch week · Report #1**

---

## 1. Headline

V2 went live July 16. Through Wednesday: **10-4 on official flagged bets, ≈ +$537 at $100 flat (+38% ROI on 14 bets)**, with **+4.4% average CLV** and a **71% closing-line beat rate** in the V2 window. Every leading indicator is above the deploy gate; sample is still far too small to raise stakes.

**Deploy gate progress: 14 / 100 graded official picks (need ≥54% at the gate; currently 71.4%).**

---

## 2. The week's daily record (official flagged plays)

| Day | Overall picks | Official flags | P&L |
|---|---|---|---|
| Wed 7/16 | 1/1 | no flags | — |
| Fri 7/17 | 5/12 | 3-1 | +$211 |
| Sat 7/18 | 7/13 | 0-2 | -$200 |
| Mon 7/20 | 9/14 | 1-0 | +$67 |
| Tue 7/21 | 5/13 | 3-1 | +$198 |
| Wed 7/22 | 8/14 | 3-0 | +$261 |
| **Total** | **35/67 (52.2%)** | **10-4 (71.4%)** | **≈ +$537** |

---

## 3. Season-wide health checks (the always-run reports)

**Calibration (478 graded games, corrected grading):**
- Edge buckets: 0–3% → 53.3% · **3–6% → 57.0%** · 6–10% → 50.0% · 10%+ → 46.2%. The 3–8% bet window remains right where the data says it should be.
- Categories: home favorites **57.8%** (the model's core strength) · home dogs 45.5% (weakness) · away sides ~coin flip.
- MAE 49.5 vs 50.0 baseline. No home/away bias (53.2% vs 49.7%).
- Coors: 8/17 (47.1%) — exclusion stays.

**Tracker (90 season flagged bets, $100 flat):**
- Season P&L is now **positive: +$234 (+2.6%)** — was reported as -$1,425 before Monday's grading-bug fix.
- Sharp FADE bets: 4/15 (26.7%), **-$594** — the FADE veto remains the most valuable single rule.
- Filter scenarios: skip-FADE = +$828 (+11.0%) · skip-FADE-and-ESTIMATED = **55.6%, +$450 (+12.5%)** — the closest proxy to "V2 rules applied all season."
- Sharp signal on all games: sharps 56.9% when agreeing with model, sharps win 57.9% when opposing it.

**CLV (leading indicator, 171 season games):**
- Season: +2.47% avg, 57.9% beat rate. Flagged: **+4.27%**.
- V2 window: **+4.44% avg, 71% beat rate (36/51)** — elite territory; the market keeps moving toward our numbers.

---

## 4. NEW — Team-level analytics (first run this week)

**Best teams when the model picks them (min 8 picks):**
| Team | Record |
|---|---|
| Brewers | 19/24 (79%) |
| Royals | 11/15 (73%) |
| Phillies | 13/18 (72%) |
| Braves | 15/24 (62%) |
| Rays | 11/18 (61%) |

**Worst:**
| Team | Record |
|---|---|
| Diamondbacks | 3/13 (23%) |
| Twins | 4/13 (31%) |
| Orioles | 3/9 (33%) |
| Giants | 5/14 (36%) |
| Marlins | 4/11 (36%) |

**Most-bet teams (flag landed on them):**
- **Cardinals: 4-7** ← the model's biggest leak; it keeps seeing value in STL and keeps losing. Today's slate has another Cardinals lean — watch closely.
- Rays: 5-2 · Giants: 4-2 · Reds: 3-1 · Brewers: 3-1 · Blue Jays: 3-3

Note the distinction: "picked" = model says they win (any price); "bet" = flag landed on them (price-driven). Twins are a *bad pick* team (31%) but have been a *good value-dog bet* — both can be true.

---

## 5. What changed this week (engineering)

1. **Flag-side grading bug found & fixed (Mon):** graders scored value-dog bets on the model's pick side instead of the flagged side. 13 season bets corrected; season P&L swung +$1,273. All four consumers (results, tracker, calibration, notifications) now share one `features_v2` implementation with acceptance tests.
2. **Official vs. lean process formalized:** morning/nightly texts = pre-lineup leans; per-game lineup-locked texts = official plays. Graders only count official flags.
3. **Six-book line shop** added to locked-pick notifications (DK/MGM/FD/CZR/HardRock/Circa, best price called out).
4. **Notification pipeline hardened:** doubleheader key collisions, unresolved-starter crashes, cp1252 emoji crashes — all fixed; full scheduler chain (9 AM check-in → lineup watch → nightly slate + text + push + shutdown) verified end-to-end.
5. **Subscriber list grew to 3** (topic: ntfy). Flat-stakes discipline note included in results texts.

---

## 6. Watch items for next week

- **Cardinals bet leak (4-7).** If STL flags keep failing, consider a team-level review — but no ad-hoc filters; let the sample build first.
- **CONFIRMED-lineup flagged bucket: 43.2%, -$349 season.** Mostly old-model swap-bug era. V2's fix targets exactly this bucket — it should climb; if it doesn't by ~30 V2 confirmed-lineup bets, that's a red flag.
- **Probability clamp sightings:** today's Braves play hit 77.8% (clamp is 78). Clamped outputs mean the model wants to go higher — monitor calibration in the 65%+ bucket.
- **Heavy-favorite bets** (Braves -260): edge is real but payout asymmetry makes variance ugly. Consider whether the window should be price-aware after the 100-pick gate.
- **Small sample discipline:** 14 official picks. Nothing about +38% ROI is sustainable; the honest expectation at a true 54-56% is +5-8% ROI. Flat $100 until 100 picks.

---

*Generated 2026-07-23. Next report: 2026-07-30.*
