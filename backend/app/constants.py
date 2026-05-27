UNIT_STATS = {
    "starfighter": {
        "attack": 2,
        "defense": 1,
        "hp": 5,
        "nodes_per_tick": 2,
        "manufacture_cost_minerals": 15,
        "manufacture_cost_fuel": 30,
        "manufacture_cost_currency": 1000,
        "required_facility": "shipyard",
    },
}

COLONY_SHIP_STATS = {
    "nodes_per_tick": 1,
    "cargo_capacity": 100,
    "manufacture_cost_minerals": 500,
    "manufacture_cost_fuel": 1000,
    "required_facility": "shipyard",
}

PROBE_STATS = {
    "nodes_per_tick": 1,
    "manufacture_cost_minerals": 1000,
    "manufacture_cost_fuel": 500,
    "manufacture_cost_currency": 10000,
    "required_facility": "probe_factory",
}

POPULATION_START = 100
POPULATION_GROWTH_RATE = 0.01        # 1% of current population per tick
POPULATION_CAP_MULTIPLIER = 50       # cap = 50 × (mineral_richness + fuel_richness)

FACILITY_POPULATION_COST = {
    "mine":          10,
    "refinery":      10,
    "probe_factory": 20,
    "shipyard":      40,
}

# Production formula per facility per tick:
#   normal territory (richness 1-5):  max(5, round(richness * 2))  →  5-10
#   anomaly territory (richness 5-10): round(richness * 2 + 10)    → 20-30
# mines use mineral_richness, refineries use fuel_richness

FACILITY_COSTS = {
    "mine":          {"minerals":  60, "fuel":  30, "currency":  500},
    "refinery":      {"minerals":  30, "fuel":  60, "currency":  500},
    "shipyard":      {"minerals": 150, "fuel":  60, "currency": 2000},
    "probe_factory": {"minerals":  30, "fuel":  15},
}

PROBE_RANGE = 10           # max nodes from nearest owned colony
PROBE_VISION_RADIUS = 2    # nodes revealed around probe each tick

# Ticks required to complete construction (1 tick = 2 hours)
FACILITY_BUILD_TICKS = {
    "mine":          1,
    "refinery":      1,
    "probe_factory": 1,
    "shipyard":      2,
}
DEMOLISH_TICKS = 1
DEMOLISH_REFUND_FRACTION = 0.25  # 25% of build cost returned, floored to int
