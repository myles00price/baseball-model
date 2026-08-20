# K WATCH — notes (shipped 2026-08-17)

Strikeout-prop distribution for every probable starter, display-only, self-grading.
Built beside the main model; touches nothing that decides or texts official plays.

## Files

| file | role |
|---|---|
| `k_model.py` | morning build → `k_watch_{date}.json` (board), `k_log_{date}.csv` (frozen training log), `k_batters_{date}.csv` (frozen batter K rates); `--refresh` → lineup-aware JSON rewrite + `k_lock_{date}.csv` (first-confirmed-lineup snapshot per starter, pre-game only) |
| `k_grade.py` | nightly: boxscore K totals joined to log + lock rows → `k_training_data.csv` (idempotent by date+pitcher+pk) and `k_summary.json` (board footer) |
| `k_backtest_data.py` | refreshes the boxscore dump (`hit_bt_*.csv`, shared with the hit watch) and pulls 2025 / career-through-2025 K rates → `k_bt_priors.csv` |
| `k_backtest.py` | walk-forward backtest → `k_bt_eval.csv`, `k_bt_params.json` |
| `board.html` | K WATCH section + `INFO.kwatch` |
| hooks | `morning_report.py` (build, subprocess, try/except), `notify_pick.py` (`--refresh` next to the HR/HIT refresh, display-only, git add), `daily_results_notify.py` (`k_grade.run()`) |

## Method (all point-in-time)

1. **Per-PA K probability** — log-odds combination:
   `logit(p_i) = logit(p_pit) + logit(p_bat_i) − logit(lg)`
   - `p_pit` = 2026 K/BF shrunk **200 BF** toward the pitcher's **2025 rate** (itself shrunk 200 BF toward league); league if no 2025.
   - `p_bat_i` = each lineup batter's 2026 K/PA shrunk **60 PA** toward league.
   - `pK` = mean over the nine (log-odds mean). Morning: opponent's **previous game's lineup**; refresh: **confirmed lineup**; fallback: team K% (300-PA prior).
2. **Expected BF** = 0.75 × mean BF of last 5 starts + 0.25 × season mean BF/start (season mean shrunk 3 starts toward league 21.9). Source: `pen_usage.csv` (game-log API fallback).
3. **Distribution** = mixture over BF = round(exp_bf) + r, r from the empirical residual table (fit window), of BetaBinomial(BF, pK·κ, (1−pK)·κ) with κ = 200 → P(K ≥ n) for every n → fair American odds per half-line.
4. **Pricing** — per book, per line (main + alternates): edge = model P(side) − de-vigged implied (raw implied when only one side is posted → alt-line edges are understated). "Best" = max edge over sides/books/lines; sorts the board.

## Backtest (k_backtest.py, 2026-08-16)

2,575 starts 2026-05-01..08-15 (pitcher ≥ 60 prior BF), fit May–Jun (1,490) / holdout Jul–Aug 15 (1,085). Every parameter chosen on the fit window; numbers below are holdout.

| variant | mean Brier×1000 (lines 3.5–8.5) | Brier at line nearest model median | MAE of E[K] |
|---|---|---|---|
| naive: league mean Poisson | 183.4 | 250.3 | 2.06 |
| naive: pitcher's season K/start Poisson | 164.7 | 245.9 | 1.89 |
| pitcher only (no lineup term) | 163.2 | 247.1 | — |
| **shipped** (2025-anchored pitcher, lineup, BF blend, mixture κ=200) | **160.0** | **235.6** | **1.82** |

Calibration (holdout): P(over 4.5/5.5/6.5) buckets within ~3 pts where n ≥ 40; far tails (n < 30) run hot. Predicted vs actual mean K by octile tracks within 0.4 K. Residual under-dispersion ~5% (MSE 5.12 vs mean predictive variance 4.89) — κ=200 helps only marginally.

**Kept:** 2025-anchored pitcher prior (200 BF; fit Brier 157.8 vs 158.4 for league target); lineup term at ×1 (×0.5 and ×1.5 both worse); recent-start BF blend (0.75/5 chosen on fit; 0.5/8 was 159.1 on holdout — within noise); mixture + β-binomial (log score 2.2048 vs 2.2086 binomial).

**Rejected (holdout):** batter K% split by pitcher hand (160.6); 2025 batter prior (160.3, no gain); lineup-OBP tilt on expected BF (160.0–160.2, and worse BF MAE); recency last-5-start K% blend (160.3 / 161.1 — fails again, as it has three times before in this repo); career-through-2025 anchor (160.4–162.6; not better even on the <150-BF small-sample subset, n=94); team K% as the morning input (as good on fixed lines, worse at the book-style line — previous lineup wins).

**Not tested (no data / not spent):** umpire K tendencies, weather, park K factors, catcher framing, velocity trend. Historical odds (10 credits/snapshot) not spent — market comparison begins with the live log.

## Regimes and grading

- Morning log is the frozen dataset (never rebuilt after first pitch; `--refresh` skips a full build once any game is underway).
- Lock rows: written once per starter the first refresh in which the opposing lineup is posted **and** the game is still Preview; carry the last-fetched prices (odds refetched at most every 3h). Late probable changes are built fresh in refresh (his own game hasn't started) and appear only in the lock file (`src=lock-only`); scratched morning probables grade as `started=0`.
- `k_summary.json`: n graded starts, MAE, mean pred vs actual, calibration by P(over consensus line) bucket, and the paper W-L / ROI of the best-edge side at logged price — morning and lock separately, and by edge bucket (0-3 / 3-6 / 6-10 / 10+ pts).

## Credits per day

Odds API: 2 credits per game per fetch (two market keys) → ~30 in the morning + one refetch per 3h window during lineup-lock runs (~2–3 more) ≈ **90–120/day** at a 15-game slate. Everything else is free statsapi.

## Rules

Display only. No texts to the subscriber topic, ever. Any bet flag would have to be earned by the graded archive beating the market on paper — same bar as F5.

## Loss autopsy (2026-08-19, after the text pull)

82 graded starts decomposed into workload error (BF) x rate error (K/BF), then
49 starts joined to pitch-by-pitch Statcast (whiff/called/foul/zone/velo).

- Misses live in the RATE, not the workload: |rate err| 1.71 K vs |BF err| 0.60 K.
  Both biases ~0. The exp-BF model is genuinely good.
- The rate-error component (1.71 K) sits AT the binomial noise floor of a single
  start (+-1.81 K at ~22 BF, pK~.20). Total MAE 1.78 vs the book's line MAE 1.76.
  Both the model and the books are already at the floor; there is no missing
  variable with room to matter at the single-start level.
- W vs L on the paper leans: identical edges (+.086/+.085), mirror-image rate
  errors (-.036/+.035) - the statistical signature of variance, not bias.
- Pitch level: losses show NO pre-game footprint. Velo-vs-season W -0.01 / L +0.15,
  called-strike%, zone%, fouls, pitch counts all identical. The miss correlates
  with the night's whiff rate (r=+.57) - which correlates with pre-game velo delta
  at only r=+.09. The thing that decides these bets is not predictable pre-game.
- One structural weak corner: OVER leans went 8-16 (33%) while unders went 24-20;
  mean projected 4.44 vs actual 4.27 (model a shade high), and books shade lines
  toward overs. n=24 - logged for the weekly retrain to keep correcting, not
  worth a post-hoc rule.

Verdict: variance on top of a no-edge tie, NOT missing data. Any future K edge
must come from price (stale lines, best-price shopping at extremes), not from
out-predicting the total. Display-only stands.
