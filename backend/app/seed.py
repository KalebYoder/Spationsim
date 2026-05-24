"""
Territory seeder. Run once to populate the game map.
Usage: docker compose exec backend python -m app.seed
"""
import random
from .db.database import SessionLocal
from .models.territory import Territory

MAX_RING = 14  # produces ~631 territories (within the 500-800 target)
RANDOM_SEED = 42


def seed_territories() -> int:
    random.seed(RANDOM_SEED)
    db = SessionLocal()
    try:
        if db.query(Territory).count() > 0:
            print("Territories already seeded — skipping.")
            return 0

        territories = []
        for q in range(-MAX_RING, MAX_RING + 1):
            for r in range(-MAX_RING, MAX_RING + 1):
                dist = max(abs(q), abs(r), abs(q + r))
                if dist > MAX_RING:
                    continue

                # Resource richness decreases with distance; some randomness per node
                base = max(0.5, 4.0 - dist * 0.24)
                mineral_richness = round(
                    min(4.0, max(0.10, base + random.uniform(-0.35, 0.35))), 2
                )
                fuel_richness = round(
                    min(4.0, max(0.10, base + random.uniform(-0.35, 0.35))), 2
                )
                territories.append(
                    Territory(
                        node_key=f"{q},{r}",
                        mineral_richness=mineral_richness,
                        fuel_richness=fuel_richness,
                        distance_from_center=dist,
                    )
                )

        db.bulk_save_objects(territories)
        db.commit()
        print(f"Seeded {len(territories)} territories.")
        return len(territories)
    finally:
        db.close()


if __name__ == "__main__":
    seed_territories()
