"""
Tests for the tutorial service pure functions.

The tutorial guides new players through 4 steps:
  Step 1: Build a mine       → reward +500 minerals, +500 currency
  Step 2: Build a refinery   → reward +500 fuel, +500 currency
  Step 3: View Planets tab   → UI step, no resource reward (auto-advances to 4)
  Step 4: Build a shipyard   → reward +1000 currency

All functions are pure (no DB dependency); no fixtures needed.

Service module: backend/app/services/tutorial.py
"""
from app.services.tutorial import (
    get_facility_tutorial_step,
    get_tutorial_reward,
    should_complete_step,
    next_step,
)


# ===========================================================================
# get_facility_tutorial_step
# ===========================================================================

class TestGetFacilityTutorialStep:
    """Maps facility type strings to the tutorial step they unlock."""

    # --- Tutorial facility types ---

    def test_mine_maps_to_step_1(self):
        assert get_facility_tutorial_step("mine") == 1

    def test_refinery_maps_to_step_2(self):
        assert get_facility_tutorial_step("refinery") == 2

    def test_shipyard_maps_to_step_4(self):
        # Step 3 is a UI step (no facility trigger); step 4 is triggered by shipyard.
        assert get_facility_tutorial_step("shipyard") == 4

    # --- Non-tutorial facility types ---

    def test_propaganda_office_returns_none(self):
        assert get_facility_tutorial_step("propaganda_office") is None

    def test_fleet_returns_none(self):
        # "fleet" is not a facility type but must not accidentally match anything.
        assert get_facility_tutorial_step("fleet") is None

    def test_barracks_returns_none(self):
        assert get_facility_tutorial_step("barracks") is None

    def test_empty_string_returns_none(self):
        assert get_facility_tutorial_step("") is None

    def test_unknown_type_returns_none(self):
        assert get_facility_tutorial_step("totally_made_up_facility") is None

    # --- Case sensitivity ---

    def test_mine_uppercase_returns_none(self):
        # Matching must be exact lowercase; "Mine" is not a valid facility key.
        assert get_facility_tutorial_step("Mine") is None

    def test_refinery_uppercase_returns_none(self):
        assert get_facility_tutorial_step("Refinery") is None

    def test_shipyard_uppercase_returns_none(self):
        assert get_facility_tutorial_step("Shipyard") is None


# ===========================================================================
# get_tutorial_reward
# ===========================================================================

class TestGetTutorialReward:
    """Returns the resource dict granted when a tutorial step is completed."""

    # --- Step 1: mine completed ---

    def test_step_1_minerals_reward(self):
        assert get_tutorial_reward(1)["minerals"] == 500

    def test_step_1_fuel_reward_is_zero(self):
        assert get_tutorial_reward(1)["fuel"] == 0

    def test_step_1_currency_reward(self):
        assert get_tutorial_reward(1)["currency"] == 500

    # --- Step 2: refinery completed ---

    def test_step_2_minerals_reward_is_zero(self):
        assert get_tutorial_reward(2)["minerals"] == 0

    def test_step_2_fuel_reward(self):
        assert get_tutorial_reward(2)["fuel"] == 500

    def test_step_2_currency_reward(self):
        assert get_tutorial_reward(2)["currency"] == 500

    # --- Step 3: Planets page visit ---

    def test_step_3_minerals_reward(self):
        assert get_tutorial_reward(3)["minerals"] == 100

    def test_step_3_fuel_reward(self):
        assert get_tutorial_reward(3)["fuel"] == 100

    def test_step_3_currency_reward(self):
        assert get_tutorial_reward(3)["currency"] == 500

    # --- Step 4: shipyard completed ---

    def test_step_4_minerals_reward_is_zero(self):
        assert get_tutorial_reward(4)["minerals"] == 0

    def test_step_4_fuel_reward_is_zero(self):
        assert get_tutorial_reward(4)["fuel"] == 0

    def test_step_4_currency_reward(self):
        assert get_tutorial_reward(4)["currency"] == 1000

    # --- Out-of-range / unknown steps ---

    def test_step_0_returns_zero_reward(self):
        r = get_tutorial_reward(0)
        assert r["minerals"] == 0
        assert r["fuel"] == 0
        assert r["currency"] == 0

    def test_step_99_returns_zero_reward(self):
        r = get_tutorial_reward(99)
        assert r["minerals"] == 0
        assert r["fuel"] == 0
        assert r["currency"] == 0

    def test_negative_step_returns_zero_reward(self):
        r = get_tutorial_reward(-1)
        assert r["minerals"] == 0
        assert r["fuel"] == 0
        assert r["currency"] == 0

    # --- Return type guarantees ---

    def test_reward_dict_has_required_keys(self):
        r = get_tutorial_reward(1)
        assert set(r.keys()) >= {"minerals", "fuel", "currency"}

    def test_reward_values_are_ints_step_1(self):
        r = get_tutorial_reward(1)
        assert all(isinstance(v, int) for v in r.values())

    def test_reward_values_are_ints_step_4(self):
        r = get_tutorial_reward(4)
        assert all(isinstance(v, int) for v in r.values())

    def test_reward_values_are_ints_unknown_step(self):
        r = get_tutorial_reward(99)
        assert all(isinstance(v, int) for v in r.values())


# ===========================================================================
# should_complete_step
# ===========================================================================

class TestShouldCompleteStep:
    """
    Returns True only when the facility type exactly matches what the player's
    current tutorial step requires.
    """

    # --- Correct facility at correct step (True cases) ---

    def test_mine_at_step_1_returns_true(self):
        assert should_complete_step(1, "mine") is True

    def test_refinery_at_step_2_returns_true(self):
        assert should_complete_step(2, "refinery") is True

    def test_shipyard_at_step_4_returns_true(self):
        assert should_complete_step(4, "shipyard") is True

    # --- Wrong facility at correct step (False cases) ---

    def test_refinery_at_step_1_returns_false(self):
        # Player is on step 1 but built a refinery — does not satisfy step 1.
        assert should_complete_step(1, "refinery") is False

    def test_shipyard_at_step_1_returns_false(self):
        assert should_complete_step(1, "shipyard") is False

    def test_mine_at_step_2_returns_false(self):
        # Player is on step 2 but built a mine — step 1 is already past.
        assert should_complete_step(2, "mine") is False

    def test_shipyard_at_step_2_returns_false(self):
        assert should_complete_step(2, "shipyard") is False

    def test_mine_at_step_4_returns_false(self):
        # Player is on step 4; building a mine does not satisfy step 4.
        assert should_complete_step(4, "mine") is False

    def test_refinery_at_step_4_returns_false(self):
        assert should_complete_step(4, "refinery") is False

    # --- Correct facility but already past that step (False cases) ---

    def test_mine_at_step_2_already_past_step_1(self):
        # Building a mine when on step 2 should not re-trigger step 1.
        assert should_complete_step(2, "mine") is False

    def test_mine_at_step_3_already_past_step_1(self):
        assert should_complete_step(3, "mine") is False

    def test_refinery_at_step_3_already_past_step_2(self):
        assert should_complete_step(3, "refinery") is False

    def test_mine_at_step_4_already_past_step_1(self):
        assert should_complete_step(4, "mine") is False

    def test_refinery_at_step_4_already_past_step_2(self):
        assert should_complete_step(4, "refinery") is False

    # --- Step 3 is a UI step: no facility ever satisfies it ---

    def test_mine_at_step_3_returns_false(self):
        # Step 3 is triggered by the UI, not a facility.  Mine must never satisfy it.
        assert should_complete_step(3, "mine") is False

    def test_refinery_at_step_3_returns_false(self):
        assert should_complete_step(3, "refinery") is False

    def test_shipyard_at_step_3_returns_false(self):
        # Even if a shipyard matches step 4, it must not satisfy step 3.
        assert should_complete_step(3, "shipyard") is False

    def test_propaganda_office_at_step_3_returns_false(self):
        # A non-tutorial facility also must not accidentally satisfy step 3.
        assert should_complete_step(3, "propaganda_office") is False

    # --- Tutorial complete: step 5+ always False ---

    def test_shipyard_at_step_5_tutorial_complete(self):
        # Step 5 means the tutorial is finished; no facility should trigger anything.
        assert should_complete_step(5, "shipyard") is False

    def test_mine_at_step_5_tutorial_complete(self):
        assert should_complete_step(5, "mine") is False

    def test_refinery_at_step_5_tutorial_complete(self):
        assert should_complete_step(5, "refinery") is False

    def test_shipyard_at_step_99_tutorial_complete(self):
        # Any step beyond 4 is past the end; must always be False.
        assert should_complete_step(99, "shipyard") is False

    def test_mine_at_step_6_tutorial_complete(self):
        assert should_complete_step(6, "mine") is False

    # --- Non-tutorial facility types: always False regardless of step ---

    def test_propaganda_office_at_step_1_returns_false(self):
        assert should_complete_step(1, "propaganda_office") is False

    def test_barracks_at_step_4_returns_false(self):
        assert should_complete_step(4, "barracks") is False

    def test_empty_string_at_step_1_returns_false(self):
        assert should_complete_step(1, "") is False

    # --- Return type ---

    def test_true_case_returns_bool_not_truthy(self):
        result = should_complete_step(1, "mine")
        assert result is True

    def test_false_case_returns_bool_not_falsy(self):
        result = should_complete_step(1, "refinery")
        assert result is False


# ===========================================================================
# next_step
# ===========================================================================

class TestNextStep:
    """Steps advance sequentially 1→2→3→4→5; step 5 is clamped (tutorial done)."""

    def test_step_1_advances_to_2(self):
        assert next_step(1) == 2

    def test_step_2_advances_to_3(self):
        assert next_step(2) == 3

    def test_step_3_advances_to_4(self):
        assert next_step(3) == 4

    def test_step_4_advances_to_5(self):
        # Step 5 is the terminal "done" state.
        assert next_step(4) == 5

    def test_step_5_clamps_to_5(self):
        # Calling next_step when already done must not overflow to 6.
        assert next_step(5) == 5

    def test_step_5_clamp_is_idempotent(self):
        # Repeated calls on a completed tutorial stay at 5.
        assert next_step(next_step(5)) == 5

    def test_return_value_is_int(self):
        assert isinstance(next_step(1), int)

    def test_return_value_is_int_at_clamp(self):
        assert isinstance(next_step(5), int)

    # --- Confirm sequential completeness: all 4 steps chain correctly ---

    def test_full_tutorial_sequence_1_to_5(self):
        step = 1
        step = next_step(step)
        assert step == 2
        step = next_step(step)
        assert step == 3
        step = next_step(step)
        assert step == 4
        step = next_step(step)
        assert step == 5
        # One more call must clamp, not overflow.
        step = next_step(step)
        assert step == 5
