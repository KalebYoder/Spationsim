"""
Tests for per-territory resource yield calculation.

Production formula (matches tick.py):
  mine:     normal  → max(5, round(mineral_richness × 2))
            anomaly → round(mineral_richness × 2 + 10)
  refinery: normal  → max(5, round(fuel_richness × 2))
            anomaly → round(fuel_richness × 2 + 10)

Currency income: 30 per active mine or refinery per tick (per facility, not per territory).
Currency upkeep: 2 per stationed fighter.
"""
import pytest
from app.services.territory_yield import compute_territory_yield

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def yield_of(**kwargs):
    """Shortcut: call compute_territory_yield with sane defaults."""
    defaults = dict(
        territory_type="normal",
        mineral_richness=3.0,
        fuel_richness=3.0,
        mine_count=0,
        refinery_count=0,
        stationed_fighters=0,
    )
    defaults.update(kwargs)
    return compute_territory_yield(**defaults)


# ---------------------------------------------------------------------------
# Zero / empty territory
# ---------------------------------------------------------------------------

def test_no_facilities_produces_nothing():
    y = yield_of(mine_count=0, refinery_count=0)
    assert y["minerals_per_tick"] == 0
    assert y["fuel_per_tick"] == 0
    assert y["currency_income_per_tick"] == 0
    assert y["currency_upkeep_per_tick"] == 0
    assert y["currency_net_per_tick"] == 0


# ---------------------------------------------------------------------------
# Mine production -- normal territory
# ---------------------------------------------------------------------------

def test_mine_richness_1_clamps_to_5():
    # max(5, round(1 x 2)) = max(5, 2) = 5
    y = yield_of(mineral_richness=1.0, mine_count=1)
    assert y["minerals_per_tick"] == 5


def test_mine_richness_2_clamps_to_5():
    # max(5, round(2 x 2)) = max(5, 4) = 5
    y = yield_of(mineral_richness=2.0, mine_count=1)
    assert y["minerals_per_tick"] == 5


def test_mine_richness_3_produces_6():
    # max(5, round(3 x 2)) = max(5, 6) = 6
    y = yield_of(mineral_richness=3.0, mine_count=1)
    assert y["minerals_per_tick"] == 6


def test_mine_richness_4_produces_8():
    # max(5, round(4 x 2)) = max(5, 8) = 8
    y = yield_of(mineral_richness=4.0, mine_count=1)
    assert y["minerals_per_tick"] == 8


def test_mine_richness_5_produces_10():
    # max(5, round(5 x 2)) = max(5, 10) = 10
    y = yield_of(mineral_richness=5.0, mine_count=1)
    assert y["minerals_per_tick"] == 10


def test_two_mines_double_production():
    # 2 x max(5, round(3 x 2)) = 2 x 6 = 12
    y = yield_of(mineral_richness=3.0, mine_count=2)
    assert y["minerals_per_tick"] == 12


def test_three_mines_triple_production():
    y = yield_of(mineral_richness=5.0, mine_count=3)
    assert y["minerals_per_tick"] == 30


# ---------------------------------------------------------------------------
# Refinery production -- normal territory
# ---------------------------------------------------------------------------

def test_refinery_richness_1_clamps_to_5():
    y = yield_of(fuel_richness=1.0, refinery_count=1)
    assert y["fuel_per_tick"] == 5


def test_refinery_richness_3_produces_6():
    y = yield_of(fuel_richness=3.0, refinery_count=1)
    assert y["fuel_per_tick"] == 6


def test_refinery_richness_5_produces_10():
    y = yield_of(fuel_richness=5.0, refinery_count=1)
    assert y["fuel_per_tick"] == 10


def test_two_refineries_double_fuel():
    y = yield_of(fuel_richness=4.0, refinery_count=2)
    assert y["fuel_per_tick"] == 16


# ---------------------------------------------------------------------------
# Anomaly territory production
# ---------------------------------------------------------------------------

def test_anomaly_mine_richness_5_produces_20():
    # round(5 x 2 + 10) = round(20) = 20
    y = yield_of(territory_type="anomaly", mineral_richness=5.0, mine_count=1)
    assert y["minerals_per_tick"] == 20


def test_anomaly_mine_richness_7_produces_24():
    # round(7 x 2 + 10) = round(24) = 24
    y = yield_of(territory_type="anomaly", mineral_richness=7.0, mine_count=1)
    assert y["minerals_per_tick"] == 24


def test_anomaly_mine_richness_10_produces_30():
    # round(10 x 2 + 10) = round(30) = 30
    y = yield_of(territory_type="anomaly", mineral_richness=10.0, mine_count=1)
    assert y["minerals_per_tick"] == 30


def test_anomaly_refinery_richness_8_produces_26():
    # round(8 x 2 + 10) = round(26) = 26
    y = yield_of(territory_type="anomaly", fuel_richness=8.0, refinery_count=1)
    assert y["fuel_per_tick"] == 26


def test_anomaly_mine_is_strictly_greater_than_normal_at_richness_5():
    normal = yield_of(territory_type="normal",  mineral_richness=5.0, mine_count=1)
    anomaly = yield_of(territory_type="anomaly", mineral_richness=5.0, mine_count=1)
    assert anomaly["minerals_per_tick"] > normal["minerals_per_tick"]


# ---------------------------------------------------------------------------
# Currency income
# ---------------------------------------------------------------------------

def test_one_mine_triggers_currency_income():
    # 1 mine × 30¤ = 30¤
    y = yield_of(mine_count=1)
    assert y["currency_income_per_tick"] == 30


def test_one_refinery_triggers_currency_income():
    # 1 refinery × 30¤ = 30¤
    y = yield_of(refinery_count=1)
    assert y["currency_income_per_tick"] == 30


def test_mine_and_refinery_together_doubles_income():
    # Income is per facility: (1 mine + 1 refinery) × 30¤ = 60¤
    y = yield_of(mine_count=1, refinery_count=1)
    assert y["currency_income_per_tick"] == 60


def test_five_mines_income_scales_linearly():
    # 5 mines × 30¤ = 150¤
    y = yield_of(mine_count=5)
    assert y["currency_income_per_tick"] == 150


def test_no_facilities_no_currency_income():
    y = yield_of(mine_count=0, refinery_count=0)
    assert y["currency_income_per_tick"] == 0


# ---------------------------------------------------------------------------
# Currency upkeep (stationed fighters)
# ---------------------------------------------------------------------------

def test_no_fighters_no_upkeep():
    y = yield_of(stationed_fighters=0)
    assert y["currency_upkeep_per_tick"] == 0


def test_one_fighter_costs_2_currency():
    y = yield_of(stationed_fighters=1)
    assert y["currency_upkeep_per_tick"] == 2


def test_100_fighters_costs_200_currency():
    y = yield_of(stationed_fighters=100)
    assert y["currency_upkeep_per_tick"] == 200


# ---------------------------------------------------------------------------
# Net currency
# ---------------------------------------------------------------------------

def test_net_currency_positive_with_mine_and_few_fighters():
    # income 30 (1 mine × 30¤), upkeep 2 × 10 = 20 → net 10
    y = yield_of(mine_count=1, stationed_fighters=10)
    assert y["currency_net_per_tick"] == 10


def test_net_currency_zero_at_break_even():
    # income 30, upkeep 2 × 15 = 30 → net 0
    y = yield_of(mine_count=1, stationed_fighters=15)
    assert y["currency_net_per_tick"] == 0


def test_net_currency_negative_when_upkeep_exceeds_income():
    # income 30, upkeep 2 × 20 = 40 → net -10
    y = yield_of(mine_count=1, stationed_fighters=20)
    assert y["currency_net_per_tick"] == -10


def test_net_currency_negative_with_no_income_and_fighters():
    # income 0, upkeep 2 x 10 = 20 -> net -20
    y = yield_of(mine_count=0, refinery_count=0, stationed_fighters=10)
    assert y["currency_net_per_tick"] == -20


def test_net_equals_income_minus_upkeep():
    y = yield_of(mine_count=1, refinery_count=1, stationed_fighters=75)
    assert y["currency_net_per_tick"] == y["currency_income_per_tick"] - y["currency_upkeep_per_tick"]


# ---------------------------------------------------------------------------
# Mine does not affect fuel; refinery does not affect minerals
# ---------------------------------------------------------------------------

def test_mine_does_not_produce_fuel():
    y = yield_of(mineral_richness=5.0, fuel_richness=5.0, mine_count=3, refinery_count=0)
    assert y["fuel_per_tick"] == 0


def test_refinery_does_not_produce_minerals():
    y = yield_of(mineral_richness=5.0, fuel_richness=5.0, mine_count=0, refinery_count=3)
    assert y["minerals_per_tick"] == 0


# ---------------------------------------------------------------------------
# Return type guarantees
# ---------------------------------------------------------------------------

def test_return_value_is_dict_with_expected_keys():
    y = yield_of()
    expected_keys = {
        "minerals_per_tick",
        "fuel_per_tick",
        "currency_income_per_tick",
        "currency_upkeep_per_tick",
        "currency_net_per_tick",
    }
    assert set(y.keys()) == expected_keys


def test_all_values_are_ints():
    y = yield_of(mine_count=1, refinery_count=1, stationed_fighters=50)
    assert all(isinstance(v, int) for v in y.values())


# ===========================================================================
# QA-pass additions -- gaps not covered by the developer-written tests above
# ===========================================================================

# ---------------------------------------------------------------------------
# Fractional richness values (DB column is Numeric(4,2); 2.5 is a real input)
# ---------------------------------------------------------------------------

def test_mine_richness_fractional_below_floor_boundary():
    # max(5, round(2.4 x 2)) = max(5, round(4.8)) = max(5, 5) = 5
    # Verifies fractional richness that rounds to exactly 5 still clamps correctly
    y = yield_of(mineral_richness=2.4, mine_count=1)
    assert y["minerals_per_tick"] == 5


def test_mine_richness_fractional_at_floor_boundary():
    # max(5, round(2.5 x 2)) = max(5, round(5.0)) = max(5, 5) = 5
    # 2.5 is the first value where r*2 == 5; still hits the floor
    y = yield_of(mineral_richness=2.5, mine_count=1)
    assert y["minerals_per_tick"] == 5


def test_mine_richness_fractional_just_above_floor_boundary():
    # max(5, round(2.6 x 2)) = max(5, round(5.2)) = max(5, 5) = 5
    # 2.6 still rounds down to 5, still clamped
    y = yield_of(mineral_richness=2.6, mine_count=1)
    assert y["minerals_per_tick"] == 5


def test_mine_richness_fractional_escapes_floor():
    # max(5, round(3.5 x 2)) = max(5, round(7.0)) = max(5, 7) = 7
    # 3.5 produces 7, above the floor of 5
    y = yield_of(mineral_richness=3.5, mine_count=1)
    assert y["minerals_per_tick"] == 7


def test_mine_richness_fractional_midpoint_rounding():
    # round(1.75 x 2) = round(3.5) -- Python banker's rounding rounds to 4 (nearest even)
    # max(5, 4) = 5; confirms the floor absorbs banker's rounding artifacts at low richness
    y = yield_of(mineral_richness=1.75, mine_count=1)
    assert y["minerals_per_tick"] == 5


def test_refinery_richness_fractional_midpoint_rounding():
    # round(1.75 x 2) = round(3.5) = 4 (banker's rounding); max(5, 4) = 5
    # Parallel check for refinery to ensure symmetric formula behavior
    y = yield_of(fuel_richness=1.75, refinery_count=1)
    assert y["fuel_per_tick"] == 5


def test_mine_richness_fractional_midpoint_above_floor():
    # round(3.75 x 2) = round(7.5) = 8 (banker's rounding rounds to even: 8)
    # max(5, 8) = 8; above the floor so banker's rounding is observable
    y = yield_of(mineral_richness=3.75, mine_count=1)
    assert y["minerals_per_tick"] == 8


# ---------------------------------------------------------------------------
# Void territory type
# ---------------------------------------------------------------------------

def test_void_territory_with_no_facilities_produces_nothing():
    # Void nodes cannot be colonized and have zero richness, so no output expected
    y = yield_of(
        territory_type="void",
        mineral_richness=0.0,
        fuel_richness=0.0,
        mine_count=0,
        refinery_count=0,
    )
    assert y["minerals_per_tick"] == 0
    assert y["fuel_per_tick"] == 0
    assert y["currency_income_per_tick"] == 0


def test_void_territory_type_uses_normal_formula_not_anomaly():
    # "void" is not "anomaly"; the else branch applies: max(5, round(r * 2))
    # With richness 5.0 and a mine: max(5, round(10)) = 10, not 20
    y = yield_of(territory_type="void", mineral_richness=5.0, mine_count=1)
    assert y["minerals_per_tick"] == 10


def test_void_territory_stationed_fighters_still_incur_upkeep():
    # Upkeep is independent of territory type; fleets can station anywhere
    y = yield_of(
        territory_type="void",
        mineral_richness=0.0,
        fuel_richness=0.0,
        mine_count=0,
        refinery_count=0,
        stationed_fighters=50,
    )
    assert y["currency_upkeep_per_tick"] == 100
    assert y["currency_net_per_tick"] == -100


# ---------------------------------------------------------------------------
# Zero richness (valid DB value per Numeric(4,2) constraint)
# ---------------------------------------------------------------------------

def test_mine_zero_richness_clamps_to_floor():
    # max(5, round(0 x 2)) = max(5, 0) = 5
    # A planet with a mine but richness=0 still produces the minimum floor output
    y = yield_of(mineral_richness=0.0, mine_count=1)
    assert y["minerals_per_tick"] == 5


def test_refinery_zero_richness_clamps_to_floor():
    # max(5, round(0 x 2)) = max(5, 0) = 5
    y = yield_of(fuel_richness=0.0, refinery_count=1)
    assert y["fuel_per_tick"] == 5


def test_anomaly_mine_zero_richness_produces_ten():
    # round(0 x 2 + 10) = 10; anomaly has no floor, bonus alone drives output
    y = yield_of(territory_type="anomaly", mineral_richness=0.0, mine_count=1)
    assert y["minerals_per_tick"] == 10


def test_anomaly_refinery_zero_richness_produces_ten():
    # round(0 x 2 + 10) = 10; symmetric with mine case
    y = yield_of(territory_type="anomaly", fuel_richness=0.0, refinery_count=1)
    assert y["fuel_per_tick"] == 10


def test_anomaly_zero_richness_beats_normal_zero_richness():
    # Anomaly bonus (10) must always exceed normal floor (5) even at richness=0
    normal = yield_of(territory_type="normal", mineral_richness=0.0, mine_count=1)
    anomaly = yield_of(territory_type="anomaly", mineral_richness=0.0, mine_count=1)
    assert anomaly["minerals_per_tick"] > normal["minerals_per_tick"]


# ---------------------------------------------------------------------------
# Currency income -- ordering insensitivity (mine_count=0, refinery_count>0)
# ---------------------------------------------------------------------------

def test_currency_income_triggered_by_refinery_only_no_mine():
    # 1 refinery × 30¤; guards against a mine-first short-circuit
    y = yield_of(mine_count=0, refinery_count=1)
    assert y["currency_income_per_tick"] == 30


def test_currency_income_triggered_by_mine_only_no_refinery():
    # 1 mine × 30¤; guards against a refinery-first short-circuit
    y = yield_of(mine_count=1, refinery_count=0)
    assert y["currency_income_per_tick"] == 30


def test_anomaly_territory_with_mine_still_earns_currency():
    # Currency income applies regardless of territory_type: 1 mine × 30¤
    y = yield_of(territory_type="anomaly", mine_count=1)
    assert y["currency_income_per_tick"] == 30


# ---------------------------------------------------------------------------
# Negative mine_count / refinery_count -- document current behavior
# ---------------------------------------------------------------------------

def test_negative_mine_count_produces_negative_minerals():
    # The service performs no input validation; mine_count * per_mine_output goes negative.
    # This test documents the actual behavior so a future guard clause is noticed.
    # If the implementation adds validation and raises, update this test accordingly.
    y = yield_of(mineral_richness=3.0, mine_count=-1)
    assert y["minerals_per_tick"] < 0


def test_negative_refinery_count_produces_negative_fuel():
    # Same documentation test for refinery_count
    y = yield_of(fuel_richness=3.0, refinery_count=-1)
    assert y["fuel_per_tick"] < 0


def test_negative_mine_count_produces_negative_currency_income():
    # No input validation: -1 mine × 30¤ = -30¤. Documents current behavior.
    y = yield_of(mine_count=-1, refinery_count=0)
    assert y["currency_income_per_tick"] == -30


def test_negative_refinery_count_produces_negative_currency_income():
    # Symmetric: -1 refinery × 30¤ = -30¤
    y = yield_of(mine_count=0, refinery_count=-1)
    assert y["currency_income_per_tick"] == -30


# ---------------------------------------------------------------------------
# Large stationed_fighters values
# ---------------------------------------------------------------------------

def test_large_stationed_fighters_upkeep_is_linear():
    # 10,000 fighters x 2 = 20,000 upkeep; confirms no integer overflow or cap
    y = yield_of(stationed_fighters=10_000)
    assert y["currency_upkeep_per_tick"] == 20_000


def test_large_stationed_fighters_net_currency_deeply_negative():
    # A heavily garrisoned territory with no income should drain significantly
    y = yield_of(mine_count=0, refinery_count=0, stationed_fighters=10_000)
    assert y["currency_net_per_tick"] == -20_000


def test_large_fighters_with_income_still_net_negative():
    # 30 income (1 mine × 30¤), 10,000 × 2 = 20,000 upkeep → -19,970 net
    y = yield_of(mine_count=1, stationed_fighters=10_000)
    assert y["currency_net_per_tick"] == -19_970


# ---------------------------------------------------------------------------
# Constants are in sync with tick.py
# ---------------------------------------------------------------------------

def test_currency_income_constant_matches_tick_py():
    # tick.py: currency_delta = 30 * income_facility_count
    from app.services.territory_yield import CURRENCY_INCOME_PER_FACILITY
    assert CURRENCY_INCOME_PER_FACILITY == 30


def test_fighter_upkeep_constant_is_2():
    # tick.py does not yet subtract fighter upkeep per-territory, but the service
    # documents the intended rate as 2 per fighter.  If tick.py ever adds this
    # deduction the constant here must remain the source of truth.
    from app.services.territory_yield import FIGHTER_CURRENCY_UPKEEP
    assert FIGHTER_CURRENCY_UPKEEP == 2


# ---------------------------------------------------------------------------
# Unknown / unrecognized territory_type falls through to normal formula
# ---------------------------------------------------------------------------

def test_unknown_territory_type_uses_normal_formula():
    # Any string that is not "anomaly" hits the else branch; should behave like normal
    y = yield_of(territory_type="colony", mineral_richness=3.0, mine_count=1)
    normal = yield_of(territory_type="normal", mineral_richness=3.0, mine_count=1)
    assert y["minerals_per_tick"] == normal["minerals_per_tick"]


def test_empty_string_territory_type_uses_normal_formula():
    # Empty string is not "anomaly"; else branch applies
    y = yield_of(territory_type="", mineral_richness=3.0, mine_count=1)
    normal = yield_of(territory_type="normal", mineral_richness=3.0, mine_count=1)
    assert y["minerals_per_tick"] == normal["minerals_per_tick"]


# ---------------------------------------------------------------------------
# Anomaly vs normal: anomaly formula never applies the floor (max(5, ...))
# ---------------------------------------------------------------------------

def test_anomaly_has_no_floor_at_very_low_richness():
    # normal: max(5, round(0.1 x 2)) = max(5, 0) = 5
    # anomaly: round(0.1 x 2 + 10) = round(10.2) = 10  -- no floor applied
    # If the anomaly formula accidentally applied the normal floor, both would be 5
    normal = yield_of(territory_type="normal", mineral_richness=0.1, mine_count=1)
    anomaly = yield_of(territory_type="anomaly", mineral_richness=0.1, mine_count=1)
    assert normal["minerals_per_tick"] == 5
    assert anomaly["minerals_per_tick"] == 10


# ---------------------------------------------------------------------------
# Multi-mine / multi-refinery scaling with fractional richness
# ---------------------------------------------------------------------------

def test_multiple_mines_scale_correctly_with_fractional_richness():
    # 3 mines at richness 3.5: each produces max(5, round(7.0)) = 7 -> total 21
    y = yield_of(mineral_richness=3.5, mine_count=3)
    assert y["minerals_per_tick"] == 21


def test_multiple_refineries_scale_correctly_with_fractional_richness():
    # 2 refineries at richness 4.5: each produces max(5, round(9.0)) = 9 -> total 18
    y = yield_of(fuel_richness=4.5, refinery_count=2)
    assert y["fuel_per_tick"] == 18


# ---------------------------------------------------------------------------
# Return type guarantees for fractional inputs
# ---------------------------------------------------------------------------

def test_all_values_are_ints_with_fractional_richness():
    # Fractional richness must still produce integer outputs after round()
    y = yield_of(mineral_richness=2.5, fuel_richness=3.7, mine_count=2, refinery_count=1, stationed_fighters=7)
    assert all(isinstance(v, int) for v in y.values())


# ===========================================================================
# dissent_production_modifier -- direct function tests
# ===========================================================================
# Formula: t = max(0, (d - 25) / 75)
#          modifier = max(0.0, 1.0 - t ** DISSENT_CURVE_EXPONENT)
# where DISSENT_CURVE_EXPONENT = 1.71 (from app.constants).
# Anchor: dissent=75 -> modifier=0.50 (exact within 0.001).
# ===========================================================================

from app.services.territory_yield import dissent_production_modifier


# ---------------------------------------------------------------------------
# Spec reference table -- fixed anchor points
# ---------------------------------------------------------------------------

def test_dissent_production_modifier_zero_dissent_is_1():
    # Below onset (25): no penalty applied; full production.
    # d=0: t=max(0,(0-25)/75)=0 -> modifier=1-0=1.0
    assert dissent_production_modifier(0) == 1.0


def test_dissent_production_modifier_onset_exactly_1():
    # d=25 is the onset boundary; no effect at or below 25.
    # t = max(0, (25-25)/75) = 0 -> modifier = 1.0
    assert dissent_production_modifier(25) == 1.0


def test_dissent_production_modifier_50_approx_085():
    # d=50: t=(50-25)/75=1/3 -> modifier=1-(1/3)^1.71 approx 0.847
    # Spec says approx 0.85; use generous tolerance to survive exponent tuning.
    result = dissent_production_modifier(50)
    assert result == pytest.approx(0.85, abs=0.02)


def test_dissent_production_modifier_75_exact_anchor():
    # d=75 is the spec anchor: modifier must be exactly 0.50 (within 0.001).
    # t=(75-25)/75=2/3 -> modifier=1-(2/3)^1.71
    result = dissent_production_modifier(75)
    assert result == pytest.approx(0.50, abs=0.001)


def test_dissent_production_modifier_87_approx_028():
    # d=87: t=(87-25)/75=62/75 approx 0.8267 -> modifier=1-(0.8267)^1.71 approx 0.280
    result = dissent_production_modifier(87)
    assert result == pytest.approx(0.28, abs=0.02)


def test_dissent_production_modifier_100_is_zero():
    # Full suppression: d=100 -> t=1.0 -> modifier=1-1^1.71=0.0
    assert dissent_production_modifier(100) == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Boundary: below-onset values all return 1.0
# ---------------------------------------------------------------------------

def test_dissent_production_modifier_below_onset_is_always_1():
    # All values strictly below 25 must return exactly 1.0 (no penalty).
    for d in [0, 1, 10, 20, 24]:
        assert dissent_production_modifier(d) == 1.0, f"Expected 1.0 at dissent={d}"


def test_dissent_production_modifier_24_is_1():
    # One below the onset boundary -- ensure off-by-one cannot creep in.
    assert dissent_production_modifier(24) == 1.0


# ---------------------------------------------------------------------------
# Boundary: above 100 clamps to 0.0 (t > 1 makes the exponentiation > 1,
# so max(0.0, ...) must absorb it rather than producing a negative modifier)
# ---------------------------------------------------------------------------

def test_dissent_production_modifier_above_100_clamps_to_zero():
    # Dissent cannot exceed 100 in the game, but the function must not return
    # a negative multiplier if called with out-of-range values.
    result = dissent_production_modifier(110)
    assert result >= 0.0


def test_dissent_production_modifier_200_does_not_go_negative():
    # Extreme out-of-range value: max(0.0, ...) guard must hold.
    result = dissent_production_modifier(200)
    assert result >= 0.0


# ---------------------------------------------------------------------------
# Monotonicity: modifier must be strictly non-increasing as dissent rises
# ---------------------------------------------------------------------------

def test_dissent_production_modifier_is_monotonically_non_increasing():
    # For every integer dissent value 0..100 the modifier must be <= the
    # previous value.  A non-monotonic result would indicate a formula bug.
    prev = dissent_production_modifier(0)
    for d in range(1, 101):
        current = dissent_production_modifier(d)
        assert current <= prev + 1e-9, (
            f"Modifier increased from dissent={d - 1} ({prev:.4f}) to "
            f"dissent={d} ({current:.4f})"
        )
        prev = current


# ---------------------------------------------------------------------------
# Return type: always a float in [0.0, 1.0]
# ---------------------------------------------------------------------------

def test_dissent_production_modifier_return_type_is_float():
    assert isinstance(dissent_production_modifier(50), float)


def test_dissent_production_modifier_always_in_unit_interval():
    # Spot-check a broad sample of valid dissent values.
    for d in range(0, 101, 5):
        result = dissent_production_modifier(d)
        assert 0.0 <= result <= 1.0, f"Modifier {result} out of [0,1] at dissent={d}"


# ---------------------------------------------------------------------------
# DISSENT_CURVE_EXPONENT constant is importable and matches constants.py
# ---------------------------------------------------------------------------

def test_dissent_curve_exponent_constant_is_1_71():
    # The exponent is defined in constants.py and must be read from there
    # (not hardcoded in territory_yield.py) so a single-point tuning change
    # during beta propagates correctly.
    from app.constants import DISSENT_CURVE_EXPONENT
    assert DISSENT_CURVE_EXPONENT == pytest.approx(1.71, abs=1e-9)


# ===========================================================================
# compute_territory_yield -- dissent_modifier parameter integration tests
# ===========================================================================
# The dissent_modifier is applied ONLY to minerals_per_tick and fuel_per_tick.
# Formula: output = round(raw_value * dissent_modifier)
# Currency income, upkeep, and net are NOT scaled.
# ===========================================================================

# ---------------------------------------------------------------------------
# Default / backward compatibility
# ---------------------------------------------------------------------------

def test_compute_territory_yield_dissent_modifier_default_is_1():
    # Calling without dissent_modifier must behave identically to modifier=1.0.
    # This guards backward compatibility for all existing callers.
    without = yield_of(mine_count=2, refinery_count=1, stationed_fighters=10)
    with_explicit = yield_of(mine_count=2, refinery_count=1, stationed_fighters=10, dissent_modifier=1.0)
    assert without == with_explicit


def test_compute_territory_yield_modifier_1_no_change_to_minerals():
    # modifier=1.0 must leave minerals_per_tick unchanged.
    base = yield_of(mineral_richness=5.0, mine_count=2)
    scaled = yield_of(mineral_richness=5.0, mine_count=2, dissent_modifier=1.0)
    assert scaled["minerals_per_tick"] == base["minerals_per_tick"]


def test_compute_territory_yield_modifier_1_no_change_to_fuel():
    # modifier=1.0 must leave fuel_per_tick unchanged.
    base = yield_of(fuel_richness=4.0, refinery_count=3)
    scaled = yield_of(fuel_richness=4.0, refinery_count=3, dissent_modifier=1.0)
    assert scaled["fuel_per_tick"] == base["fuel_per_tick"]


# ---------------------------------------------------------------------------
# Minerals and fuel are both scaled by dissent_modifier
# ---------------------------------------------------------------------------

def test_compute_territory_yield_modifier_half_halves_minerals():
    # modifier=0.5: round(raw_minerals * 0.5) = round(10 * 0.5) = 5
    # mine at richness 5.0 -> raw = 10; 10 * 0.5 = 5
    y = yield_of(mineral_richness=5.0, mine_count=1, dissent_modifier=0.5)
    assert y["minerals_per_tick"] == 5


def test_compute_territory_yield_modifier_half_halves_fuel():
    # modifier=0.5: round(raw_fuel * 0.5) = round(10 * 0.5) = 5
    # refinery at richness 5.0 -> raw = 10; 10 * 0.5 = 5
    y = yield_of(fuel_richness=5.0, refinery_count=1, dissent_modifier=0.5)
    assert y["fuel_per_tick"] == 5


def test_compute_territory_yield_modifier_half_both_resources_scaled():
    # With one mine and one refinery, both outputs should be halved together.
    # mineral_richness=5.0 -> raw=10 -> scaled=5
    # fuel_richness=4.0 -> raw=8 -> scaled=4
    y = yield_of(
        mineral_richness=5.0,
        fuel_richness=4.0,
        mine_count=1,
        refinery_count=1,
        dissent_modifier=0.5,
    )
    assert y["minerals_per_tick"] == 5
    assert y["fuel_per_tick"] == 4


def test_compute_territory_yield_modifier_zero_suppresses_minerals():
    # modifier=0.0: round(raw * 0.0) = 0 -- full suppression.
    y = yield_of(mineral_richness=5.0, mine_count=3, dissent_modifier=0.0)
    assert y["minerals_per_tick"] == 0


def test_compute_territory_yield_modifier_zero_suppresses_fuel():
    # modifier=0.0: round(raw * 0.0) = 0 -- full suppression.
    y = yield_of(fuel_richness=5.0, refinery_count=3, dissent_modifier=0.0)
    assert y["fuel_per_tick"] == 0


# ---------------------------------------------------------------------------
# Currency income is NOT scaled by dissent_modifier
# ---------------------------------------------------------------------------

def test_compute_territory_yield_currency_income_unaffected_by_modifier():
    # Dissent suppresses production but NOT currency income.
    base_income = yield_of(mine_count=1)["currency_income_per_tick"]
    suppressed_income = yield_of(mine_count=1, dissent_modifier=0.0)["currency_income_per_tick"]
    assert suppressed_income == base_income


def test_compute_territory_yield_currency_income_unaffected_by_half_modifier():
    base_income = yield_of(mine_count=1, refinery_count=1)["currency_income_per_tick"]
    half_income = yield_of(mine_count=1, refinery_count=1, dissent_modifier=0.5)["currency_income_per_tick"]
    assert half_income == base_income


# ---------------------------------------------------------------------------
# Currency upkeep is NOT scaled by dissent_modifier
# ---------------------------------------------------------------------------

def test_compute_territory_yield_currency_upkeep_unaffected_by_modifier():
    # Fighter upkeep must be paid regardless of dissent level.
    base_upkeep = yield_of(stationed_fighters=100)["currency_upkeep_per_tick"]
    suppressed_upkeep = yield_of(stationed_fighters=100, dissent_modifier=0.0)["currency_upkeep_per_tick"]
    assert suppressed_upkeep == base_upkeep


def test_compute_territory_yield_currency_upkeep_unaffected_by_half_modifier():
    base_upkeep = yield_of(stationed_fighters=50)["currency_upkeep_per_tick"]
    half_upkeep = yield_of(stationed_fighters=50, dissent_modifier=0.5)["currency_upkeep_per_tick"]
    assert half_upkeep == base_upkeep


# ---------------------------------------------------------------------------
# currency_net_per_tick is derived from unscaled income/upkeep
# ---------------------------------------------------------------------------

def test_compute_territory_yield_net_currency_unaffected_by_modifier():
    # net = income - upkeep, both unscaled; net must be identical regardless of modifier.
    base = yield_of(mine_count=1, stationed_fighters=50)
    suppressed = yield_of(mine_count=1, stationed_fighters=50, dissent_modifier=0.0)
    assert suppressed["currency_net_per_tick"] == base["currency_net_per_tick"]


# ---------------------------------------------------------------------------
# Rounding: dissent_modifier produces integer outputs via round()
# ---------------------------------------------------------------------------

def test_compute_territory_yield_dissent_modifier_minerals_are_int():
    # round(raw * modifier) must always yield an int, not a float.
    y = yield_of(mineral_richness=3.0, mine_count=2, dissent_modifier=0.75)
    assert isinstance(y["minerals_per_tick"], int)


def test_compute_territory_yield_dissent_modifier_fuel_are_int():
    y = yield_of(fuel_richness=3.0, refinery_count=2, dissent_modifier=0.75)
    assert isinstance(y["fuel_per_tick"], int)


def test_compute_territory_yield_dissent_modifier_rounding_applied():
    # mineral_richness=3.0, mine_count=1 -> raw=6
    # modifier=0.75 -> 6 * 0.75 = 4.5 -> round(4.5) = 4 (banker's rounding: nearest even)
    y = yield_of(mineral_richness=3.0, mine_count=1, dissent_modifier=0.75)
    assert y["minerals_per_tick"] == round(6 * 0.75)


# ---------------------------------------------------------------------------
# Integration: dissent_production_modifier output flows correctly into
# compute_territory_yield as dissent_modifier
# ---------------------------------------------------------------------------

def test_dissent_modifier_pipeline_zero_dissent_no_penalty():
    # dissent=0 -> modifier=1.0 -> no production change.
    modifier = dissent_production_modifier(0)
    y = yield_of(mineral_richness=5.0, mine_count=1, dissent_modifier=modifier)
    # unmodified: max(5, round(5*2)) = 10
    assert y["minerals_per_tick"] == 10


def test_dissent_modifier_pipeline_full_suppression():
    # dissent=100 -> modifier=0.0 -> all production zeroed.
    modifier = dissent_production_modifier(100)
    y = yield_of(
        mineral_richness=5.0,
        fuel_richness=5.0,
        mine_count=3,
        refinery_count=3,
        dissent_modifier=modifier,
    )
    assert y["minerals_per_tick"] == 0
    assert y["fuel_per_tick"] == 0


def test_dissent_modifier_pipeline_anchor_halves_production():
    # dissent=75 -> modifier approx 0.50 -> minerals should be approximately half of raw.
    modifier = dissent_production_modifier(75)
    raw = yield_of(mineral_richness=5.0, mine_count=2)["minerals_per_tick"]  # = 20
    scaled = yield_of(mineral_richness=5.0, mine_count=2, dissent_modifier=modifier)["minerals_per_tick"]
    # round(20 * 0.50) = 10; allow abs=1 for rounding at the half-unit boundary
    assert scaled == pytest.approx(raw * 0.50, abs=1)


def test_dissent_modifier_pipeline_currency_immune_at_anchor():
    # Even at the 75-dissent anchor, currency income must be unchanged.
    modifier = dissent_production_modifier(75)
    base_income = yield_of(mine_count=1)["currency_income_per_tick"]
    scaled_income = yield_of(mine_count=1, dissent_modifier=modifier)["currency_income_per_tick"]
    assert scaled_income == base_income
