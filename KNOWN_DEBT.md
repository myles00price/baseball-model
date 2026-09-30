# KNOWN DEBT — 2026-08-27 full-code audit remainders

Items the audit verified but deliberately did NOT change tonight, either
because the honest fix needs a walk-forward test first or because they are
low-impact. Nothing here touches the official record. Re-visit list, in
priority order.

## 1. Training/inference stat mismatch (core #1/#2 — NEEDS A TEST, NOT A HOTFIX)
Inference feeds the model **career-blended** pitcher stats
(`get_blended_pitcher_stats`) and platoon lineup OPS; the 8,663-game training
archive was built on **raw season** stats. The traded-stint half was fixed
tonight (training now uses combined season totals), but the blend half is a
modeling DECISION: align training→blended (rebuild rows) or inference→raw.
**A/B VERDICT (2026-09-12, blend_vs_raw_ab.json; methodology adversarially
audited twice — a v1 career-anchor leak and a v2 traded-season double count
were found, fixed, and shown not to move the result):**

- PROBABILITY ACCURACY: no EVIDENCE of a difference — test underpowered.
  Citable OOS split (n=193, 8/27-9/10): paired Brier delta +0.0012,
  t=+0.37, 95% CI [-0.0054, +0.0079], MDE80 ~0.009 — about 2x the 0.0047
  Brier gap that justified shipping V2. Equivalence is NOT established;
  the mismatch's accuracy cost is bounded only by that CI. Extending the
  window through season end cannot resolve it (blend converges to raw as
  starters accumulate IP); the decisive Brier test is early-season 2027
  walk-forward, when the conventions maximally disagree.
- FLAG SELECTION (the economics): the conventions are NOT interchangeable.
  Mean per-game probability gap 3.6 pts vs a 3-point-wide bet window; of
  527 odds-joinable games only 57 flag events were shared, 55 blend-only,
  52 raw-only. Replayed at stored prices with live gates: raw arm 64-45
  +$2,317 vs blend arm 54-58 +$104; the exclusive cells split 32-20
  +$1,067 (raw-only) vs 22-33 -$1,147 (blend-only). Cell sizes ~55 —
  a strong lead, not a verdict.
- DECISION: live inference stays on blended inputs mid-season (the
  walk-forward 60.8% validates the SYSTEM AS SHIPPED, not either pure
  convention). NEXT STEP, pending owner approval: a RAW-arm shadow ledger
  at lock time (shadow-first discipline, like F5/runline) so the flag-level
  lead gets a real forward test before any convention switch.

## 2. Historical training rows contain full-season stats (leakage, core #3 class)
The 2023-25 bulk rows were built with each season's FINAL stats, so early-season
games "know" the future. Walk-forward validation on live 2026 data is the real
test and it never had this problem — the live-2026 walk-forward numbers are
the only accuracy claims this project treats as evidence. Any backtest run
ON the training archive itself overstates and is not citable. A clean rebuild
(point-in-time stats) is a multi-day pull; queue for offseason.

## 3. k_summary morning-vs-lock double count (props #8)
K ledger can count a pitcher once from the morning log and once from the lock
snapshot on days both exist. Display-only (K is not texting); dedupe by
(date, pitcher_id) preferring the lock row.

## 4. market_paper de-vig inconsistency (props #15)
Hit-prop paper ledger mixes de-vigged and raw implied across books. Paper
only; standardize `under_key` handling before any hit-prop market decisions.

## 5. hr grader DH played=0 (props #13)
HR/hit graders can mark a player DNP if his stat line sits in the OTHER game
of a doubleheader (boxscore keyed by first matching pk). Affects a handful of
DH days; grade against both pks of a twin bill.

## 6. bullpen_stats label (core #11)
`bullpen_era` is actually team relief ERA incl. openers. Unused by the live
model (bullpen family failed trials); rename when next touched.

## 7. flagged_side both-books edge (core #12)
When DK and MGM disagree on which side clears the window, flagged_side prefers
DK; the text always quotes the flagged book, so no record impact — but the
CLV lock price reads DK odds even when the play was texted at MGM's price.
Store the texted book/price on the row at freeze time.

## 8. Board cosmetic remainders (A10, C2)
Rotation numbers in the player-file header are placeholders; two dead fields
ship in board_stats.json. Cosmetic.

## Notes
- clv_log.json `clv`/`clv_positive`/`open_close_drift` fields remain PICK-side
  (historical artifact). The gate metric ignores them and uses
  `gen_analytics.bet_side_clv_summary` (true-close-only, `unmeasured` counted).
- 29 pre-8/27 dog plays have no bet-side close and never will; they are
  permanently excluded from the CLV gate metric, not estimated.

---

# POSTSEASON ITEMS (2026-09-29 audit, 17 findings)

Data and record-integrity findings were FIXED with regression tests (see the
changelog and PATCHED LEAKS entries dated 2026-09-29). What follows is the
prediction side: evidence is recorded, nothing is implemented, and no term is
fitted to the 2026 postseason, which is the forward test.

## 9. October starter workload vs k_model's expected batters faced
EVIDENCE COMPLETE, AWAITING OWNER DECISION. k_model sets
exp_bf = 0.75*bf_l5 + 0.25*bf_season (LG_BF 21.9, fitted May-Jun 2026) and that
value is the mixture center for the whole K distribution, so it prices every
half-line.

Measured by re-implementing the live formula verbatim and scoring it on 237
postseason starts (2023-25), each using ONLY starts strictly earlier than its
own date:
  - actual 19.77 BF vs predicted 22.51 -> bias -2.75, MAE 4.45, over-predicted
    in 73% of starts
  - same-pitcher regular-season control (n=2,320): bias +0.08, MAE 2.42 - so
    the formula is unbiased in its own regime
  - paired per-pitcher-season (postseason minus his own regular season):
    -4.40 BF, t=-9.17, negative for 82% of pitcher-seasons
  - K consequence: 5.754 K/start regular vs 4.538 postseason, paired -1.24
    (t=-6.61); about -0.83 of that is the BF drop, the rest a K/BF drop
  - worst on a pitcher's FIRST October start (bias -3.57, n=110), because
    bf_l5 is still 5 regular-season starts; only -1.74 by his 2nd+
CHRONOLOGICAL VALIDATION ALREADY RUN on the single-scalar form
exp_bf_post = exp_bf + delta: expanding window (fit 2023 -> test 2024, fit
2023+24 -> test 2025) gives delta -2.70 / -2.66; held-out bias collapses
-2.63 -> +0.07 and -2.45 -> +0.21; MAE -11.5% and -3.9%. Leave-one-season-out:
-2.54 / -2.57 / -2.66, stable to +/-0.1.
NOT IMPLEMENTED. K WATCH is display-only and never texts, so no official record
or money is exposed; the owner decides whether a display model gets a regime
term mid-postseason. If adopted it must be the one scalar, fitted on 2023-25
only, with the 2026 postseason left untouched as the forward test.

## 10. October residual SHAPE (gated behind #9)
RESID_V/RESID_W were fitted May-Jun 2026 and control the whole pmf, not just
spread. Postseason residual quantiles (n=237): p05 -13.1, p25 -5.6, p50 -2.2,
p95 +5.8, sd 5.21, left-skewed. Regular-season control (n=2,320): p05 -5.3,
p25 -1.7, p50 +0.3, p95 +4.8, sd 3.25, near-symmetric. The early-hook left tail
is ~2.5x deeper: a starter pulled after 2 innings is roughly a -14 residual,
which the fitted table weights under 0.5% while in October it sits in the bottom
decile. Consequence: P(K >= n) at the 3.5/4.5 lines (the ones books post in
October) is overstated beyond the location error. If ever fitted, prefer ONE
scale factor on the existing residual index over a new 40-entry table, and only
after #9's mean correction is adopted - never fit shape on an uncorrected mean.

## 11. F5 head in October (paper only)
The starter recorded under 5.0 IP in 17.5% of regular-season starts vs 48.1% of
postseason starts (mean postseason starter IP 4.46; 51.9% under 5.0 across 262
starter lines). model_f5.pkl was fitted on f5_outcomes.csv, which contains zero
postseason games, and F5 has no bullpen term - so in about half of October games
the priced window is decided by relievers the model never saw.
DONE: grade_all() now reports regular-season and postseason subtotals separately
(f5_shadow.POSTSEASON_START), so the go-live decision at SAMPLE_TARGET flags is
never made on a blended regime. Nothing already written changed.
NOTE FOR THE OWNER: the regular-season paper ledger is 24-32, -$1,285,
ROI -19.5% at 56 graded flags - past the 50-flag review point, and currently
arguing against ever going live.

## 12. model_v2 itself has no bullpen term - the one item that can reach the record
training_data.csv contains 2023-25 regular seasons and zero postseason games,
and the four features are starter ERA/WHIP, lineup OPS and team K% with no
bullpen input. Starter share of team batters faced: 57.7% (2026 regular season,
4,266 team-games) vs 50.5% (262 postseason team-games 2023-25); reliever
appearances per team-game 3.27 -> 4.10. master_v2 correctly does NOT filter
gameType, so postseason games are flagged and texted - unlike every other
finding here, this one reaches official plays. The reliability gate does not
catch it: RELIABILITY_MIN measures whether a starter's season IP sample is big
enough to trust, not how much of tonight's game he will pitch, and in October a
thin-IP starter can be a deliberate bulk/opener assignment.
NOT IMPLEMENTED, and deliberately so: a bullpen term is a new feature on a
4-feature calibrated model whose whole validation history is regular-season, and
the bullpen family already failed four walk-forward trials. The testable
question is whether an expected-starter-length or bullpen-quality term improves
held-out postseason Brier over 2023-25 with an expanding-window split, judged
also at flag level (P&L at stored prices), and it must hold in all three
Octobers separately.
SEPARABILITY: postseason plays are identifiable by date (>= 2026-09-29, the
regular season ended 9/27), so the record can be split without touching a row.
Persisting statsapi gameType on the picks row and pit_snapshot would make that
permanent - additive, not done tonight.

## 1b. Training composition: postseason rows are excluded BY DECISION
weekly_retrain and f5_backfill now pass gameTypes="R" explicitly. Their feature
inputs (stats=season) are regular-season-only, so a postseason game would enter
the archive as a regular-season-shaped row carrying a label from a different
data-generating process - and a best-of-N repeats near-identical feature vectors
with independent labels, adding variance at one point in feature space rather
than information (~32-40 rows against an 8,754-row archive, which cannot move a
metric enough to be evidence either way). To decide inclusion properly: a
chronological walk-forward over the 2023/2024/2025 postseasons in a research
copy, include-vs-exclude on Brier and on flag-level P&L at stored prices,
holding in all three seasons separately. Until then the archive stays as
validated. A season_type column on training_data.csv / f5_outcomes.csv would
make the switch auditable - additive, not done tonight.
