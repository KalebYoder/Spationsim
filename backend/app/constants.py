UNIT_STATS = {
    "starfighter": {
        "firepower": 2,
        "shields": 1,
        "structural_integrity": 5,
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
    "required_facility": "shipyard",
}

POPULATION_START = 100
POPULATION_GROWTH_RATE = 0.01        # 1% of current population per tick
POPULATION_CAP_MULTIPLIER = 50       # cap = 50 × (mineral_richness + fuel_richness)

FACILITY_POPULATION_COST = {
    "mine":               10,
    "refinery":           10,
    "shipyard":           40,
    "propaganda_office":  20,
}

# Production formula per facility per tick:
#   normal territory (richness 1-5):  max(5, round(richness * 2))  →  5-10
#   anomaly territory (richness 5-10): round(richness * 2 + 10)    → 20-30
# mines use mineral_richness, refineries use fuel_richness

FACILITY_COSTS = {
    "mine":               {"minerals":  60, "fuel":  30, "currency":  500},
    "refinery":           {"minerals":  30, "fuel":  60, "currency":  500},
    "shipyard":           {"minerals": 150, "fuel":  60, "currency": 2000},
    "propaganda_office":  {"minerals": 500, "fuel": 250, "currency": 6000},
}

PROBE_RANGE = 10           # max nodes from nearest owned colony
PROBE_VISION_RADIUS = 2    # nodes revealed around probe each tick

# Ticks required to complete construction (1 tick = 2 hours)
FACILITY_BUILD_TICKS = {
    "mine":              1,
    "refinery":          1,
    "shipyard":          2,
    "propaganda_office": 2,
}
DEMOLISH_TICKS = 1
DEMOLISH_REFUND_FRACTION = 0.25  # 25% of build cost returned, floored to int

# Logistics fuel upkeep: each Nth territory costs N × k fuel/tick.
# Total across N territories = k × N(N+1)/2  (quadratic, creates diminishing returns).
# At k=1: 5 territories=15 fuel/tick, 10=55, 20=210.  Tune during beta.
LOGISTICS_FUEL_K = 1

# Dissent production penalty curve: modifier = max(0, 1 - t^n), t = max(0, (d-25)/75)
# n = ln(2)/ln(1.5) ≈ 1.71 — anchor: 50% production loss at dissent=75, zero at 100.
# Tune during beta; higher n = more forgiving at mid-dissent, harsher at high dissent.
DISSENT_CURVE_EXPONENT = 1.71

# Dissent accumulation sources (per tick)
DISSENT_WAR_AGGRESSOR    = 3   # all aggressor's territories while at war
DISSENT_WAR_DEFENDER     = 2   # all defender's territories while at war
DISSENT_FLEET_HOLDING    = 6   # territory with enemy fleet holding
DISSENT_FLEET_ENGAGED    = 10  # territory with enemy fleet engaged
DISSENT_CONQUEST_RESET   = 80  # instant value on conquest

# Dissent decay (per tick, negative = decreasing dissent)
DISSENT_DECAY_PEACE      = -3  # at peace, no enemy fleet
DISSENT_DECAY_WAR        = -2  # at war, no enemy fleet on this territory
DISSENT_DECAY_OCCUPIED   =  0  # enemy fleet present — no natural decay

# Propaganda Office decay bonuses
DISSENT_OFFICE_BONUS_NORMAL     = 2  # additional decay at peace or war without occupation
DISSENT_OFFICE_BONUS_OCCUPIED   = 3  # additional decay while enemy fleet present
HOME_TERRITORY_DEFENSE_MULTIPLIER = 1.5  # defender effective count on own colonized territory

DISSENT_LOPSIDED_WAR_RATIO    = 3    # aggressor/defender military ratio threshold (strictly >)
DISSENT_LOPSIDED_MULTIPLIER   = 1.5  # multiplier on aggressor war dissent when lopsided
DISSENT_OFFICE_BONUS_AGGRESSOR = 1   # PO decay bonus cap while nation is the declared aggressor

# Holding fleet attrition: fraction of unit_count lost per tick when holding at a territory
# where an enemy stationed fleet is present. min 1 unit/tick enforced in tick.py.
# At 2.5%: a 100-unit fleet lasts ~40 ticks (~80 hours) under contested holding.
HOLDING_ATTRITION_RATE = 0.025

# Territory count currency upkeep: k × N² per tick, where N = territories owned.
# Marginal cost of the Nth territory = k × (2N − 1).  Optimal expansion stops when
# marginal cost exceeds marginal income per territory.
# At k=10: optimal N* = I / (2k), where I = currency income per territory per tick.
#   Low-richness rim (I≈150):  N* ≈ 7     Medium (I≈300): N* ≈ 15    Core (I≈600): N* ≈ 30
# Tune during beta; stored here so the open-question monitor has a single lever to pull.
TERRITORY_UPKEEP_K = 10

DEFENDER_AUTO_ROUT_FRACTION = 0.50

# Raid loot = min(fleet_FP * RAID_K, defender_stockpile * RAID_MAX_STOCKPILE_FRACTION).
# RAID_K=1 means 500 FP hits the 5% cap on a 10,000-unit stockpile.
# Scales naturally with new unit types (cruisers etc.) via their FP stat.
RAID_K                    = 1
RAID_MAX_STOCKPILE_FRACTION = 0.05

# Wars that reach this age auto-resolve to white peace. 48h redeclaration cooldown applies.
# Prevents indefinite wars against inactive or deleted players.
WAR_MAX_DURATION_DAYS = 14
