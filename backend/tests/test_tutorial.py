"""
Tests for the tutorial service pure functions.

The tutorial guides new players through 10 steps:
  Step 1:  Build a mine              → reward +500 minerals, +500 currency
  Step 2:  Build a refinery          → reward +500 fuel, +500 currency
  Step 3:  View Planets tab          → UI step, reward +100 minerals, +100 fuel, +500 currency
  Step 4:  Build a shipyard          → reward +1000 currency
  Step 5:  Manufacture a fighter     → reward +1000 currency
  Step 6:  View Military tab         → view/acknowledgement step, no reward
  Step 7:  Dispatch a fleet          → reward +500 minerals, +500 fuel
  Step 8:  Manufacture a colony ship → reward +500 minerals, +1000 fuel
  Step 9:  View Colonization guide   → view/acknowledgement step, no reward
  Step 10: Colonize a territory      → reward +1000 minerals, +1000 fuel, +2000 currency

Step 11 is the "tutorial complete" sentinel; it clamps and never advances.

All functions are pure (no DB dependency); no fixtures needed.

Service module: backend/app/services/tutorial.py
"""
from app.services.tutorial import (
    get_facility_tutorial_step,
    get_tutorial_reward,
    should_complete_step,
    next_step,
    get_action_tutorial_step,
    should_complete_step_on_action,
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

    # --- Step 5: manufacture fighter ---

    def test_step_5_minerals_reward_is_zero(self):
        assert get_tutorial_reward(5)["minerals"] == 0

    def test_step_5_fuel_reward_is_zero(self):
        assert get_tutorial_reward(5)["fuel"] == 0

    def test_step_5_currency_reward(self):
        assert get_tutorial_reward(5)["currency"] == 1000

    # --- Step 6: view Military tab (no resource reward) ---

    def test_step_6_minerals_reward_is_zero(self):
        assert get_tutorial_reward(6)["minerals"] == 0

    def test_step_6_fuel_reward_is_zero(self):
        assert get_tutorial_reward(6)["fuel"] == 0

    def test_step_6_currency_reward_is_zero(self):
        assert get_tutorial_reward(6)["currency"] == 0

    # --- Step 7: dispatch fleet ---

    def test_step_7_minerals_reward(self):
        assert get_tutorial_reward(7)["minerals"] == 500

    def test_step_7_fuel_reward(self):
        assert get_tutorial_reward(7)["fuel"] == 500

    def test_step_7_currency_reward_is_zero(self):
        assert get_tutorial_reward(7)["currency"] == 0

    # --- Step 8: manufacture colony ship ---

    def test_step_8_minerals_reward(self):
        assert get_tutorial_reward(8)["minerals"] == 500

    def test_step_8_fuel_reward(self):
        assert get_tutorial_reward(8)["fuel"] == 1000

    def test_step_8_currency_reward_is_zero(self):
        assert get_tutorial_reward(8)["currency"] == 0

    # --- Step 9: view Colonization guide (no resource reward) ---

    def test_step_9_minerals_reward_is_zero(self):
        assert get_tutorial_reward(9)["minerals"] == 0

    def test_step_9_fuel_reward_is_zero(self):
        assert get_tutorial_reward(9)["fuel"] == 0

    def test_step_9_currency_reward_is_zero(self):
        assert get_tutorial_reward(9)["currency"] == 0

    # --- Step 10: colonize territory ---

    def test_step_10_minerals_reward(self):
        assert get_tutorial_reward(10)["minerals"] == 1000

    def test_step_10_fuel_reward(self):
        assert get_tutorial_reward(10)["fuel"] == 1000

    def test_step_10_currency_reward(self):
        assert get_tutorial_reward(10)["currency"] == 2000

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

    # Step 11 is the "done" sentinel — it has no reward.
    def test_step_11_returns_zero_reward(self):
        r = get_tutorial_reward(11)
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

    def test_reward_values_are_ints_step_10(self):
        r = get_tutorial_reward(10)
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

    # --- Steps 5-10 are action/view steps: no facility ever satisfies them ---

    def test_shipyard_at_step_5_returns_false(self):
        # Step 5 is triggered by manufacture_fighter action, not a facility build.
        assert should_complete_step(5, "shipyard") is False

    def test_mine_at_step_5_returns_false(self):
        assert should_complete_step(5, "mine") is False

    def test_refinery_at_step_5_returns_false(self):
        assert should_complete_step(5, "refinery") is False

    def test_mine_at_step_6_returns_false(self):
        # Step 6 is a view/acknowledgement step; no facility satisfies it.
        assert should_complete_step(6, "mine") is False

    def test_shipyard_at_step_7_returns_false(self):
        # Step 7 is triggered by dispatch_fleet action, not a facility build.
        assert should_complete_step(7, "shipyard") is False

    def test_mine_at_step_8_returns_false(self):
        # Step 8 is triggered by manufacture_colony_ship action, not a facility build.
        assert should_complete_step(8, "mine") is False

    def test_mine_at_step_9_returns_false(self):
        # Step 9 is a view/acknowledgement step; no facility satisfies it.
        assert should_complete_step(9, "mine") is False

    def test_mine_at_step_10_returns_false(self):
        # Step 10 is triggered by colonize_territory action, not a facility build.
        assert should_complete_step(10, "mine") is False

    # --- Tutorial complete: step 11+ always False ---

    def test_shipyard_at_step_11_tutorial_complete(self):
        # Step 11 means the tutorial is finished; no facility should trigger anything.
        assert should_complete_step(11, "shipyard") is False

    def test_mine_at_step_11_tutorial_complete(self):
        assert should_complete_step(11, "mine") is False

    def test_refinery_at_step_11_tutorial_complete(self):
        assert should_complete_step(11, "refinery") is False

    def test_shipyard_at_step_99_tutorial_complete(self):
        # Any step beyond 10 is past the end; must always be False.
        assert should_complete_step(99, "shipyard") is False

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
    """Steps advance sequentially 1→2→…→10→11; step 11 is clamped (tutorial done)."""

    def test_step_1_advances_to_2(self):
        assert next_step(1) == 2

    def test_step_2_advances_to_3(self):
        assert next_step(2) == 3

    def test_step_3_advances_to_4(self):
        assert next_step(3) == 4

    def test_step_4_advances_to_5(self):
        assert next_step(4) == 5

    def test_step_5_advances_to_6(self):
        # Step 5 is now an active tutorial step, not the terminal state.
        assert next_step(5) == 6

    def test_step_6_advances_to_7(self):
        assert next_step(6) == 7

    def test_step_7_advances_to_8(self):
        assert next_step(7) == 8

    def test_step_8_advances_to_9(self):
        assert next_step(8) == 9

    def test_step_9_advances_to_10(self):
        assert next_step(9) == 10

    def test_step_10_advances_to_11(self):
        # Step 11 is the terminal "done" sentinel.
        assert next_step(10) == 11

    def test_step_11_clamps_to_11(self):
        # Calling next_step when already done must not overflow to 12.
        assert next_step(11) == 11

    def test_step_11_clamp_is_idempotent(self):
        # Repeated calls on a completed tutorial stay at 11.
        assert next_step(next_step(11)) == 11

    def test_return_value_is_int(self):
        assert isinstance(next_step(1), int)

    def test_return_value_is_int_at_clamp(self):
        assert isinstance(next_step(11), int)

    # --- Confirm sequential completeness: all 10 steps chain correctly ---

    def test_full_tutorial_sequence_1_to_11(self):
        step = 1
        step = next_step(step)
        assert step == 2
        step = next_step(step)
        assert step == 3
        step = next_step(step)
        assert step == 4
        step = next_step(step)
        assert step == 5
        step = next_step(step)
        assert step == 6
        step = next_step(step)
        assert step == 7
        step = next_step(step)
        assert step == 8
        step = next_step(step)
        assert step == 9
        step = next_step(step)
        assert step == 10
        step = next_step(step)
        assert step == 11
        # One more call must clamp, not overflow.
        step = next_step(step)
        assert step == 11


# ===========================================================================
# get_action_tutorial_step
# ===========================================================================

class TestGetActionTutorialStep:
    """
    Maps player action strings to the tutorial step they complete.

    Mapping:
      "manufacture_fighter"     -> 5
      "dispatch_fleet"          -> 7
      "manufacture_colony_ship" -> 8
      "colonize_territory"      -> 10
      anything else             -> None
    """

    # --- Valid action strings ---

    def test_manufacture_fighter_maps_to_step_5(self):
        assert get_action_tutorial_step("manufacture_fighter") == 5

    def test_dispatch_fleet_maps_to_step_7(self):
        assert get_action_tutorial_step("dispatch_fleet") == 7

    def test_manufacture_colony_ship_maps_to_step_8(self):
        assert get_action_tutorial_step("manufacture_colony_ship") == 8

    def test_colonize_territory_maps_to_step_10(self):
        assert get_action_tutorial_step("colonize_territory") == 10

    # --- Non-matching action strings ---

    def test_send_probe_returns_none(self):
        assert get_action_tutorial_step("send_probe") is None

    def test_build_mine_returns_none(self):
        assert get_action_tutorial_step("build_mine") is None

    def test_empty_string_returns_none(self):
        assert get_action_tutorial_step("") is None

    def test_unknown_action_returns_none(self):
        assert get_action_tutorial_step("totally_made_up_action") is None

    def test_declare_war_returns_none(self):
        assert get_action_tutorial_step("declare_war") is None

    # --- Case sensitivity ---

    def test_manufacture_fighter_uppercase_returns_none(self):
        # Matching must be exact; "Manufacture_Fighter" must not match.
        assert get_action_tutorial_step("Manufacture_Fighter") is None

    def test_dispatch_fleet_uppercase_returns_none(self):
        assert get_action_tutorial_step("DISPATCH_FLEET") is None

    def test_manufacture_colony_ship_mixed_case_returns_none(self):
        assert get_action_tutorial_step("Manufacture_Colony_Ship") is None

    def test_colonize_territory_uppercase_returns_none(self):
        assert get_action_tutorial_step("COLONIZE_TERRITORY") is None

    # --- Return type ---

    def test_valid_action_returns_int(self):
        assert isinstance(get_action_tutorial_step("manufacture_fighter"), int)

    def test_invalid_action_returns_none_not_zero(self):
        # Must be None, not 0 or False.
        result = get_action_tutorial_step("send_probe")
        assert result is None


# ===========================================================================
# should_complete_step_on_action
# ===========================================================================

class TestShouldCompleteStepOnAction:
    """
    Returns True only if get_action_tutorial_step(action) == current_step.

    Steps 6 and 9 are view/acknowledgement steps — no action triggers them.
    Steps 11+ are past the tutorial — always False.
    """

    # --- Correct action at correct step (True cases) ---

    def test_manufacture_fighter_at_step_5_returns_true(self):
        assert should_complete_step_on_action(5, "manufacture_fighter") is True

    def test_dispatch_fleet_at_step_7_returns_true(self):
        assert should_complete_step_on_action(7, "dispatch_fleet") is True

    def test_manufacture_colony_ship_at_step_8_returns_true(self):
        assert should_complete_step_on_action(8, "manufacture_colony_ship") is True

    def test_colonize_territory_at_step_10_returns_true(self):
        assert should_complete_step_on_action(10, "colonize_territory") is True

    # --- Wrong action at each correct step (False cases) ---

    def test_dispatch_fleet_at_step_5_returns_false(self):
        # step 5 requires manufacture_fighter, not dispatch_fleet.
        assert should_complete_step_on_action(5, "dispatch_fleet") is False

    def test_colonize_territory_at_step_5_returns_false(self):
        assert should_complete_step_on_action(5, "colonize_territory") is False

    def test_manufacture_fighter_at_step_7_returns_false(self):
        # step 7 requires dispatch_fleet, not manufacture_fighter.
        assert should_complete_step_on_action(7, "manufacture_fighter") is False

    def test_colonize_territory_at_step_7_returns_false(self):
        assert should_complete_step_on_action(7, "colonize_territory") is False

    def test_manufacture_fighter_at_step_8_returns_false(self):
        # step 8 requires manufacture_colony_ship, not manufacture_fighter.
        assert should_complete_step_on_action(8, "manufacture_fighter") is False

    def test_dispatch_fleet_at_step_8_returns_false(self):
        assert should_complete_step_on_action(8, "dispatch_fleet") is False

    def test_manufacture_fighter_at_step_10_returns_false(self):
        # step 10 requires colonize_territory.
        assert should_complete_step_on_action(10, "manufacture_fighter") is False

    def test_dispatch_fleet_at_step_10_returns_false(self):
        assert should_complete_step_on_action(10, "dispatch_fleet") is False

    # --- Correct action but at wrong step (False cases) ---

    def test_manufacture_fighter_at_step_4_returns_false(self):
        # manufacture_fighter completes step 5, not step 4.
        assert should_complete_step_on_action(4, "manufacture_fighter") is False

    def test_manufacture_fighter_at_step_6_returns_false(self):
        # manufacture_fighter completes step 5, not step 6.
        assert should_complete_step_on_action(6, "manufacture_fighter") is False

    def test_dispatch_fleet_at_step_6_returns_false(self):
        # dispatch_fleet completes step 7, not step 6.
        assert should_complete_step_on_action(6, "dispatch_fleet") is False

    def test_colonize_territory_at_step_9_returns_false(self):
        # colonize_territory completes step 10, not step 9.
        assert should_complete_step_on_action(9, "colonize_territory") is False

    # --- Steps 6 and 9 are view steps: no action ever triggers them ---

    def test_manufacture_fighter_at_step_6_view_step_returns_false(self):
        assert should_complete_step_on_action(6, "manufacture_fighter") is False

    def test_dispatch_fleet_at_step_6_view_step_returns_false(self):
        assert should_complete_step_on_action(6, "dispatch_fleet") is False

    def test_manufacture_colony_ship_at_step_6_view_step_returns_false(self):
        assert should_complete_step_on_action(6, "manufacture_colony_ship") is False

    def test_colonize_territory_at_step_6_view_step_returns_false(self):
        assert should_complete_step_on_action(6, "colonize_territory") is False

    def test_manufacture_fighter_at_step_9_view_step_returns_false(self):
        assert should_complete_step_on_action(9, "manufacture_fighter") is False

    def test_dispatch_fleet_at_step_9_view_step_returns_false(self):
        assert should_complete_step_on_action(9, "dispatch_fleet") is False

    def test_manufacture_colony_ship_at_step_9_view_step_returns_false(self):
        assert should_complete_step_on_action(9, "manufacture_colony_ship") is False

    def test_colonize_territory_at_step_9_view_step_returns_false(self):
        assert should_complete_step_on_action(9, "colonize_territory") is False

    # --- Step 11+: tutorial complete, always False ---

    def test_manufacture_fighter_at_step_11_returns_false(self):
        assert should_complete_step_on_action(11, "manufacture_fighter") is False

    def test_colonize_territory_at_step_11_returns_false(self):
        assert should_complete_step_on_action(11, "colonize_territory") is False

    def test_manufacture_fighter_at_step_99_returns_false(self):
        assert should_complete_step_on_action(99, "manufacture_fighter") is False

    def test_colonize_territory_at_step_12_returns_false(self):
        assert should_complete_step_on_action(12, "colonize_territory") is False

    # --- Non-tutorial actions: always False regardless of step ---

    def test_send_probe_at_step_5_returns_false(self):
        assert should_complete_step_on_action(5, "send_probe") is False

    def test_empty_string_at_step_7_returns_false(self):
        assert should_complete_step_on_action(7, "") is False

    def test_unknown_action_at_step_10_returns_false(self):
        assert should_complete_step_on_action(10, "unknown_action") is False

    # --- Return type: strict bool ---

    def test_true_case_returns_strict_bool(self):
        result = should_complete_step_on_action(5, "manufacture_fighter")
        assert result is True

    def test_false_case_returns_strict_bool_not_none(self):
        result = should_complete_step_on_action(5, "dispatch_fleet")
        assert result is False

    def test_false_case_returns_strict_bool_not_zero(self):
        # Must be bool False, not integer 0 or None.
        result = should_complete_step_on_action(6, "manufacture_fighter")
        assert type(result) is bool
        assert result is False

    def test_true_case_returns_strict_bool_not_int(self):
        result = should_complete_step_on_action(10, "colonize_territory")
        assert type(result) is bool
        assert result is True
