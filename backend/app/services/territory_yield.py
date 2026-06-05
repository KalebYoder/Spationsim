from __future__ import annotations
from ..constants import DISSENT_CURVE_EXPONENT

CURRENCY_INCOME_PER_FACILITY = 30    # per active mine or refinery per tick
FIGHTER_CURRENCY_UPKEEP = 2          # per stationed fighter per tick


def dissent_production_modifier(dissent: int) -> float:
    """
    Production multiplier in [0.0, 1.0] based on dissent level.
    No effect below 25. At 75 exactly half of production is lost.
    At 100 production is fully suppressed.
    """
    t = max(0.0, (dissent - 25) / 75.0)
    return max(0.0, 1.0 - t ** DISSENT_CURVE_EXPONENT)


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
    dissent_modifier: float = 1.0,
) -> dict:
    """
    Return per-tick resource flow for one territory.

    mine_count / refinery_count should reflect ACTIVE facilities only.
    stationed_fighters is the unit count of fleets with status='stationed'
    on this territory (used to compute currency upkeep attributable here).
    dissent_modifier scales mineral and fuel output only (not currency).

    Returns:
        minerals_per_tick       — minerals produced by active mines (after dissent)
        fuel_per_tick           — fuel produced by active refineries (after dissent)
        currency_income_per_tick — 30 × (mine_count + refinery_count)
        currency_upkeep_per_tick — 2 × stationed_fighters
        currency_net_per_tick   — income minus upkeep (can be negative)
    """
    raw_minerals = mine_count * _mine_output(mineral_richness, territory_type)
    raw_fuel = refinery_count * _refinery_output(fuel_richness, territory_type)
    minerals_per_tick = round(raw_minerals * dissent_modifier)
    fuel_per_tick = round(raw_fuel * dissent_modifier)
    currency_income = (mine_count + refinery_count) * CURRENCY_INCOME_PER_FACILITY
    currency_upkeep = stationed_fighters * FIGHTER_CURRENCY_UPKEEP
    return {
        "minerals_per_tick": minerals_per_tick,
        "fuel_per_tick": fuel_per_tick,
        "currency_income_per_tick": currency_income,
        "currency_upkeep_per_tick": currency_upkeep,
        "currency_net_per_tick": currency_income - currency_upkeep,
    }
