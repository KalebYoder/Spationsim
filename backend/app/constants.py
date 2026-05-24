UNIT_STATS = {
    "starfighter": {
        "attack": 2,
        "defense": 1,
        "hp": 5,
        "nodes_per_tick": 2,
        "manufacture_cost_minerals": 5,
        "manufacture_cost_fuel": 10,
        "required_facility": "fighter_factory",
    },
}

PROBE_STATS = {
    "nodes_per_tick": 1,
    "manufacture_cost_minerals": 2,
    "manufacture_cost_fuel": 1,
    "required_facility": "probe_factory",
}

POPULATION_START = 100
POPULATION_GROWTH_RATE = 0.05        # 5% of current population per tick
POPULATION_CAP_MULTIPLIER = 50       # cap = 50 × (mineral_richness + fuel_richness)

FACILITY_POPULATION_COST = {
    "mine":            10,
    "refinery":        10,
    "probe_factory":   20,
    "fighter_factory": 40,
}

# Production formula: round(2 * territory_richness) per facility per tick
# mines use mineral_richness, refineries use fuel_richness

FACILITY_COSTS = {
    "mine":            {"minerals": 20, "fuel": 10},
    "refinery":        {"minerals": 10, "fuel": 20},
    "fighter_factory": {"minerals": 50, "fuel": 20},
    "probe_factory":   {"minerals": 10, "fuel":  5},
}
