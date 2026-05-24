"""
Territory seeder. Builds three resource clusters connected by void corridors.
Usage: docker compose exec backend python -m app.seed [--force]
"""
import random
import sys
from sqlalchemy import text
from .db.database import SessionLocal
from .models.territory import Territory

RANDOM_SEED = 42
CLUSTER_RADIUS = 7
CORRIDOR_WIDTH = 2
CORRIDOR_STEPS = 30

CLUSTER_CENTERS = [
    (0,   -16),   # north
    (14,   8),    # south-east
    (-14,  8),    # south-west
]


def hex_disk(cq, cr, radius):
    result = []
    for dq in range(-radius, radius + 1):
        for dr in range(-radius, radius + 1):
            if max(abs(dq), abs(dr), abs(dq + dr)) <= radius:
                result.append((cq + dq, cr + dr))
    return result


def hex_line_points(aq, ar, bq, br, steps):
    points = []
    for i in range(steps + 1):
        t = i / steps
        points.append((round(aq + (bq - aq) * t), round(ar + (br - ar) * t)))
    return points


def seed_territories(force=False) -> int:
    random.seed(RANDOM_SEED)
    db = SessionLocal()
    try:
        existing = db.query(Territory).count()
        if existing > 0:
            if not force:
                print("Territories already seeded — use --force to reseed.")
                return 0
            print("Clearing existing territory data...")
            db.execute(text("DELETE FROM infrastructure"))
            db.execute(text("DELETE FROM territory_population"))
            db.execute(text("DELETE FROM probe_data_access"))
            db.execute(text("DELETE FROM probe_data"))
            db.execute(text("UPDATE fleets SET origin_territory = NULL, destination_territory = NULL"))
            db.execute(text("UPDATE probes SET origin_territory = NULL, destination_territory = NULL"))
            db.execute(text("UPDATE nations SET home_territory_id = NULL, minerals = 100, fuel = 100, starfighters = 0, probes_reserve = 0"))
            db.execute(text("DELETE FROM territories"))
            db.commit()

        # --- Build normal cluster nodes ---
        cluster_nodes = {}  # (q,r) -> distance_from_cluster_center
        for (cq, cr) in CLUSTER_CENTERS:
            for (q, r) in hex_disk(cq, cr, CLUSTER_RADIUS):
                dist = max(abs(q - cq), abs(r - cr), abs((q - cq) + (r - cr)))
                if (q, r) not in cluster_nodes or dist < cluster_nodes[(q, r)]:
                    cluster_nodes[(q, r)] = dist

        # --- Build void corridor nodes ---
        void_nodes = set()
        pairs = [
            (CLUSTER_CENTERS[0], CLUSTER_CENTERS[1]),
            (CLUSTER_CENTERS[1], CLUSTER_CENTERS[2]),
            (CLUSTER_CENTERS[0], CLUSTER_CENTERS[2]),
        ]
        for (aq, ar), (bq, br) in pairs:
            for (lq, lr) in hex_line_points(aq, ar, bq, br, CORRIDOR_STEPS):
                for (q, r) in hex_disk(lq, lr, CORRIDOR_WIDTH):
                    if (q, r) not in cluster_nodes:
                        void_nodes.add((q, r))

        # --- Assemble territories ---
        territories = []

        for (q, r), local_dist in cluster_nodes.items():
            base = max(0.5, 4.0 - local_dist * 0.45)
            mineral_richness = round(min(4.0, max(0.10, base + random.uniform(-0.4, 0.4))), 2)
            fuel_richness    = round(min(4.0, max(0.10, base + random.uniform(-0.4, 0.4))), 2)
            territories.append(Territory(
                node_key=f"{q},{r}",
                territory_type='normal',
                mineral_richness=mineral_richness,
                fuel_richness=fuel_richness,
                distance_from_center=local_dist,
            ))

        for (q, r) in void_nodes:
            territories.append(Territory(
                node_key=f"{q},{r}",
                territory_type='void',
                mineral_richness=0.0,
                fuel_richness=0.0,
                distance_from_center=CLUSTER_RADIUS + 1,
            ))

        db.bulk_save_objects(territories)
        db.commit()

        normal_count = len(cluster_nodes)
        void_count = len(void_nodes)
        print(f"Seeded {len(territories)} territories ({normal_count} normal, {void_count} void).")
        return len(territories)
    finally:
        db.close()


if __name__ == "__main__":
    force = "--force" in sys.argv
    seed_territories(force=force)
