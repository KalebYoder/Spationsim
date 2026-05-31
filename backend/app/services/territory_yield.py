from __future__ import annotations

CURRENCY_INCOME_PER_TERRITORY = 500  # per territory with >= 1 active mine or refinery
FIGHTER_CURRENCY_UPKEEP = 2          # per stationed fighter per tick


def _mine_output(mineral_richness: float, territory_type: str) -> int:
    r = float(mineral_richness)
    return round(r * 2 + 10) if territory_type == "anomaly" else max(5, round(r * 2))


def _refinery_output(fuel_richness: float, territory_type: str) -> int:
    r = float(fuel_richness)
    return round(r * 2 + 10) if territory_type == "anomaly" else max(5, round(r * 2))


def compute_territory_yield(
    territory_type: str,
    mineral_richness: float,
    fuel_richness: float,
    mine_count: int,
    refinery_count: int,
    stationed_fighters: int = 0,
) -> dict:
    """
    Return per-tick resource flow for one territory.

    mine_count / refinery_count should reflect ACTIVE facilities only.
    stationed_fighters is the unit count of fleets with status='stationed'
    on this territory (used to compute currency upkeep attributable here).

    Returns:
        minerals_per_tick       — minerals produced by active mines
        fuel_per_tick           — fuel produced by active refineries
        currency_income_per_tick — 500 if territory has >= 1 active mine or refinery
        currency_upkeep_per_tick — 2 × stationed_fighters
        currency_net_per_tick   — income minus upkeep (can be negative)
    """
    minerals_per_tick = mine_count * _mine_output(mineral_richness, territory_type)
    fuel_per_tick = refinery_count * _refinery_output(fuel_richness, territory_type)
    currency_income = CURRENCY_INCOME_PER_TERRITORY if mine_count + refinery_count > 0 else 0
    currency_upkeep = stationed_fighters * FIGHTER_CURRENCY_UPKEEP
    return {
        "minerals_per_tick": minerals_per_tick,
        "fuel_per_tick": fuel_per_tick,
        "currency_income_per_tick": currency_income,
        "currency_upkeep_per_tick": currency_upkeep,
        "currency_net_per_tick": currency_income - currency_upkeep,
    }
