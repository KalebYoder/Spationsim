_FACILITY_STEP_MAP = {
    "mine": 1,
    "refinery": 2,
    "shipyard": 4,
}

_FACILITY_TRIGGERED_STEPS = {1, 2, 4}

_REWARDS = {
    1:  {"minerals": 500,  "fuel": 0,    "currency": 500},
    2:  {"minerals": 0,    "fuel": 500,  "currency": 500},
    3:  {"minerals": 100,  "fuel": 100,  "currency": 500},
    4:  {"minerals": 0,    "fuel": 0,    "currency": 1000},
    5:  {"minerals": 0,    "fuel": 0,    "currency": 1000},
    6:  {"minerals": 0,    "fuel": 0,    "currency": 0},
    7:  {"minerals": 500,  "fuel": 500,  "currency": 0},
    8:  {"minerals": 500,  "fuel": 1000, "currency": 0},
    9:  {"minerals": 0,    "fuel": 0,    "currency": 0},
    10: {"minerals": 1000, "fuel": 1000, "currency": 2000},
}

_ZERO_REWARD = {"minerals": 0, "fuel": 0, "currency": 0}

_ACTION_STEP_MAP = {
    "manufacture_fighter":     5,
    "dispatch_fleet":          7,
    "manufacture_colony_ship": 8,
    "colonize_territory":      10,
}
_ACTION_TRIGGERED_STEPS = {5, 7, 8, 10}


def get_facility_tutorial_step(facility_type: str) -> int | None:
    return _FACILITY_STEP_MAP.get(facility_type)


def get_tutorial_reward(step: int) -> dict:
    r = _REWARDS.get(step, _ZERO_REWARD)
    return {"minerals": int(r["minerals"]), "fuel": int(r["fuel"]), "currency": int(r["currency"])}


def should_complete_step(current_step: int, facility_type: str) -> bool:
    if current_step not in _FACILITY_TRIGGERED_STEPS:
        return False
    return get_facility_tutorial_step(facility_type) == current_step


def next_step(current_step: int) -> int:
    if current_step >= 11:
        return 11
    return current_step + 1


def get_action_tutorial_step(action: str) -> int | None:
    return _ACTION_STEP_MAP.get(action)


def should_complete_step_on_action(current_step: int, action: str) -> bool:
    if current_step not in _ACTION_TRIGGERED_STEPS:
        return False
    return get_action_tutorial_step(action) == current_step
