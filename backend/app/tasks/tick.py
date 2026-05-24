from datetime import datetime, timezone
from sqlalchemy import text
from ..celery_app import celery_app
from ..db.database import SessionLocal
from ..models.nation import Nation
from ..models.infrastructure import Infrastructure
from ..models.territory import Territory
from ..models.resource_log import ResourceLog
from ..models.event import Event
from ..models.territory_population import TerritoryPopulation
from ..constants import POPULATION_GROWTH_PER_TICK


@celery_app.task(name="app.tasks.tick.run_tick")
def run_tick():
    db = SessionLocal()
    tick_at = datetime.now(timezone.utc)
    try:
        nations = db.query(Nation).all()

        for nation in nations:
            territory_ids = [
                t_id for (t_id,) in
                db.query(Territory.id).filter(Territory.nation_id == nation.id).all()
            ]

            facilities = (
                db.query(Infrastructure.type, Territory.mineral_richness, Territory.fuel_richness)
                .join(Territory, Infrastructure.territory_id == Territory.id)
                .filter(Territory.nation_id == nation.id)
                .all()
            )

            minerals_delta = 0
            fuel_delta = 0
            for ftype, mineral_richness, fuel_richness in facilities:
                if ftype == "mine":
                    minerals_delta += round(2 * float(mineral_richness))
                elif ftype == "refinery":
                    fuel_delta += round(2 * float(fuel_richness))

            # Grow population in each territory
            pops = (
                db.query(TerritoryPopulation)
                .filter(TerritoryPopulation.territory_id.in_(territory_ids))
                .all()
            )
            population_delta = len(pops) * POPULATION_GROWTH_PER_TICK
            for pop in pops:
                pop.current += POPULATION_GROWTH_PER_TICK
                pop.last_updated = tick_at

            if minerals_delta or fuel_delta or population_delta:
                nation.minerals += minerals_delta
                nation.fuel += fuel_delta
                db.add(ResourceLog(
                    nation_id=nation.id,
                    tick_at=tick_at,
                    minerals_delta=minerals_delta,
                    fuel_delta=fuel_delta,
                    population_delta=population_delta,
                ))

        db.add(Event(
            type="tick",
            payload={"tick_at": tick_at.isoformat(), "nations_processed": len(nations)},
            scheduled_for=tick_at,
            processed_at=tick_at,
            status="processed",
        ))

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
