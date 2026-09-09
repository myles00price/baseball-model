# Phase 1 Report — Closing-Line Verification, Feature Rebuild, Model Tournament

**Date:** 2026-08-01
**Status:** Phase 1 modelling groundwork. Nothing is texted. Nothing is bet.

---

## 1. The closing line is VERIFIED ✔

The single most important result of this session, because every backtest number in
the project leans on it.

**Method.** 24 historical snapshots from the odds API, each taken at kickoff minus
2 minutes (true pre-kickoff, per Constitution #9), covering 159 games across
2023–2025 — main Sunday slates plus primetime singles. Each response filtered by
commence time (the handoff's team-name-mixing warning is enforced in code). Compared
the median home spread across ~11–15 books against `spread_line` in games.csv.

**Result.**

| | |
|---|---|
| games matched | 159 / 159 |
| exact match | 66.0% |
| within 0.5 pt | 94.3% |
| within 1.0 pt | 98.1% |
| mean abs diff | 0.208 pts |
| mean signed diff (bias) | −0.10 pts |
| max abs diff | 2.5 pts (1 game) |

**Verdict: `spread_line` is a genuine closing line.** The residual differences are
consistent with "one book's close vs the median of all books." Backtesting ATS
against it is sound. Two caveats stand: the live pipeline must still take its own
lock-time and pre-kickoff snapshots (grading and CLV are measured on *our* prices,
not a third party's), and the one 2.5-pt outlier (2025_14_WAS_MIN) looks like a
late-week line move that one source caught and the other didn't — a reminder that
"the close" is a distribution, not a number.

**Cost:** 240 credits. 19,654 remain for the month.

## 2. Feature rebuild

### New team-game metrics (same no-leakage sequential pattern, all tests passing)

| feature | what | corr w/ margin |
|---|---|---|
| `epa_edge` | EPA/play matchup edge (existing) | +0.374 |
| `success_edge` | success-rate matchup edge | +0.340 |
| `pts_edge` | EWMA scoring-margin rating diff | +0.384 |
| `to_edge` | turnover-battle edge (takeaway/giveaway rates) | +0.248 |
| `qb_change_edge` | new-starter flag, home vs away | +0.124 |
| `qb_starts_diff` | starter's career starts with this team, diff | +0.212 |

The QB flag confirms the handoff's claim: home teams with a new starting QB average
**−1.50** margin vs **+2.19** with a stable starter — a ~3.7-point swing.
(Caveat: the flag is derived from the *actual* starter in games.csv, which is only
certain ~90 min pre-kickoff. Fine for closing-line backtests; the live pipeline
needs a real QB-status feed from depth charts/injuries, already cached.)

EWMA hyperparameters (halflife 8, season-carry 0.8) were tuned on **2018–2021
walk-forward only** and frozen before any 2022–2025 evaluation. The sweep surface
was nearly flat (0.13 MAE across the grid) — these knobs barely matter.

### Ablation (Constitution #11): which features earn inclusion?

OLS walk-forward 2022–2025, leave-one-out deltas (positive = feature was helping):

```
epa_edge         -0.0013     redundant IN THE PRESENCE of the rest, but it is
                             the core: alone it is worth -0.79 MAE
success_edge     +0.0229     keep
qb_starts_diff   +0.0471     keep -- largest single contributor after EPA
pts_edge         -0.0064     cut (EPA already knows this)
to_edge          -0.0036     cut (turnovers are noise, as expected)
qb_change_edge   -0.0068     cut (subsumed: a new starter has 0 starts,
                             so qb_starts_diff already encodes the change)
```

**Lean set (kept):** `epa_edge, success_edge, qb_starts_diff, rest_diff, div_game,
is_neutral` — 9.852 MAE, identical to the full 9-feature set (9.855) with three
fewer inputs. Fewer inputs, honest model.

**And the market ablation, which is the real headline:** market alone 9.505; market
plus *everything we have built* 9.525. **No feature we possess adds information to
the closing line.** Every "keep" above is about making our standalone rating better,
not about beating the market.

## 3. Model tournament

Walk-forward 2022–2025, 1,087 REG games, refit every week. Ridge alpha (100) tuned
on 2018–2021 only. Same features for every entrant.

| entrant | MAE | ATS | 95% CI | Brier |
|---|---|---|---|---|
| **ols/+market** | **9.525** | 50.4% | [47.4, 53.4] | 0.2109 |
| ridge/+market | 9.535 | 50.2% | [47.2, 53.2] | 0.2114 |
| rf/+market | 9.677 | 50.1% | [47.1, 53.1] | 0.2138 |
| gbm/+market | 9.784 | 48.7% | [45.7, 51.7] | 0.2167 |
| ridge/no-market | 9.838 | 49.3% | [46.3, 52.3] | 0.2200 |
| rf/no-market | 9.841 | 53.7% | [50.7, 56.7] | 0.2197 |
| ols/no-market | 9.855 | 49.6% | [46.6, 52.6] | 0.2202 |
| gbm/no-market | 9.981 | 52.0% | [49.0, 55.0] | 0.2224 |
| *closing line* | *9.494* | — | — | *0.2105 de-vig* |

**Winner: plain linear regression.** Trees (GBM, RF) are strictly worse on margin
accuracy — with ~2,900 training games and smooth linear-ish relationships, tree
models fit noise. This mirrors the MLB lesson: simple calibrated models win.

**XGBoost addendum** (added same day on request — the library itself, not just the
sklearn equivalent): two configs, same harness.

| entrant | MAE | ATS | Brier |
|---|---|---|---|
| xgb-default/no-market | 10.231 | 51.0% | 0.2285 |
| xgb-shallow/no-market | 9.930 | 49.6% | 0.2208 |
| xgb-default/+market | 9.946 | 49.8% | 0.2205 |
| xgb-shallow/+market | 9.695 | 49.3% | 0.2143 |

Same conclusion, more decisively: the best XGBoost config trails OLS by 0.17 MAE and
the default config is the worst entrant in the tournament. Four tree learners have
now lost to a straight line; the case for linear is closed until the data grows.

**The number that will try to seduce you:** rf/no-market at 53.7% ATS, CI floor
above 50. Reasons it is almost certainly noise, recorded before anyone bets a cent
on it: (1) p = 0.21 against breakeven — not significant; (2) it is the best ATS of
8 entrants, i.e. a selection effect; (3) the same model is *worse* at predicting
actual margins than OLS — a model that predicts worse but "wins" more is lucky, not
good; (4) GBM, the other tree model, shows the same pattern weaker. Verdict:
hypothesis to re-test in the 2026 shadow season, not a finding.

**Win probability:** logistic +market Brier 0.2107 ≈ de-vigged market 0.2105. The
margin-based normal approximation gives the same answer. Nothing beats the market's
probabilities yet.

## 4. Where this leaves the project

| claim | status |
|---|---|
| closing line trustworthy for backtests | **YES — verified** |
| standalone rating quality | improved: 9.94 → 9.84 MAE (best: ridge/no-market) |
| any model type beats linear | **NO** — linear wins, trees overfit |
| any feature adds to the closing line | **NO** |
| edge vs the close demonstrated | **NO** (unchanged) |

The honest summary: the plumbing is now proven (verified lines, leak-tested
features, tuned-then-frozen hyperparameters), the standalone model is respectable
and improving, and the market remains undefeated. That is exactly where a sane NFL
project should be in August.

## 5. Recommended next steps

1. **QB status from depth charts/injuries** (already cached) — replaces the
   actual-starter proxy with a genuinely pregame feature, and enables the one edge
   worth hunting: reacting to QB news at lock time before the line fully adjusts.
2. **Discrete margin distribution** for key numbers 3/7 (push handling; needed for
   real bet logic regardless of edge).
3. **Totals model** — same harness, `total_line` field is presumably as trustworthy
   as the spread but should get the same 1-slate verification (~10 credits).
4. **Shadow-season infrastructure** (Phase 2): lock-time snapshots, pick texting,
   grading — the CLV record is what year one is actually for.

## Session cost

240 odds-API credits (19,654 remain). All other data free.
