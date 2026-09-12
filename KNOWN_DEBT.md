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
