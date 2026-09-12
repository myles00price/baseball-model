# baseball-model — the live system behind THE BOARD

This repo runs a live MLB moneyline model and publishes its full graded
history at **myles00price.github.io/baseball-model/board.html**. Everything in the graded record — results, P&L, closing-line value, edge
buckets, prop ledgers — is regenerated nightly from the files in this repo;
nothing in the graded record is hand-typed. (Explainer text and the MODEL
BIOLOGY write-ups are authored by hand and refreshed at audits/retrains.)

## The model (V2, live since 2026-07-16)

A calibrated logistic regression over four pre-game differences:
starter ERA (winsorized), starter WHIP (winsorized), lineup OPS (capped),
and team strikeout rate. Retrained weekly on the full
multi-season training archive (all rows, current season included); the
coefficients and walk-forward accuracy published in the board's MODEL BIOLOGY
section are refreshed at each weekly retrain, not computed live by the page. Probabilities are clamped to 22–78 and no
post-hoc adjustments are layered on top.

A play is flagged when the model's probability beats a book's implied
probability by **3–6 points** (the window where the model has historically
been right; above 6 the market is usually the one that's right) and the flagged side's starter passes a data-reliability gate (a stricter side-aware rule governs plays against thin opposing starters); Coors Field games are excluded outright. Flat $100 paper stakes; real sizing
is gated behind a public report card (150 plays, ROI ≥ +3%, bet-side CLV
beat ≥ 60%).

## The record: what counts

**Lock-on-text.** A play is official when it is texted to the ntfy topic at
lineup lock, at a stated price. Graders cross-check the sent-text log in
code; untexted flags never enter the official record. Two disclosed
exceptions, decided by the owner on 2026-09-08 and labeled on the board's
provenance line: 6 saved flags and 23 walk-forward reconstructed plays from
an offline stretch (8/27–9/7). The board separates TEXTED / SAVED FLAGS /
RECONSTRUCTED subtotals so live performance is always independently
readable. None of the 29 carry closing-line data, so they are excluded from
the CLV metric.

**Corrections are published, never silently fixed** — see the board's
changelog and PATCHED LEAKS sections for every bug found and what it
changed (doubleheader key collisions, a phantom play, a frozen CLV tile,
a sharp-money signal built on cross-game noise, and more).

## Known limitations (tracked in KNOWN_DEBT.md)

The headline items: training rows use raw season pitcher stats while live
inference feeds career-blended stats (a walk-forward A/B on live 2026 games
is the gating test for any change), and pre-2026 training rows contain
end-of-season stats, so backtests **on the training archive** overstate —
only the live 2026 walk-forward record is treated as evidence. Nothing in
KNOWN_DEBT.md is considered proven until it has a forward test attached.

## Pipeline map

| Stage | Files | Runs |
|---|---|---|
| Slate build + odds + flags | `master_v2.py`, `features_v2.py`, `pitcher_stats.py`, `lineup_stats.py` | morning + lineup checks |
| Lineup lock + texts | `notify_pick.py`, `auto_lineup_push.py`, `settle_notify.py` | every 15 min |
| Grading + record | `check_results.py`, `daily_results_notify.py` | nightly 10:30 PM |
| Weekly report card | `weekly_report.py` | Thursday mornings |
| Board data | `gen_analytics.py`, `board_stats.json`, `board_analytics.json` | nightly |
| Props (HR / hits / Ks) | `hr_model.py`, `hit_model.py`, `k_model.py`, graders, `props_analytics.py` | morning + nightly |
| Retrains | `weekly_retrain_v2.py` (-> `train_model_v2.py`), `props_retrain.py` | weekly |
| Shadows (paper only) | `f5_shadow.py`, runline curves in `gen_analytics.py` | with each slate |

Prop model outputs (plays, probabilities, prices) are public on the board;
their internal methodology is deliberately not documented here.

Frozen morning logs are frozen by code: model scripts refuse to rebuild a
log once the slate has started, and refuse past dates entirely.

## Operational notes

- Python 3.11 (`py -3.11`), shared interpreter — no new packages get
  installed into it; anything extra lives in a venv.
- `ODDS_API_KEY` comes from the environment; no key appears in the current
  code. (An early commit contained a hardcoded key; it has been rotated -
  see the security note in the changelog.)
- Windows Task Scheduler drives every job (`Baseball*` tasks).
- The ntfy topic receives plays, results, and weekly reports only.
