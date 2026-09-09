# Props Pivot — Engine Port + First Walk-Forward Backtest

**Date:** 2026-08-06
**Status:** Props are now the product. Nothing is texted. Nothing is bet.

## Why the pivot is defensible

Four seasons of walk-forward evidence in this repo say NFL sides offer us no edge
(50.9% ATS, CI straddling breakeven, nothing adds to the closing line). Props are
the opposite market: hundreds of lines per week, wide vig, slower to move, and
books limit winners — the classic signature of a soft market. The skill that props
reward — projecting *usage* faster than lines adjust — is exactly what the engine
Myles built optimizes for. This is a rational reallocation, not a chase.

## What was built

- **`props_engine.html`** — Myles's tool, checked into the repo as the reference
  implementation. Usage-first: environment → shares → shrunk efficiency → opponent
  adjustment → identity enforcement, with OUT-redistribution and logged overrides.
- **`props_model.py`** — faithful Python port (K_TGT=120, K_CAR=150, OPPW=0.5,
  caps QB2/RB4/WR5/TE3, identities enforced). Walk-forward by construction.
- **`props_backtest.py`** — projects week W of 2025 from weeks < W only, grades vs
  actual box scores against a naive per-game-average baseline.
- **`seed_props_data.py`** — regenerates `model_data.json` from nflverse for any
  (season, week); drop it on the HTML tool to refresh all 32 teams in-season.
  Cross-check: Hurts nAtt/comp/ypa match the tool's embedded seed exactly.

## Backtest: 2025, weeks 2–18, graded only when the player actually played

| market | n | engine MAE | naive MAE | delta | engine bias | corr |
|---|---|---|---|---|---|---|
| receptions | 1,675 | 1.71 | 1.73 | **−0.03** | −0.56 | 0.44 |
| rec yds | 1,675 | 23.89 | 24.67 | **−0.79** | −7.49 | 0.44 |
| rush yds | 608 | 27.57 | 27.18 | +0.40 | **−14.69** | 0.36 |
| pass yds | 373 | 59.97 | 59.19 | +0.78 | +11.42 | **0.14** |

Reading it honestly:

1. **The engine's structure earns its keep on receiving markets** — the identity
   enforcement + opponent adjustment beat the naive baseline on both receptions
   and receiving yards. Small margins, but consistent across 17 weeks.
2. **Rush yards has a systematic bug-sized bias**: lead backs are under-projected
   by ~15 yards. Most likely causes: environment plays estimate too low, and/or
   game-script correlation (teams that win run more than their season-average
   share). Needs a dedicated fix before anything else.
3. **QB pass yards are near-noise week to week** (corr 0.14) — for everyone, not
   just us; this is why pass-yardage props carry the widest vig. Deprioritize.
4. Selection note: grading only players who played approximates knowing inactives
   at lock, which a real workflow does. Late scratches the model couldn't know
   about are not in these numbers.

## Known divergences from the HTML tool (documented, intentional)

- Season blend is sample-weighted (n/(n+4)) instead of static 0.75/0.25, so the
  port works at any mid-season week.
- Scrambles: weekly data folds them into QB carries, so the port treats them as
  runs. The tool counts them as pass plays. PHI pass rate: port 0.51 vs tool 0.60.
  Self-consistent either way; don't mix numbers between the two.
- No end-zone / inside-5 TD tilts yet (need pbp fields). TD markets aren't being
  evaluated, so this doesn't touch the table above.

## What it costs to test against real prop lines (the decision pending)

Historical player-prop odds from the odds API are priced **per market per event**:
~10 credits × 16 games × 4 markets ≈ **640 credits per week-slate**, one snapshot.
A 4-week pilot ≈ 2,600 credits against the 20k/month budget (19,654 remaining,
MLB still running). That pilot — engine projections vs actual posted lines, hit
rates de-vig — is the real test of whether a props edge exists. Backtesting vs
box scores (free, done above) had to come first: a projection that can't beat a
per-game average has no business being compared to a market.

## Next steps, in order

1. Fix the rush-yards bias (environment plays + game-script share adjustment).
2. Add pbp-derived fields to the seeder (adot, EZ/RZ targets, inside-5, snap%) —
   completes the HTML tool's data and enables the TD tilts.
3. Decide on the 4-week prop-lines pilot (~2,600 credits) once 1–2 are done.
4. Shadow-season plumbing (Phase 2 discipline unchanged): lock-time snapshots of
   prop lines, texted paper picks, grading, CLV.
