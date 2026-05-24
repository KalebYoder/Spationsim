from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.infrastructure import Infrastructure
from ..models.nation import Nation
from ..models.territory import Territory
from ..models.player import Player
from ..schemas.nation import ManufactureRequest, NationResponse, UnitStatsResponse
from ..routers.auth import get_current_player
from ..models.territory_population import TerritoryPopulation
from ..constants import UNIT_STATS, FACILITY_POPULATION_COST

router = APIRouter(prefix="/api/military", tags=["military"])


@router.get("/units", response_model=list[UnitStatsResponse])
def get_units(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    reserves = {"starfighter": nation.starfighters}
    return [
        UnitStatsResponse(
            type=unit_type,
            attack=stats["attack"],
            defense=stats["defense"],
            hp=stats["hp"],
            nodes_per_tick=stats["nodes_per_tick"],
            reserve=reserves.get(unit_type, 0),
            manufacture_cost_minerals=stats["manufacture_cost_minerals"],
            manufacture_cost_fuel=stats["manufacture_cost_fuel"],
        )
        for unit_type, stats in UNIT_STATS.items()
    ]


@router.post("/manufacture/starfighter", response_model=NationResponse)
def manufacture_starfighter(
    body: ManufactureRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    has_factory = (
        db.query(Infrastructure)
        .join(Territory, Infrastructure.territory_id == Territory.id)
        .filter(Territory.nation_id == nation.id, Infrastructure.type == "fighter_factory")
        .first()
    )
    if not has_factory:
        raise HTTPException(status_code=409, detail="You need a fighter factory to manufacture starfighters")

    stats = UNIT_STATS["starfighter"]
    mineral_cost = stats["manufacture_cost_minerals"] * body.quantity
    fuel_cost = stats["manufacture_cost_fuel"] * body.quantity

    if nation.minerals < mineral_cost or nation.fuel < fuel_cost:
        raise HTTPException(status_code=409, detail="Insufficient resources")

    # Each starfighter consumes 1 population permanently
    territory_ids = [
        t_id for (t_id,) in
        db.query(Territory.id).filter(Territory.nation_id == nation.id).all()
    ]
    existing_facilities = (
        db.query(Infrastructure)
        .join(Territory, Infrastructure.territory_id == Territory.id)
        .filter(Territory.nation_id == nation.id)
        .all()
    )
    assigned_pop = sum(FACILITY_POPULATION_COST.get(f.type, 0) for f in existing_facilities)
    from sqlalchemy import func as sqlfunc
    total_pop = db.query(sqlfunc.sum(TerritoryPopulation.current)).filter(
        TerritoryPopulation.territory_id.in_(territory_ids)
    ).scalar() or 0
    unassigned = int(total_pop) - assigned_pop
    if unassigned < body.quantity:
        raise HTTPException(
            status_code=409,
            detail=f"Insufficient unassigned population (need {body.quantity}, have {unassigned})",
        )

    # Deduct population from territories (highest first)
    qty_remaining = body.quantity
    pops = (
        db.query(TerritoryPopulation)
        .filter(TerritoryPopulation.territory_id.in_(territory_ids))
        .order_by(TerritoryPopulation.current.desc())
        .all()
    )
    for pop in pops:
        if qty_remaining <= 0:
            break
        deduct = min(qty_remaining, pop.current)
        pop.current -= deduct
        qty_remaining -= deduct

    nation.minerals -= mineral_cost
    nation.fuel -= fuel_cost
    nation.starfighters += body.quantity

    db.commit()
    db.refresh(nation)
    return nation
