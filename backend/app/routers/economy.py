from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.event import Event
from ..models.infrastructure import Infrastructure
from ..models.nation import Nation
from ..models.player import Player
from ..models.territory import Territory
from ..models.territory_population import TerritoryPopulation
from ..routers.auth import get_current_player
from ..constants import FACILITY_POPULATION_COST, POPULATION_CAP_MULTIPLIER

router = APIRouter(prefix="/api/economy", tags=["economy"])


@router.get("/last-tick")
def last_tick(
    db: Session = Depends(get_db),
    _: Player = Depends(get_current_player),
):
    event = (
        db.query(Event)
        .filter(Event.type == "tick", Event.status == "processed")
        .order_by(Event.processed_at.desc())
        .first()
    )
    if not event:
        return None
    return {"processed_at": event.processed_at.isoformat()}


@router.get("/population")
def get_population(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    territories = db.query(Territory).filter(Territory.nation_id == nation.id).all()
    territory_ids = [t.id for t in territories]

    total = int(
        db.query(func.sum(TerritoryPopulation.current))
        .filter(TerritoryPopulation.territory_id.in_(territory_ids))
        .scalar() or 0
    )
    cap = sum(
        round(POPULATION_CAP_MULTIPLIER * (float(t.mineral_richness) + float(t.fuel_richness)))
        for t in territories
    )
    facilities = (
        db.query(Infrastructure)
        .join(Territory, Infrastructure.territory_id == Territory.id)
        .filter(Territory.nation_id == nation.id)
        .all()
    )
    assigned = sum(FACILITY_POPULATION_COST.get(f.type, 0) for f in facilities)
    return {"total": total, "cap": cap, "assigned": assigned, "unassigned": total - assigned}
