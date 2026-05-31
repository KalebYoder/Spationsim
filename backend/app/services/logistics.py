from __future__ import annotations


def compute_logistics_fuel_cost(territory_count: int, k: float = 1.0) -> int:
    """
    Quadratic logistics fuel upkeep based on territory count.

    The Nth territory costs N×k fuel/tick to maintain, so holding N territories
    in total costs k × N × (N+1) / 2 fuel per tick.

    At k=1: 1 territory=1, 5 territories=15, 10 territories=55, 20 territories=210.

    k is a global balance knob — increase to steepen the logistics curve,
    decrease to flatten it.  Default k=1 is the beta starting point.
    """
    if territory_count <= 0:
        return 0
    return round(k * territory_count * (territory_count + 1) / 2)
