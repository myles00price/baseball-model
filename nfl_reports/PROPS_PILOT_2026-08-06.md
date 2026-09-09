# Props Pilot — Engine vs Real Closing Prop Lines

**Date:** 2026-08-06
**Sample:** 4 Sunday main slates of 2025 (weeks 5, 9, 13, 17), lines at kickoff−2min,
median across books. 938 player-market lines matched to walk-forward projections
(OUTs redistributed, calibrated — the post-fix engine).
**Cost:** ~1,610 credits (18,040 remain). Budget approved: 2,600.

## The number

| market | record | hit % | 95% CI | bigger-half edges |
|---|---|---|---|---|
| receptions | 190–163 | **53.8%** | [48.6, 59.0] | **58.2%** |
| rec yds | 186–172 | 52.0% | [46.8, 57.1] | 54.7% |
| rush yds | 90–80 | 52.9% | [45.5, 60.3] | 52.9% |
| pass yds | 24–31 | **43.6%** | [31.4, 56.7] | 50.0% |
| **ALL** | **490–446** | **52.35%** | [49.1, 55.5] | — |

Breakeven at −110 is 52.38%. The overall record lands **exactly on it** — a
coin flip after vig, and the CI is far too wide to claim anything.

## Honest reading

1. **No edge demonstrated, no edge ruled out.** 936 graded picks is one-quarter
   of a season of slates. The CI spans "losing steadily" to "printing money."
2. **Receptions is the live hypothesis.** Best headline rate (53.8%), and the only
   market where bigger disagreements won more (58.2% on the larger half) — the
   monotonicity you'd want if signal exists. Still p = 0.31; a hypothesis, not a
   finding.
3. **Pass yards confirmed dead** for the third time: 43.6% record, engine MAE
   52.5 vs the line's 44.9. Out of the pick universe going forward.
4. **The lines are sharper projections than the engine in every market** (line
   MAE beats engine MAE across the board). Any edge is in the tails of
   disagreement, not in average accuracy — same shape as the MLB experience.
5. One infrastructure bug caught and fixed mid-pilot: hardcoded 17:00Z slate time
   silently missed all post-DST weeks (Nov+ kickoffs are 18:00Z). First run
   "worked" on one slate and returned zero on three. Kickoffs now derived from
   the schedule in ET. Same bug family as the handoff's commence-date warning.

## Addendum (same day): open lines + CLV — Myles's differential test

Myles's point: breakeven at the close implies value at the open. Pulled the same
4 slates at **kickoff−72h** (~1,070 more credits; 16,974 remain). 557 lines had
open + close + actual. Same engine numbers, graded both ways:

| market | vs OPEN | vs CLOSE (same sample) | movers toward engine | mean move |
|---|---|---|---|---|
| receptions | 51.7% | 51.2% | **21/27 = 77.8%** | +0.09 |
| rec yds | 52.6% | 50.9% | 50.5% | +0.23 |
| rush yds | **57.9%** | 55.6% | **57.8%** | +0.10 |
| pass yds | 42.0% | 44.0% | 42.6% | **−1.44** |
| **ALL** | **52.42%** | 51.25% | **53.4%** | — |

What this says, honestly:

1. **The direction is what Myles predicted**: identical picks score ~1.2 points
   better against the open than the close. Not significant alone, but the right
   sign.
2. **The strongest signal in the project so far: receptions line movement.**
   When a receptions line moved between open and close, it moved *toward* the
   engine's number 21 of 27 times (77.8%, raw p ≈ 0.002; ~0.01 after multiplying
   by four markets examined). Receptions lines barely move (27 movers of 172),
   but when they do, they chase our projection. Combined with receptions being
   the best market vs the close (53.8%, monotone in edge size), that is
   convergent evidence — still on one-quarter-season of slates.
3. **Rush yards joins the live list**: 57.9% vs open, 57.8% of movers our way.
4. **Pass yards fails a fourth way**: the market moves AWAY from our number
   (−1.44 mean move). The market corrects toward truth and away from us. Dead
   and buried.
5. Coverage caveat: only ~60% of closing lines existed 72h out (books post props
   at different times), so the open sample is the subset books were willing to
   price early — plausibly the sharper-priced subset.

## Decision recommendation (updated)

Shadow season on **receptions + rush yards + receiving yards**, with picks made
EARLY in the week (the edge decays toward the close — bet timing is part of the
strategy now), lock-on-text, line-CLV tracked as the primary health metric per
Constitution #9. Pass yards is out. The 2026 season provides ~18x this sample
for free. Gate to real money unchanged: half a season of shadow picks clearing
52.4% with positive CLV.
