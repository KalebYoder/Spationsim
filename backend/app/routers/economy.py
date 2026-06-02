from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.event import Event
from ..models.fleet import Fleet
from ..models.infrastructure import Infrastructure
from ..models.nation import Nation
from ..models.player import Player
from ..models.territory import Territory
from ..models.territory_population import TerritoryPopulation
from ..routers.auth import get_current_player
from ..constants import (
    FACILITY_POPULATION_COST, POPULATION_CAP_MULTIPLIER,
    LOGISTICS_FUEL_K, TERRITORY_UPKEEP_K,
)
from ..services.logistics import compute_logistics_fuel_cost
from ..services.territory_yield import _mine_output, _refinery_output

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


@router.get("/flow")
def get_resource_flow(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    """Per-resource per-tick flow breakdown: production, each upkeep source, net, runway."""
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    territories = db.query(Territory).filter(Territory.nation_id == nation.id).all()
    territory_count = len(territories)
    territory_ids = [t.id for t in territories]

    active_facilities = (
        db.query(Infrastructure)
        .join(Territory, Infrastructure.territory_id == Territory.id)
        .filter(Territory.nation_id == nation.id, Infrastructure.status == "active")
        .all()
    )

    # Build territory lookup for richness/type
    t_by_id = {t.id: t for t in territories}

    minerals_production = 0
    fuel_production = 0
    income_facility_count = 0
    for f in active_facilities:
        t = t_by_id.get(f.territory_id)
        if not t:
            continue
        if f.type == "mine":
            minerals_production += _mine_output(float(t.mineral_richness), t.territory_type)
            income_facility_count += 1
        elif f.type == "refinery":
            fuel_production += _refinery_output(float(t.fuel_richness), t.territory_type)
            income_facility_count += 1

    # Fuel upkeep sources
    in_space_units = int(
        db.query(func.coalesce(func.sum(Fleet.unit_count), 0))
        .filter(Fleet.nation_id == nation.id, Fleet.status != "stationed")
        .scalar()
    )
    stationed_foreign_units = int(
        db.query(func.coalesce(func.sum(Fleet.unit_count), 0))
        .join(Territory, Fleet.origin_territory == Territory.id)
        .filter(
            Fleet.nation_id == nation.id,
            Fleet.status == "stationed",
            Territory.nation_id != nation.id,
        )
        .scalar()
    )
    fleet_fuel_upkeep = in_space_units + stationed_foreign_units
    logistics_fuel_upkeep = compute_logistics_fuel_cost(territory_count, k=LOGISTICS_FUEL_K)
    net_fuel = fuel_production - fleet_fuel_upkeep - logistics_fuel_upkeep

    # Currency upkeep sources
    total_fighters = int(
        db.query(func.coalesce(func.sum(Fleet.unit_count), 0))
        .filter(Fleet.nation_id == nation.id)
        .scalar()
    )
    currency_income = income_facility_count * 30
    fighter_currency_upkeep = total_fighters * 2
    territory_currency_upkeep = TERRITORY_UPKEEP_K * territory_count ** 2
    net_currency = currency_income - fighter_currency_upkeep - territory_currency_upkeep

    def runway(stockpile: float, net: int):
        """Ticks until empty (net < 0) or None if stable/positive."""
        if net >= 0 or stockpile <= 0:
            return None
        return round(float(stockpile) / abs(net))

    return {
        "minerals": {
            "production_per_tick": minerals_production,
            "net_per_tick": minerals_production,
            "current_stockpile": float(nation.minerals),
        },
        "fuel": {
            "production_per_tick": fuel_production,
            "fleet_upkeep_per_tick": fleet_fuel_upkeep,
            "fleet_count_out_of_dock": in_space_units + stationed_foreign_units,
            "logistics_upkeep_per_tick": logistics_fuel_upkeep,
            "territory_count": territory_count,
            "net_per_tick": net_fuel,
            "current_stockpile": float(nation.fuel),
            "ticks_until_empty": runway(nation.fuel, net_fuel),
        },
        "currency": {
            "income_per_tick": currency_income,
            "income_facility_count": income_facility_count,
            "fighter_upkeep_per_tick": fighter_currency_upkeep,
            "total_fighters": total_fighters,
            "territory_upkeep_per_tick": territory_currency_upkeep,
            "territory_count": territory_count,
            "net_per_tick": net_currency,
            "current_stockpile": float(nation.currency),
            "ticks_until_empty": runway(nation.currency, net_currency),
        },
    }
