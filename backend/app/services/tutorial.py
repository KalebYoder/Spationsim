_FACILITY_STEP_MAP = {
    "mine": 1,
    "refinery": 2,
    "shipyard": 4,
}

_FACILITY_TRIGGERED_STEPS = {1, 2, 4}

_REWARDS = {
    1: {"minerals": 500, "fuel": 0, "currency": 500},
    2: {"minerals": 0, "fuel": 500, "currency": 500},
    3: {"minerals": 0, "fuel": 0, "currency": 0},
    4: {"minerals": 0, "fuel": 0, "currency": 1000},
}

_ZERO_REWARD = {"minerals": 0, "fuel": 0, "currency": 0}


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
    if current_step >= 5:
        return 5
    return current_step + 1
