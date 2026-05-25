from datetime import datetime, timezone
from sqlalchemy import text
from ..celery_app import celery_app
from ..db.database import SessionLocal
from ..models.colony_ship import ColonyShip
from ..models.fleet import Fleet
from ..models.nation import Nation
from ..models.infrastructure import Infrastructure
from ..models.territory import Territory
from ..models.resource_log import ResourceLog
from ..models.event import Event
from ..models.territory_population import TerritoryPopulation
from ..constants import POPULATION_GROWTH_RATE, POPULATION_CAP_MULTIPLIER


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

            # Grow population in each territory (5% per tick, capped by richness)
            pop_rows = (
                db.query(TerritoryPopulation, Territory.mineral_richness, Territory.fuel_richness)
                .join(Territory, TerritoryPopulation.territory_id == Territory.id)
                .filter(TerritoryPopulation.territory_id.in_(territory_ids))
                .all()
            )
            population_delta = 0
            for pop, mineral_richness, fuel_richness in pop_rows:
                cap = round(POPULATION_CAP_MULTIPLIER * (float(mineral_richness) + float(fuel_richness)))
                if pop.current < cap:
                    growth = min(round(pop.current * POPULATION_GROWTH_RATE), cap - pop.current)
                    pop.current += growth
                    population_delta += growth
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

        # Land in-transit fleets that have arrived
        arrived_fleets = (
            db.query(Fleet)
            .filter(Fleet.status == "in_transit", Fleet.arrives_at <= tick_at)
            .all()
        )
        for fleet in arrived_fleets:
            dest_id = fleet.destination_territory
            existing = (
                db.query(Fleet)
                .filter(
                    Fleet.nation_id == fleet.nation_id,
                    Fleet.origin_territory == dest_id,
                    Fleet.status == "stationed",
                )
                .first()
            )
            if existing:
                existing.unit_count += fleet.unit_count
                db.delete(fleet)
            else:
                fleet.status = "stationed"
                fleet.origin_territory = dest_id
                fleet.destination_territory = None
                fleet.arrives_at = None
                fleet.departs_at = None

        # Land in-transit colony ships that have arrived
        arrived_colony_ships = (
            db.query(ColonyShip)
            .filter(ColonyShip.status == "in_transit", ColonyShip.arrives_at <= tick_at)
            .all()
        )
        for ship in arrived_colony_ships:
            ship.status = "stationed"
            ship.origin_territory = ship.destination_territory
            ship.destination_territory = None
            ship.arrives_at = None
            ship.departs_at = None

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
