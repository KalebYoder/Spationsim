"""
Tests for per-territory resource yield calculation.

Production formula (matches tick.py):
  mine:     normal  → max(5, round(mineral_richness × 2))
            anomaly → round(mineral_richness × 2 + 10)
  refinery: normal  → max(5, round(fuel_richness × 2))
            anomaly → round(fuel_richness × 2 + 10)

Currency income: 500 per territory with >= 1 active mine or refinery (not per facility).
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
# Mine production — normal territory
# ---------------------------------------------------------------------------

def test_mine_richness_1_clamps_to_5():
    # max(5, round(1 × 2)) = max(5, 2) = 5
    y = yield_of(mineral_richness=1.0, mine_count=1)
    assert y["minerals_per_tick"] == 5


def test_mine_richness_2_clamps_to_5():
    # max(5, round(2 × 2)) = max(5, 4) = 5
    y = yield_of(mineral_richness=2.0, mine_count=1)
    assert y["minerals_per_tick"] == 5


def test_mine_richness_3_produces_6():
    # max(5, round(3 × 2)) = max(5, 6) = 6
    y = yield_of(mineral_richness=3.0, mine_count=1)
    assert y["minerals_per_tick"] == 6


def test_mine_richness_4_produces_8():
    # max(5, round(4 × 2)) = max(5, 8) = 8
    y = yield_of(mineral_richness=4.0, mine_count=1)
    assert y["minerals_per_tick"] == 8


def test_mine_richness_5_produces_10():
    # max(5, round(5 × 2)) = max(5, 10) = 10
    y = yield_of(mineral_richness=5.0, mine_count=1)
    assert y["minerals_per_tick"] == 10


def test_two_mines_double_production():
    # 2 × max(5, round(3 × 2)) = 2 × 6 = 12
    y = yield_of(mineral_richness=3.0, mine_count=2)
    assert y["minerals_per_tick"] == 12


def test_three_mines_triple_production():
    y = yield_of(mineral_richness=5.0, mine_count=3)
    assert y["minerals_per_tick"] == 30


# ---------------------------------------------------------------------------
# Refinery production — normal territory
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
    # round(5 × 2 + 10) = round(20) = 20
    y = yield_of(territory_type="anomaly", mineral_richness=5.0, mine_count=1)
    assert y["minerals_per_tick"] == 20


def test_anomaly_mine_richness_7_produces_24():
    # round(7 × 2 + 10) = round(24) = 24
    y = yield_of(territory_type="anomaly", mineral_richness=7.0, mine_count=1)
    assert y["minerals_per_tick"] == 24


def test_anomaly_mine_richness_10_produces_30():
    # round(10 × 2 + 10) = round(30) = 30
    y = yield_of(territory_type="anomaly", mineral_richness=10.0, mine_count=1)
    assert y["minerals_per_tick"] == 30


def test_anomaly_refinery_richness_8_produces_26():
    # round(8 × 2 + 10) = round(26) = 26
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
    y = yield_of(mine_count=1)
    assert y["currency_income_per_tick"] == 500


def test_one_refinery_triggers_currency_income():
    y = yield_of(refinery_count=1)
    assert y["currency_income_per_tick"] == 500


def test_mine_and_refinery_together_still_500():
    # Income is per territory, not per facility
    y = yield_of(mine_count=1, refinery_count=1)
    assert y["currency_income_per_tick"] == 500


def test_five_mines_still_500_income():
    y = yield_of(mine_count=5)
    assert y["currency_income_per_tick"] == 500


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
    # income 500, upkeep 2 × 50 = 100 → net 400
    y = yield_of(mine_count=1, stationed_fighters=50)
    assert y["currency_net_per_tick"] == 400


def test_net_currency_zero_at_break_even():
    # income 500, upkeep 2 × 250 = 500 → net 0
    y = yield_of(mine_count=1, stationed_fighters=250)
    assert y["currency_net_per_tick"] == 0


def test_net_currency_negative_when_upkeep_exceeds_income():
    # income 500, upkeep 2 × 300 = 600 → net -100
    y = yield_of(mine_count=1, stationed_fighters=300)
    assert y["currency_net_per_tick"] == -100


def test_net_currency_negative_with_no_income_and_fighters():
    # income 0, upkeep 2 × 10 = 20 → net -20
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
# QA-pass additions — gaps not covered by the developer-written tests above
# ===========================================================================

# ---------------------------------------------------------------------------
# Fractional richness values (DB column is Numeric(4,2); 2.5 is a real input)
# ---------------------------------------------------------------------------

def test_mine_richness_fractional_below_floor_boundary():
    # max(5, round(2.4 × 2)) = max(5, round(4.8)) = max(5, 5) = 5
    # Verifies fractional richness that rounds to exactly 5 still clamps correctly
    y = yield_of(mineral_richness=2.4, mine_count=1)
    assert y["minerals_per_tick"] == 5


def test_mine_richness_fractional_at_floor_boundary():
    # max(5, round(2.5 × 2)) = max(5, round(5.0)) = max(5, 5) = 5
    # 2.5 is the first value where r*2 == 5; still hits the floor
    y = yield_of(mineral_richness=2.5, mine_count=1)
    assert y["minerals_per_tick"] == 5


def test_mine_richness_fractional_just_above_floor_boundary():
    # max(5, round(2.6 × 2)) = max(5, round(5.2)) = max(5, 5) = 5
    # 2.6 still rounds down to 5, still clamped
    y = yield_of(mineral_richness=2.6, mine_count=1)
    assert y["minerals_per_tick"] == 5


def test_mine_richness_fractional_escapes_floor():
    # max(5, round(3.5 × 2)) = max(5, round(7.0)) = max(5, 7) = 7
    # 3.5 produces 7, above the floor of 5
    y = yield_of(mineral_richness=3.5, mine_count=1)
    assert y["minerals_per_tick"] == 7


def test_mine_richness_fractional_midpoint_rounding():
    # round(1.75 × 2) = round(3.5) — Python banker's rounding rounds to 4 (nearest even)
    # max(5, 4) = 5; confirms the floor absorbs banker's rounding artifacts at low richness
    y = yield_of(mineral_richness=1.75, mine_count=1)
    assert y["minerals_per_tick"] == 5


def test_refinery_richness_fractional_midpoint_rounding():
    # round(1.75 × 2) = round(3.5) = 4 (banker's rounding); max(5, 4) = 5
    # Parallel check for refinery to ensure symmetric formula behavior
    y = yield_of(fuel_richness=1.75, refinery_count=1)
    assert y["fuel_per_tick"] == 5


def test_mine_richness_fractional_midpoint_above_floor():
    # round(3.75 × 2) = round(7.5) = 8 (banker's rounding rounds to even: 8)
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
    # max(5, round(0 × 2)) = max(5, 0) = 5
    # A planet with a mine but richness=0 still produces the minimum floor output
    y = yield_of(mineral_richness=0.0, mine_count=1)
    assert y["minerals_per_tick"] == 5


def test_refinery_zero_richness_clamps_to_floor():
    # max(5, round(0 × 2)) = max(5, 0) = 5
    y = yield_of(fuel_richness=0.0, refinery_count=1)
    assert y["fuel_per_tick"] == 5


def test_anomaly_mine_zero_richness_produces_ten():
    # round(0 × 2 + 10) = 10; anomaly has no floor, bonus alone drives output
    y = yield_of(territory_type="anomaly", mineral_richness=0.0, mine_count=1)
    assert y["minerals_per_tick"] == 10


def test_anomaly_refinery_zero_richness_produces_ten():
    # round(0 × 2 + 10) = 10; symmetric with mine case
    y = yield_of(territory_type="anomaly", fuel_richness=0.0, refinery_count=1)
    assert y["fuel_per_tick"] == 10


def test_anomaly_zero_richness_beats_normal_zero_richness():
    # Anomaly bonus (10) must always exceed normal floor (5) even at richness=0
    normal = yield_of(territory_type="normal", mineral_richness=0.0, mine_count=1)
    anomaly = yield_of(territory_type="anomaly", mineral_richness=0.0, mine_count=1)
    assert anomaly["minerals_per_tick"] > normal["minerals_per_tick"]


# ---------------------------------------------------------------------------
# Currency income — ordering insensitivity (mine_count=0, refinery_count>0)
# ---------------------------------------------------------------------------

def test_currency_income_triggered_by_refinery_only_no_mine():
    # Verifies the condition `mine_count + refinery_count > 0` fires when
    # mine_count is exactly zero; guards against an accidental mine-first short-circuit
    y = yield_of(mine_count=0, refinery_count=1)
    assert y["currency_income_per_tick"] == 500


def test_currency_income_triggered_by_mine_only_no_refinery():
    # Symmetric: guards against a refinery-first short-circuit
    y = yield_of(mine_count=1, refinery_count=0)
    assert y["currency_income_per_tick"] == 500


def test_anomaly_territory_with_mine_still_earns_500_currency():
    # Currency income formula must apply regardless of territory_type
    y = yield_of(territory_type="anomaly", mine_count=1)
    assert y["currency_income_per_tick"] == 500


# ---------------------------------------------------------------------------
# Negative mine_count / refinery_count — document current behavior
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


def test_negative_mine_count_does_not_trigger_currency_income():
    # mine_count + refinery_count = -1 + 0 = -1, which is not > 0
    # Currency income gate must not fire for negative facility counts
    y = yield_of(mine_count=-1, refinery_count=0)
    assert y["currency_income_per_tick"] == 0


def test_negative_refinery_count_does_not_trigger_currency_income():
    # mine_count + refinery_count = 0 + (-1) = -1, which is not > 0
    y = yield_of(mine_count=0, refinery_count=-1)
    assert y["currency_income_per_tick"] == 0


# ---------------------------------------------------------------------------
# Large stationed_fighters values
# ---------------------------------------------------------------------------

def test_large_stationed_fighters_upkeep_is_linear():
    # 10,000 fighters × 2 = 20,000 upkeep; confirms no integer overflow or cap
    y = yield_of(stationed_fighters=10_000)
    assert y["currency_upkeep_per_tick"] == 20_000


def test_large_stationed_fighters_net_currency_deeply_negative():
    # A heavily garrisoned territory with no income should drain significantly
    y = yield_of(mine_count=0, refinery_count=0, stationed_fighters=10_000)
    assert y["currency_net_per_tick"] == -20_000


def test_large_fighters_with_income_still_net_negative():
    # 500 income, 10,000 × 2 = 20,000 upkeep → -19,500 net
    y = yield_of(mine_count=1, stationed_fighters=10_000)
    assert y["currency_net_per_tick"] == -19_500


# ---------------------------------------------------------------------------
# Constants are in sync with tick.py
# ---------------------------------------------------------------------------

def test_currency_income_constant_matches_tick_py():
    # tick.py line 142: currency_delta = 500 * income_territory_count
    # The service constant CURRENCY_INCOME_PER_TERRITORY must equal 500
    from app.services.territory_yield import CURRENCY_INCOME_PER_TERRITORY
    assert CURRENCY_INCOME_PER_TERRITORY == 500


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
    # normal: max(5, round(0.1 × 2)) = max(5, 0) = 5
    # anomaly: round(0.1 × 2 + 10) = round(10.2) = 10  — no floor applied
    # If the anomaly formula accidentally applied the normal floor, both would be 5
    normal = yield_of(territory_type="normal", mineral_richness=0.1, mine_count=1)
    anomaly = yield_of(territory_type="anomaly", mineral_richness=0.1, mine_count=1)
    assert normal["minerals_per_tick"] == 5
    assert anomaly["minerals_per_tick"] == 10


# ---------------------------------------------------------------------------
# Multi-mine / multi-refinery scaling with fractional richness
# ---------------------------------------------------------------------------

def test_multiple_mines_scale_correctly_with_fractional_richness():
    # 3 mines at richness 3.5: each produces max(5, round(7.0)) = 7 → total 21
    y = yield_of(mineral_richness=3.5, mine_count=3)
    assert y["minerals_per_tick"] == 21


def test_multiple_refineries_scale_correctly_with_fractional_richness():
    # 2 refineries at richness 4.5: each produces max(5, round(9.0)) = 9 → total 18
    y = yield_of(fuel_richness=4.5, refinery_count=2)
    assert y["fuel_per_tick"] == 18


# ---------------------------------------------------------------------------
# Return type guarantees for fractional inputs
# ---------------------------------------------------------------------------

def test_all_values_are_ints_with_fractional_richness():
    # Fractional richness must still produce integer outputs after round()
    y = yield_of(mineral_richness=2.5, fuel_richness=3.7, mine_count=2, refinery_count=1, stationed_fighters=7)
    assert all(isinstance(v, int) for v in y.values())
