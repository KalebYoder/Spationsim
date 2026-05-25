"""Shared map generation logic used by both the seeder and the tick processor."""
import random as _random_module
from .models.territory import Territory

CLUSTER_CENTERS = [
    (0,  -16),   # north
    (14,   8),   # south-east
    (-14,  8),   # south-west
]

CLUSTER_RADIUS = 7
CLUSTER_VOID_RING = 6   # void ring extends this many hexes beyond cluster rim

# Weights for weighted_richness at center (local_dist=0) and rim (local_dist=CLUSTER_RADIUS).
# At center: 75% chance of 5; at rim: 75% chance of 1; slides linearly between them.
_CENTER_WEIGHTS = [0.0625, 0.0625, 0.0625, 0.0625, 0.75]
_RIM_WEIGHTS    = [0.75,   0.0625, 0.0625, 0.0625, 0.0625]
_VALUES = [1, 2, 3, 4, 5]


def _hex_dist(q1: int, r1: int, q2: int, r2: int) -> int:
    dq, dr = q2 - q1, r2 - r1
    return max(abs(dq), abs(dr), abs(dq + dr))


def weighted_richness(local_dist: int, rng=_random_module) -> int:
    """Return an integer 1-5, weighted toward 5 at center and 1 at rim."""
    t = max(0.0, min(1.0, (CLUSTER_RADIUS - local_dist) / CLUSTER_RADIUS))
    weights = [t * cw + (1 - t) * rw for cw, rw in zip(_CENTER_WEIGHTS, _RIM_WEIGHTS)]
    return rng.choices(_VALUES, weights=weights)[0]


def classify_hex(q: int, r: int) -> tuple[str, int]:
    """Return (territory_type, local_dist) for a hex coordinate.

    local_dist is the hex distance from the nearest cluster center.
    territory_type is 'normal' if within CLUSTER_RADIUS, else 'void'.
    """
    dists = [_hex_dist(q, r, cq, cr) for cq, cr in CLUSTER_CENTERS]
    min_dist = min(dists)
    if min_dist <= CLUSTER_RADIUS:
        return "normal", min_dist
    return "void", min_dist


def generate_territory(q: int, r: int, rng=_random_module) -> Territory:
    """Generate and return a Territory object for hex (q, r).

    Normal territories get weighted integer richness 1-5.
    Void-zone hexes have a 1/1000 chance of being an anomaly (5-10 richness
    in one resource, 0 in the other). Otherwise they are void.
    """
    t_type, local_dist = classify_hex(q, r)
    node_key = f"{q},{r}"

    if t_type == "normal":
        return Territory(
            node_key=node_key,
            territory_type="normal",
            mineral_richness=weighted_richness(local_dist, rng),
            fuel_richness=weighted_richness(local_dist, rng),
            distance_from_center=local_dist,
        )

    # Void zone — check for anomaly
    if rng.random() < 0.001:
        richness = rng.randint(5, 10)
        if rng.random() < 0.5:
            mineral, fuel = richness, 0
        else:
            mineral, fuel = 0, richness
        return Territory(
            node_key=node_key,
            territory_type="anomaly",
            mineral_richness=mineral,
            fuel_richness=fuel,
            distance_from_center=local_dist,
        )

    return Territory(
        node_key=node_key,
        territory_type="void",
        mineral_richness=0,
        fuel_richness=0,
        distance_from_center=local_dist,
    )
