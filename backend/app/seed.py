"""
Territory seeder. Builds three resource clusters surrounded by void rings.
Usage: docker compose exec backend python -m app.seed [--force]
"""
import random
import sys
from sqlalchemy import text
from .db.database import SessionLocal
from .models.territory import Territory
from .map_gen import (
    CLUSTER_CENTERS,
    CLUSTER_RADIUS,
    CLUSTER_VOID_RING,
    classify_hex,
    generate_territory,
    _hex_dist,
)

RANDOM_SEED = 42


def hex_disk(cq, cr, radius):
    result = []
    for dq in range(-radius, radius + 1):
        for dr in range(-radius, radius + 1):
            if max(abs(dq), abs(dr), abs(dq + dr)) <= radius:
                result.append((cq + dq, cr + dr))
    return result


def seed_territories(force=False) -> int:
    rng = random.Random(RANDOM_SEED)
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
            db.execute(text("UPDATE nations SET home_territory_id = NULL, minerals = 100, fuel = 100, probes_reserve = 0"))
            db.execute(text("DELETE FROM territories"))
            db.commit()

        # Collect all hexes to generate: cluster nodes + void ring around each cluster
        seen: set[tuple[int, int]] = set()
        territories = []

        # Cluster nodes (normal, richness 1-5 weighted)
        for cq, cr in CLUSTER_CENTERS:
            for q, r in hex_disk(cq, cr, CLUSTER_RADIUS):
                if (q, r) in seen:
                    continue
                seen.add((q, r))
                t = generate_territory(q, r, rng)
                territories.append(t)

        # Void ring around each cluster (CLUSTER_RADIUS+1 to CLUSTER_RADIUS+CLUSTER_VOID_RING)
        for cq, cr in CLUSTER_CENTERS:
            for q, r in hex_disk(cq, cr, CLUSTER_RADIUS + CLUSTER_VOID_RING):
                if (q, r) in seen:
                    continue
                # Only include hexes in the void ring (outside cluster radius)
                t_type, _ = classify_hex(q, r)
                if t_type != "void":
                    # Another cluster claimed this hex as normal — skip (already handled above)
                    continue
                seen.add((q, r))
                t = generate_territory(q, r, rng)
                territories.append(t)

        db.bulk_save_objects(territories)
        db.commit()

        normal_count = sum(1 for t in territories if t.territory_type == "normal")
        void_count = sum(1 for t in territories if t.territory_type == "void")
        anomaly_count = sum(1 for t in territories if t.territory_type == "anomaly")
        print(
            f"Seeded {len(territories)} territories "
            f"({normal_count} normal, {void_count} void, {anomaly_count} anomaly)."
        )
        return len(territories)
    finally:
        db.close()


if __name__ == "__main__":
    force = "--force" in sys.argv
    seed_territories(force=force)
