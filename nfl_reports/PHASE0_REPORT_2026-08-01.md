# Phase 0 Report — Data, Harness, Baseline

**Date:** 2026-08-01 (revised same day after a self-audit found two bugs — see below)
**Status:** Phase 0 complete. No model is deployed. Nothing is texted. Nothing is bet.

---

## Headline

**The baseline does not beat the closing spread, and I am not claiming it does.**

Walk-forward on 2022–2025 (1,058 graded regular-season games):

| model | ATS % | 95% CI | vs 52.38% breakeven |
|---|---|---|---|
| TOTAL (EPA only, no market) | 50.38% | [47.4, 53.4] | p = 0.91 |
| COMBO_TOTAL (market + EPA) | 50.85% | [47.8, 53.9] | p = 0.85 |

Both intervals straddle breakeven. No evidence of an edge. This is the expected
Phase 0 result and matches the handoff's prediction: NFL sides are the sharpest
market in sports.

## Self-audit: two bugs found and fixed after the first draft

The first version of this report was **wrong**. A review pass found two real defects.
Neither changed the headline conclusion, but both materially changed the model.

### BUG 1 — inverted defensive sign (LEAK-003). Serious.

`def_epa` is EPA *allowed* by a defense, so **high = bad defense**. Every strength
feature subtracted the opponent's defensive rating when it should have added it. The
defensive half of the model was pointing backwards.

It hid well: the broken feature still correlated *positively* with margin (+0.147),
and "weak signal against a sharp market" is exactly what you expect to see anyway.

What the fix changed:

| | broken | fixed |
|---|---|---|
| corr(epa_edge, margin) | +0.147 | **+0.374** |
| corr(epa_edge, closing line) | +0.280 | **+0.839** |
| standalone MAE | 10.553 | **9.941** |
| standalone Brier | 0.2434 | **0.2232** |
| per-season ATS spread | 47.5 / 52.7 / **57.5** / 49.1 | 50.6 / 47.7 / 53.4 / 51.7 |

The market-correlation figure is the diagnostic that should have caught it
immediately: a real power rating tracks the closing line at ~0.84, not ~0.28.

Note the per-season column. The broken model produced a **57.5% season** — the single
most seductive number in the whole project, and pure noise from a crippled feature.
The corrected model is boring and stable, which is what real signal looks like.

### BUG 2 — collinear feature set (LEAK-004). Cosmetic but corrosive.

`epa_edge` is 98.3% explained by `pass_edge` + `rush_edge` (R² = 0.983, VIF 58 and
43). Feeding all three in split one signal across three unstable coefficients:

```
epa_edge   -11.5233      <- before
pass_edge   +5.0789
rush_edge   +9.9031
```

Six variants were then compared out-of-sample. They all landed within 0.03 MAE of
each other — multicollinearity destabilises *coefficients*, not predictions — so
parsimony decided (Constitution #11). `epa_edge` alone is now the model:

```
market_margin  +1.0314   <- market taken at ~full face value
epa_edge       +0.5497   <- readable: ~0.55 pts of margin per unit of EPA edge
rest_diff      +0.0208
div_game       -0.3701
is_neutral     +0.9161
```

A regression test suite (`test_features.py`) now asserts the direction of every
relationship, so a sign flip fails loudly instead of quietly halving the model.

## What was built

| file | what |
|---|---|
| `nflverse_data.py` | loaders + parquet cache for pbp, schedules, depth charts, injuries |
| `build_features.py` | team-game EPA → sequential pregame ratings → per-game model table |
| `walkforward.py` | the harness, six model variants, significance testing |
| `test_leakage.py` | 4 leakage tests |
| `test_features.py` | 10 sign-convention / direction tests |
| `scipy_shim.py` | normal CDF/PPF so the venv stays at four dependencies |
| `changelog.json`, `leaks.json` | subscriber-safe logs, MLB schema |

**Data:** 3,028 games and 532,376 plays, 2015–2025. The 2025 season is complete
through the Super Bowl (SEA 29, NE 13, 2026-02-08), so it is a fully usable test year.

## The harness (Constitution #1)

For test season S and week W, training data is every completed game with
`season < S` or `season == S and week < W`. The model refits at **every week
boundary** — 4 seasons × ~18 weeks = 72 independent refits. Ratings are built by a
single sequential pass in kickoff order: read the rating, write the row, *then*
update with the result. A game cannot see itself or any later game.

### Leakage tests — all passing

1. **Truncation invariance** (the strong one): ratings for 2015–2022 games are
   bit-for-bit identical whether or not 2023–2025 exists in the input.
   Max absolute difference across all rating columns: `0.000e+00`.
2. **Cold start**: every team's first-ever rated game sits exactly at the anchor.
3. **Games-played counter**: resets each season, never exceeds weeks elapsed.
4. **Manual recomputation**: KC's rating over 206 games hand-rolled from prior games
   only — 0 mismatches.

Test 1 caught a real leak while being written (LEAK-002).

## Detailed results

### 1. Margin accuracy (lower better)

| model | MAE | RMSE |
|---|---|---|
| SPLIT (pass+rush) | 9.952 | 12.830 |
| FEATURES (all three) | 9.941 | 12.822 |
| TOTAL (epa only) | 9.921 | 12.823 |
| MARKET | 9.505 | 12.369 |
| COMBO_TOTAL | 9.507 | 12.383 |
| **raw closing line** | **9.494** | **12.360** |

The raw closing line still beats everything, including models *fitted on top of it*.
COMBO_TOTAL is **-0.013 MAE worse** than just reading the line off the board.

### 2. Per-season ATS (COMBO_TOTAL)

| season | n | ATS | 95% CI |
|---|---|---|---|
| 2022 | 261 | 50.57% | [44.5, 56.6] |
| 2023 | 258 | 47.67% | [41.7, 53.8] |
| 2024 | 268 | 53.36% | [47.4, 59.2] |
| 2025 | 271 | 51.66% | [45.7, 57.5] |

### 3. Win-probability calibration (Brier, lower better)

| | Brier |
|---|---|
| TOTAL | 0.2232 |
| COMBO_TOTAL | 0.2109 |
| MARKET | 0.2106 |
| **market de-vig** | **0.2105** |
| coin flip | 0.2500 |

The de-vigged market remains the best probability estimate available. The model does
not improve on it — but the corrected standalone model (0.2232) is now much closer to
the market than the broken one was (0.2434).

---

## Caveats that limit every number above

1. **The closing line is unverified.** `spread_line` comes from Lee Sharpe's
   `games.csv` — a third party's record, not a snapshot we took. Constitution #9
   requires true pre-kickoff snapshots. **No CLV claim has been made and none can be**
   until this is verified against the odds API historical endpoint. It is also not
   confirmed whether the field is a true closing or a late line.
2. **No QB feature exists yet.** The handoff is explicit that a model without QB
   status is dead on arrival, and this baseline has none.
3. **Push probability is approximated.** Cover probability uses a continuous normal,
   understating push mass at key numbers 3 and 7. Pushes (29 of 1,087) are excluded
   from ATS rather than modelled.
4. **Totals are untouched.** Only sides were modelled.
5. **1,058 games is four seasons.** Error bars stay wide for a long time here.

## Recommended Phase 1 order

1. **Verify the closing line first.** ~500–1,000 odds-API credits on a random
   ~100-game subsample versus `spread_line`. Every downstream CLV number depends on
   it, and the MLB project lost months to fake closing lines. Do this before modelling.
2. **Add QB availability.** Depth charts and injuries are already cached. Single
   largest known omission.
3. **Model the margin distribution discretely**, with mass on key numbers.
4. **Then** add features one at a time, each required to beat the baseline
   out-of-sample before inclusion (Constitution #11).

Realistic expectation for Phase 1: **calibrated probabilities and positive CLV on
paper**, not a winning ATS record.

## One open question for you

The handoff says to ask once: **NFL picks on the shared ntfy topic
`poons-mlb-picks-k7d24q` with an `[NFL]` prefix, or a separate `poons-nfl-...`
topic?** Not needed until Phase 2, but it decides how the shadow season is wired.
