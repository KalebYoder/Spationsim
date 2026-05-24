from datetime import datetime, timezone, timedelta
from math import ceil
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.fleet import Fleet
from ..models.infrastructure import Infrastructure
from ..models.nation import Nation
from ..models.territory import Territory
from ..models.territory_population import TerritoryPopulation
from ..models.player import Player
from ..schemas.nation import (
    FleetResponse,
    SendFleetRequest,
    StarfighterManufactureRequest,
    UnitStatsResponse,
)
from ..routers.auth import get_current_player
from ..constants import UNIT_STATS, FACILITY_POPULATION_COST

router = APIRouter(prefix="/api/military", tags=["military"])

TICK_HOURS = 2


def _hex_distance(key_a: str, key_b: str) -> int:
    q1, r1 = map(int, key_a.split(","))
    q2, r2 = map(int, key_b.split(","))
    dq, dr = q2 - q1, r2 - r1
    return max(abs(dq), abs(dr), abs(dq + dr))


def _fleet_response(fleet: Fleet, db: Session) -> FleetResponse:
    origin = db.get(Territory, fleet.origin_territory) if fleet.origin_territory else None
    dest = db.get(Territory, fleet.destination_territory) if fleet.destination_territory else None
    return FleetResponse(
        id=fleet.id,
        unit_count=fleet.unit_count,
        status=fleet.status,
        origin_territory_id=fleet.origin_territory,
        origin_node_key=origin.node_key if origin else None,
        origin_name=origin.name if origin else None,
        destination_territory_id=fleet.destination_territory,
        destination_node_key=dest.node_key if dest else None,
        destination_name=dest.name if dest else None,
        arrives_at=fleet.arrives_at.isoformat() if fleet.arrives_at else None,
    )


def _nation_pop_stats(nation_id: int, db: Session) -> tuple[int, int]:
    territory_ids = [
        t_id for (t_id,) in
        db.query(Territory.id).filter(Territory.nation_id == nation_id).all()
    ]
    total = int(
        db.query(sqlfunc.sum(TerritoryPopulation.current))
        .filter(TerritoryPopulation.territory_id.in_(territory_ids))
        .scalar() or 0
    )
    facilities = (
        db.query(Infrastructure)
        .join(Territory, Infrastructure.territory_id == Territory.id)
        .filter(Territory.nation_id == nation_id)
        .all()
    )
    assigned = sum(FACILITY_POPULATION_COST.get(f.type, 0) for f in facilities)
    return total, assigned


@router.get("/units", response_model=list[UnitStatsResponse])
def get_units(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    return [
        UnitStatsResponse(
            type=unit_type,
            attack=stats["attack"],
            defense=stats["defense"],
            hp=stats["hp"],
            nodes_per_tick=stats["nodes_per_tick"],
            manufacture_cost_minerals=stats["manufacture_cost_minerals"],
            manufacture_cost_fuel=stats["manufacture_cost_fuel"],
        )
        for unit_type, stats in UNIT_STATS.items()
    ]


@router.get("/fleets", response_model=list[FleetResponse])
def list_fleets(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    fleets = db.query(Fleet).filter(Fleet.nation_id == nation.id).all()
    return [_fleet_response(f, db) for f in fleets]


@router.post("/manufacture/starfighter", response_model=FleetResponse, status_code=201)
def manufacture_starfighter(
    body: StarfighterManufactureRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    territory = db.get(Territory, body.territory_id)
    if not territory or territory.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="You do not control this territory")

    has_factory = (
        db.query(Infrastructure)
        .filter(
            Infrastructure.territory_id == territory.id,
            Infrastructure.type == "fighter_factory",
        )
        .first()
    )
    if not has_factory:
        raise HTTPException(status_code=409, detail="This territory has no fighter factory")

    stats = UNIT_STATS["starfighter"]
    mineral_cost = stats["manufacture_cost_minerals"] * body.quantity
    fuel_cost = stats["manufacture_cost_fuel"] * body.quantity

    if nation.minerals < mineral_cost or nation.fuel < fuel_cost:
        raise HTTPException(status_code=409, detail="Insufficient resources")

    total_pop, assigned_pop = _nation_pop_stats(nation.id, db)
    unassigned = total_pop - assigned_pop
    if unassigned < body.quantity:
        raise HTTPException(
            status_code=409,
            detail=f"Insufficient unassigned population (need {body.quantity}, have {unassigned})",
        )

    # Consume population (deduct from most-populated territories first)
    territory_ids = [
        t_id for (t_id,) in
        db.query(Territory.id).filter(Territory.nation_id == nation.id).all()
    ]
    qty_remaining = body.quantity
    for pop in (
        db.query(TerritoryPopulation)
        .filter(TerritoryPopulation.territory_id.in_(territory_ids))
        .order_by(TerritoryPopulation.current.desc())
        .all()
    ):
        if qty_remaining <= 0:
            break
        deduct = min(qty_remaining, pop.current)
        pop.current -= deduct
        qty_remaining -= deduct

    nation.minerals -= mineral_cost
    nation.fuel -= fuel_cost

    # Add to existing stationed fleet at this territory or create one
    stationed = (
        db.query(Fleet)
        .filter(
            Fleet.nation_id == nation.id,
            Fleet.origin_territory == territory.id,
            Fleet.status == "stationed",
        )
        .first()
    )
    if stationed:
        stationed.unit_count += body.quantity
    else:
        stationed = Fleet(
            nation_id=nation.id,
            origin_territory=territory.id,
            unit_count=body.quantity,
            status="stationed",
            standing_order="hold",
        )
        db.add(stationed)

    db.commit()
    db.refresh(stationed)
    return _fleet_response(stationed, db)


@router.post("/fleets/send", response_model=FleetResponse, status_code=201)
def send_fleet(
    body: SendFleetRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    origin = db.get(Territory, body.from_territory_id)
    if not origin or origin.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="You do not control the origin territory")

    dest = db.get(Territory, body.to_territory_id)
    if not dest:
        raise HTTPException(status_code=404, detail="Destination territory not found")
    if body.from_territory_id == body.to_territory_id:
        raise HTTPException(status_code=409, detail="Origin and destination must differ")

    stationed = (
        db.query(Fleet)
        .filter(
            Fleet.nation_id == nation.id,
            Fleet.origin_territory == origin.id,
            Fleet.status == "stationed",
        )
        .first()
    )
    if not stationed or stationed.unit_count < body.quantity:
        available = stationed.unit_count if stationed else 0
        raise HTTPException(
            status_code=409,
            detail=f"Insufficient stationed fighters (have {available}, need {body.quantity})",
        )

    now = datetime.now(timezone.utc)
    distance = _hex_distance(origin.node_key, dest.node_key)
    transit_ticks = ceil(distance / UNIT_STATS["starfighter"]["nodes_per_tick"])
    arrives_at = now + timedelta(hours=transit_ticks * TICK_HOURS)

    stationed.unit_count -= body.quantity
    if stationed.unit_count == 0:
        db.delete(stationed)

    transit = Fleet(
        nation_id=nation.id,
        origin_territory=origin.id,
        destination_territory=dest.id,
        unit_count=body.quantity,
        status="in_transit",
        departs_at=now,
        arrives_at=arrives_at,
        standing_order="hold",
    )
    db.add(transit)
    db.commit()
    db.refresh(transit)
    return _fleet_response(transit, db)
