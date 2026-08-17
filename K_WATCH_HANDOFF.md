# K WATCH — Strikeout Prop Model: Build Brief

Paste this whole file as the first message of a new chat. It is a complete
handoff for building a pitcher-strikeout model on top of the existing MLB
system. The MAIN win-probability model is off-limits to this chat: do not
touch `features_v2.py`, `master_v2.py`, `train_model_v2.py`, `notify_pick.py`
gating logic, or anything that decides/texts official plays. Read them
freely; edit them never (adding a display-only hook is the one exception,
noted below).

---

## 1. What exists (the system you are building beside)

Repo: `C:\Users\Poons\baseball-model` (GitHub Pages: `myles00price.github.io/baseball-model/board.html`).
Interpreter for scheduled jobs: `C:\Users\Poons\AppData\Local\Python\pythoncore-3.11-64\python.exe`
(`py -3.11`). **Never pip-install into it** — live jobs depend on its exact
versions. pybaseball lives in `C:\Users\Poons\Model\.venv\Scripts\python.exe`
if you need Statcast; run those pulls under that venv, write results to CSV/JSON,
and have the 3.11 jobs read the files.

The main model: 4-feature calibrated logistic regression (era/whip/ops/k%
diffs) → win prob → 3–6% edge window vs DK/MGM → texted official plays.
Everything is graded, published, walk-forward validated. Live record is public
on the board (THE LEDGER). Not your concern except as a source of plumbing.

Two prior "watch" products set the pattern you must follow:

- **LONG BALL WATCH** (`hr_model.py` → `hr_watch_{date}.json` → board section).
  Display-only HR probability list. Every factor was backtested walk-forward
  before shipping; the ones that lost holdout (platoon, arsenal, wind, temp)
  were REMOVED from the published number and are only logged. It self-grades
  nightly (`hr_grade.py` → `hr_training_data.csv`).
- **F5 SHADOW** (`f5_shadow.py`). A first-5-innings head that logs paper bets
  at real prices, locks with lineups, and grades itself into
  `board_analytics.json`. No money, no texts, until 50+ paper flags earn it.

**K WATCH follows the same rules: display-only, self-grading from day one,
real book prices logged beside fair odds, and it earns any bet flag only if the
graded archive beats the market. No texts to subscribers, ever, from this chat.**

## 2. Plumbing you can reuse (read these first)

| need | where |
|---|---|
| pitcher season/career K%, IP, reliability, hand | `pitcher_stats.py` (`get_blended_pitcher_stats`, `season_total_split` — traded-player safe) |
| confirmed lineups + per-batter platoon numbers | `lineup_stats.py` (`get_platoon_lineup_ops`, `_best_split`), `master_v2.get_todays_lineups` |
| point-in-time team K% | `master_v2.get_team_stats` (kpct) — for backtests use statsapi `teams/{id}/stats?stats=byDateRange` (see `team_offense_family_test.py` for the pattern + TID map) |
| per-pitcher usage archive (pitches, IP, BF, start flag, every game since 4/1) | `pen_usage.csv` (built by `pen_usage_log.py`, appended nightly) — this gives you each starter's pitch-count/IP tendency for expected batters faced |
| slate schedule + probables | statsapi `schedule?hydrate=probablePitcher,lineups` (see `master_v2.run_model`) |
| odds | the-odds-api, key in env `ODDS_API_KEY` (never hardcode). Market key: `pitcher_strikeouts` via `/events/{id}/odds?markets=pitcher_strikeouts&bookmakers=draftkings,fanduel,betmgm,williamhill_us`. 1 credit per game. See `f5_shadow.fetch_f5_odds` for the exact call shape and `f5_shadow.event_id_map` for event ids. Check `hr_model.py` for how alternate-line markets are handled (some books file lines under `_alternate`). |
| slate date filtering | `features_v2.commence_lv_date` — the odds API returns multiple days; ALWAYS filter to the slate date |
| board rendering pattern | `board.html`: see the LONG BALL WATCH section + `loadLedger` for how JSON is fetched (`tryFetch` with `?t=` cache-bust, same-origin then `${REPO}` fallback), rendered, and how INFO drop-downs (`openInfo(ev,key)` + the `INFO` dict) explain each section. **Never edit board.html with PowerShell** — non-ASCII gets mangled; use the Edit tool. |
| nightly grading hook | `daily_results_notify.py` calls `gen_analytics.main()`, `pen_usage_log.collect_recent()`, and `hr_grade` in a try/except each; add `k_grade` the same way |
| morning refresh hook | `morning_report.py` calls `hr_model.py` via subprocess at the end and pushes; add the K watch build there (display-only hook — the one allowed edit to a main-pipeline file) |
| console encoding | every scheduled script starts with `if sys.stdout and hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(errors="replace")` |
| git | scripts push themselves after writing (see morning_report/notify_pick for the subprocess pattern) |

## 3. The model to build

Target: each starting pitcher's strikeout total tonight, as a distribution.

Skeleton (all inputs point-in-time — only data available BEFORE the game):

1. **Per-PA K probability** for this pitcher vs this lineup:
   pitcher K% (season, shrunk toward career/league with a BF prior — K% stabilizes ~70 BF, so a light prior) combined with each confirmed batter's K% vs the pitcher's hand (shrunk, ~60 PA prior; fall back to team K% when lineups aren't posted). Use log-odds averaging (odds-ratio method vs league K%) rather than raw multiplication.
2. **Expected batters faced**: from the pitcher's recent IP/pitch-count tendency in `pen_usage.csv` (last 5–8 starts, plus season), adjusted by opposing lineup OBP (more baserunners → more BF per inning). Cap sensibly.
3. **Distribution**: Poisson-binomial over expected BF (or Poisson with the mean = BF × pK, slightly overdispersed) → P(K ≥ 4.5, 5.5, 6.5, 7.5…) → fair American odds per line.
4. Compare to the book lines/prices; log everything.

Things that will tempt you and must be TESTED, not assumed (the HR watch lost
most of these in holdout): recent-form/velocity trend, umpire K tendencies,
weather, park K factors, catcher framing. Ship the plain skeleton first, backtest
each addition walk-forward, keep only what wins out-of-sample. Recency
weighting has failed three separate times in this repo — expect it to fail again.

## 4. Backtest before shipping (house rule: walk-forward or it didn't happen)

- Build a point-in-time dataset over the 2026 season: for each start since ~May 1, the pitcher's pre-game K%/BF tendencies, the lineup or team K%, and the actual K total (boxscores via statsapi `game/{pk}/boxscore` — `pen_usage.csv` already has every starter's actual K? No — it has IP/pitches/BF; pull `strikeOuts` from the same boxscore field, or extend `pen_usage_log.py` to record it going forward and backfill once).
- Report calibration of P(over N.5) by bucket, Brier vs the naive "season K/9 × 6 IP" baseline, and MAE on the K total. Then simulate vs closing lines if you can capture them (the-odds-api historical endpoint costs 10 credits/snapshot — ask before spending; the plan has ~16k credits, main model uses ~40/day).
- Only after that: ship the display.

## 5. Deliverables

1. `k_model.py` — builds `k_watch_{date}.json` (every starter on the slate: name, team, opp, hand, expected K, expected BF, P(over) for the book's main line + alts, fair odds, best DK/FD/MGM/CZR price, lineup status) + logs the full slate with all factors to `k_log_{date}.csv` (training archive; never backfill past dates into it — same-day stats leak).
2. `k_grade.py` — nightly: join boxscore K totals to the day's log, append to `k_training_data.csv` (idempotent by date+pitcher), write a small summary (calibration by P(over) bucket, record vs closing line if captured) for the board.
3. Board section **K WATCH** on `board.html` (MLB section, near LONG BALL WATCH): rows sortable by edge vs best line; INFO drop-down explaining method + that it is display-only; label everything clearly — no gold play bars, nothing that looks like an official play.
4. `changelog.json` entry (newest-first array of `{d,t,x}`, subscriber-safe language, no ops/API talk) describing what shipped and what was tested/rejected. Update it again for every material change.
5. Hooks: morning build in `morning_report.py` (subprocess, try/except, never let it block the real report), nightly grade in `daily_results_notify.py` (same pattern). Verify Task Scheduler jobs still exit 0x0 after the change (`Get-ScheduledTaskInfo`).
6. A short `K_WATCH_NOTES.md` in the repo: method, backtest numbers, what was rejected and why, credit cost per day.

## 6. Non-negotiables

- Display-only. No texts to `poons-mlb-picks-k7d24q` (subscriber topic) — ever. Ops chatter can go to `poons-mlb-ops-x9r31m` if needed.
- Do not modify main-model logic, gates, windows, graders, or the texting path.
- Point-in-time discipline in every backtest; publish honest numbers on the board even when they're bad.
- Every factor earns its place walk-forward; failed factors are logged, not published.
- Never roundtrip non-ASCII files through PowerShell. Use full python.exe paths in any new scheduled task. Do not pip-install into the shared interpreter.
- Commit + push after each meaningful step; the board self-updates from the repo.

Start by reading `hr_model.py`, `hr_grade.py`, `f5_shadow.py`, `pen_usage_log.py`, and the LONG BALL WATCH section of `board.html`, then propose the k_model skeleton and the backtest plan before writing production code.
