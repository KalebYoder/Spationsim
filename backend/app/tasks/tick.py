from datetime import datetime, timezone
from sqlalchemy import text
from ..celery_app import celery_app
from ..db.database import SessionLocal
from ..models.nation import Nation
from ..models.infrastructure import Infrastructure
from ..models.territory import Territory
from ..models.resource_log import ResourceLog
from ..models.event import Event
from ..constants import FACILITY_PRODUCTION


@celery_app.task(name="app.tasks.tick.run_tick")
def run_tick():
    db = SessionLocal()
    tick_at = datetime.now(timezone.utc)
    try:
        nations = db.query(Nation).all()

        for nation in nations:
            facilities = (
                db.query(Infrastructure.type)
                .join(Territory, Infrastructure.territory_id == Territory.id)
                .filter(Territory.nation_id == nation.id)
                .all()
            )

            minerals_delta = 0
            fuel_delta = 0
            for (ftype,) in facilities:
                production = FACILITY_PRODUCTION.get(ftype, {})
                minerals_delta += production.get("minerals", 0)
                fuel_delta += production.get("fuel", 0)

            if minerals_delta or fuel_delta:
                nation.minerals += minerals_delta
                nation.fuel += fuel_delta
                db.add(ResourceLog(
                    nation_id=nation.id,
                    tick_at=tick_at,
                    minerals_delta=minerals_delta,
                    fuel_delta=fuel_delta,
                    population_delta=0,
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
