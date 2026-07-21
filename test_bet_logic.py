"""Acceptance tests for the BET window and flag-side attribution.

Run:  py -3.11 .\\test_bet_logic.py
Origin: 2026-07-18 bug report — flagged bets were being graded on the model's
pick side even when the flag belonged to the value-dog side.
"""

from features_v2 import is_bet, flagged_side, BET_MIN, BET_MAX

# ── Window: signed edge, inclusive bounds ─────────────────────────────────
assert BET_MIN == 3.0 and BET_MAX == 8.0
assert is_bet(+5.2) is True      # Mets morning flag
assert is_bet(+6.5) is True      # Cardinals
assert is_bet(+3.0) is True      # window floor inclusive
assert is_bet(+8.0) is True      # window ceiling inclusive
assert is_bet(+2.8) is False     # Yankees — below floor
assert is_bet(+9.8) is False     # above ceiling
assert is_bet(-9.8) is False     # Cubs pick-side edge (flag was Twins side)
assert is_bet(-12.3) is False    # Phillies pick-side edge (flag was Mets side)
assert is_bet(-6.8) is False     # the abs() trap: |edge| in window, sign negative
assert is_bet(None) is False     # missing odds

# ── Flag-side attribution from picks-CSV rows ─────────────────────────────
twins_cubs = {  # 2026-07-17: value on the AWAY dog, model picks home
    "DK Edge Away": "+5.2% ** BET **", "MGM Edge Away": "+5.4% ** BET **",
    "DK Edge Home": "-9.8%", "MGM Edge Home": "-9.6%",
}
assert flagged_side(twins_cubs) == "away"

jays = {  # home-side value
    "DK Edge Away": "-8.8%", "MGM Edge Away": "-8.4%",
    "DK Edge Home": "+4.3% ** BET **", "MGM Edge Home": "+3.6% ** BET **",
}
assert flagged_side(jays) == "home"

no_bet = {
    "DK Edge Away": "+2.8%", "MGM Edge Away": "+2.5%",
    "DK Edge Home": "-4.6%", "MGM Edge Home": "-4.1%",
}
assert flagged_side(no_bet) is None

print("All bet-logic tests pass.")
