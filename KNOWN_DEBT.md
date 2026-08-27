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
The model walk-forward-validated at 60.8% on raw-stat rows, so raw is the
proven side — but changing inference mid-season shifts every live probability.
**Do not touch without a walk-forward A/B on 2023-25.** Until then the
mismatch stands, documented here.

## 2. Historical training rows contain full-season stats (leakage, core #3 class)
The 2023-25 bulk rows were built with each season's FINAL stats, so early-season
games "know" the future. Walk-forward validation on live 2026 data is the real
test and it never had this problem, so headline accuracy stands — but any
backtest run ON the training archive itself overstates. A clean rebuild
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
