from ..constants import (
    DISSENT_WAR_AGGRESSOR, DISSENT_WAR_DEFENDER,
    DISSENT_FLEET_HOLDING, DISSENT_FLEET_ENGAGED,
    DISSENT_DECAY_PEACE, DISSENT_DECAY_WAR, DISSENT_DECAY_OCCUPIED,
    DISSENT_OFFICE_BONUS_NORMAL, DISSENT_OFFICE_BONUS_OCCUPIED, DISSENT_OFFICE_BONUS_AGGRESSOR,
    DISSENT_LOPSIDED_MULTIPLIER,
)


def compute_territory_dissent_delta(
    *,
    at_war: bool,
    is_aggressor: bool,
    is_lopsided_aggressor: bool,
    fleet_status: str | None,
    has_propaganda_office: bool,
    is_aggressor_in_any_active_war: bool,
) -> int:
    occupied = fleet_status in ("holding", "engaged")
    delta = 0

    if at_war:
        if is_aggressor:
            if is_lopsided_aggressor:
                delta += round(DISSENT_WAR_AGGRESSOR * DISSENT_LOPSIDED_MULTIPLIER)
            else:
                delta += DISSENT_WAR_AGGRESSOR
        else:
            delta += DISSENT_WAR_DEFENDER

    if fleet_status == "engaged":
        delta += DISSENT_FLEET_ENGAGED
    elif fleet_status == "holding":
        delta += DISSENT_FLEET_HOLDING

    if occupied:
        delta += DISSENT_DECAY_OCCUPIED
    elif at_war:
        delta += DISSENT_DECAY_WAR
    else:
        delta += DISSENT_DECAY_PEACE

    if has_propaganda_office:
        if occupied:
            delta -= DISSENT_OFFICE_BONUS_OCCUPIED
        elif is_aggressor_in_any_active_war:
            delta -= DISSENT_OFFICE_BONUS_AGGRESSOR
        else:
            delta -= DISSENT_OFFICE_BONUS_NORMAL

    return delta
