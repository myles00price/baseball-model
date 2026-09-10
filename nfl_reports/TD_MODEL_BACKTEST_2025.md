# ANYTIME TD MODEL -- 2025 WALK-FORWARD BACKTEST

4,962 player-games (played only), 1,019 scored (20.5%). Weeks 2-18.

## Team layer (per team-game)

- offensive TDs: MAE vs implied-only model 1.048 ; constant 1.167
- pass TDs: MAE model 0.916 ; league-split-only 0.916
- rush TDs: MAE model 0.748 ; league-split-only 0.748
- bias: projected off TDs 2.388/game vs actual 2.445

## Player layer -- P(anytime TD)

| model | Brier | log loss |
|---|---|---|
| **this model** | 0.1472 | 0.4682 |
| prior-rate baseline | 0.1573 | 0.5960 |
| engine bottom-up | 0.1496 | 0.4737 |
| constant 0.205 | 0.1632 | 0.5077 |

## Calibration (this model)

| bin | n | pred | actual |
|---|---|---|---|
| (-0.001, 0.1] | 1301 | 0.054 | 0.066 |
| (0.1, 0.2] | 1458 | 0.147 | 0.154 |
| (0.2, 0.3] | 1017 | 0.248 | 0.236 |
| (0.3, 0.4] | 707 | 0.347 | 0.348 |
| (0.4, 0.5] | 309 | 0.442 | 0.408 |
| (0.5, 0.6] | 130 | 0.545 | 0.546 |
| (0.6, 0.7] | 40 | 0.631 | 0.625 |

## Calibration (prior-rate baseline)

| bin | n | pred | actual |
|---|---|---|---|
| (-0.001, 0.1] | 1681 | 0.028 | 0.097 |
| (0.1, 0.2] | 975 | 0.152 | 0.178 |
| (0.2, 0.3] | 992 | 0.251 | 0.247 |
| (0.3, 0.4] | 725 | 0.347 | 0.284 |
| (0.4, 0.5] | 284 | 0.445 | 0.313 |
| (0.5, 0.6] | 189 | 0.543 | 0.455 |
| (0.6, 0.7] | 110 | 0.64 | 0.482 |
| (0.7, 1.0] | 6 | 0.787 | 0.5 |

## By position

| pos | n | scored | Brier model | Brier prior | mean p | actual |
|---|---|---|---|---|---|---|
| QB | 614 | 80 | 0.1070 | 0.1127 | 0.132 | 0.130 |
| RB | 1413 | 357 | 0.1614 | 0.1764 | 0.256 | 0.253 |
| TE | 950 | 178 | 0.1435 | 0.1518 | 0.174 | 0.187 |
| WR | 1985 | 404 | 0.1512 | 0.1601 | 0.206 | 0.204 |

## Priced tier (P >= 40%): 479 player-games, mean p 0.486, actual 0.463
