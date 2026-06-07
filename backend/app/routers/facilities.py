from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.infrastructure import Infrastructure
from ..models.nation import Nation
from ..models.territory import Territory
from ..models.player import Player
from ..schemas.nation import InfrastructureBuildRequest, InfrastructureResponse
from ..routers.auth import get_current_player
from ..models.territory_population import TerritoryPopulation
from ..constants import (
    FACILITY_COSTS,
    FACILITY_POPULATION_COST,
    FACILITY_BUILD_TICKS,
    DEMOLISH_TICKS,
    DEMOLISH_REFUND_FRACTION,
)
from ..models.tutorial import TutorialState
from ..services.tutorial import should_complete_step, get_tutorial_reward, next_step as tutorial_next_step

_IMMEDIATE_TUTORIAL_STEPS = {1, 2, 4}

router = APIRouter(prefix="/api/facilities", tags=["facilities"])

TICK_HOURS = 2


def _to_response(infra: Infrastructure, territory: Territory) -> InfrastructureResponse:
    return InfrastructureResponse(
        id=infra.id,
        territory_id=infra.territory_id,
        territory_node_key=territory.node_key,
        territory_name=territory.name,
        type=infra.type,
        level=infra.level,
        built_at=infra.built_at.isoformat() if infra.built_at else None,
        status=infra.status,
        completes_at=infra.completes_at.isoformat() if infra.completes_at else None,
    )


def _territory_assigned_pop(territory_id: int, db: Session) -> int:
    """Sum population cost of all active + under_construction facilities on a single territory."""
    rows = (
        db.query(Infrastructure)
        .filter(
            Infrastructure.territory_id == territory_id,
            Infrastructure.status.in_(["active", "under_construction"]),
        )
        .all()
    )
    return sum(FACILITY_POPULATION_COST.get(f.type, 0) for f in rows)


@router.get("", response_model=list[InfrastructureResponse])
def list_facilities(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    rows = (
        db.query(Infrastructure, Territory)
        .join(Territory, Infrastructure.territory_id == Territory.id)
        .filter(Territory.nation_id == nation.id)
        .all()
    )
    return [_to_response(infra, territory) for infra, territory in rows]


@router.post("", response_model=InfrastructureResponse, status_code=201)
def build_facility(
    body: InfrastructureBuildRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    territory = db.get(Territory, body.territory_id)
    if not territory or territory.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="You do not control this territory")
    if territory.territory_type == "void":
        raise HTTPException(status_code=409, detail="Cannot build facilities in void space")

    if body.type == "propaganda_office":
        existing = (
            db.query(Infrastructure)
            .filter(
                Infrastructure.territory_id == territory.id,
                Infrastructure.type == "propaganda_office",
                Infrastructure.status.in_(["active", "under_construction"]),
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=409, detail="Only one Propaganda Office can be built per territory")

    cost = FACILITY_COSTS[body.type]
    currency_cost = cost.get("currency", 0)
    if (
        nation.minerals < cost["minerals"]
        or nation.fuel < cost["fuel"]
        or nation.currency < currency_cost
    ):
        raise HTTPException(status_code=409, detail="Insufficient resources")

    pop_cost = FACILITY_POPULATION_COST.get(body.type, 0)
    if pop_cost > 0:
        territory_pop = int(
            db.query(TerritoryPopulation.current)
            .filter(TerritoryPopulation.territory_id == territory.id)
            .scalar() or 0
        )
        unassigned = territory_pop - _territory_assigned_pop(territory.id, db)
        if unassigned < pop_cost:
            raise HTTPException(
                status_code=409,
                detail=f"Insufficient unassigned population on this territory (need {pop_cost}, have {max(0, unassigned)})",
            )

    nation.minerals -= cost["minerals"]
    nation.fuel -= cost["fuel"]
    nation.currency -= currency_cost

    build_ticks = FACILITY_BUILD_TICKS.get(body.type, 1)
    completes_at = datetime.now(timezone.utc) + timedelta(hours=build_ticks * TICK_HOURS)

    infra = Infrastructure(
        territory_id=territory.id,
        type=body.type,
        status="under_construction",
        completes_at=completes_at,
    )
    db.add(infra)

    # Award tutorial reward immediately for steps 1 and 2
    tutorial = db.query(TutorialState).filter(
        TutorialState.nation_id == nation.id,
        TutorialState.dismissed == False,
    ).first()
    if tutorial and should_complete_step(tutorial.current_step, body.type) \
            and tutorial.current_step in _IMMEDIATE_TUTORIAL_STEPS:
        reward = get_tutorial_reward(tutorial.current_step)
        nation.minerals += reward["minerals"]
        nation.fuel += reward["fuel"]
        nation.currency += reward["currency"]
        completed_step = tutorial.current_step
        setattr(tutorial, f"step{completed_step}_completed_at", datetime.now(timezone.utc))
        tutorial.current_step = tutorial_next_step(tutorial.current_step)

    db.commit()
    db.refresh(infra)
    return _to_response(infra, territory)


@router.post("/{facility_id}/demolish", response_model=InfrastructureResponse)
def demolish_facility(
    facility_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    infra = db.get(Infrastructure, facility_id)
    if not infra:
        raise HTTPException(status_code=404, detail="Facility not found")

    territory = db.get(Territory, infra.territory_id)
    if not territory or territory.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="You do not control this territory")

    if infra.status != "active":
        raise HTTPException(
            status_code=409,
            detail="Only active facilities can be demolished",
        )

    completes_at = datetime.now(timezone.utc) + timedelta(hours=DEMOLISH_TICKS * TICK_HOURS)
    infra.status = "demolishing"
    infra.completes_at = completes_at

    db.commit()
    db.refresh(infra)
    return _to_response(infra, territory)


@router.post("/{facility_id}/cancel")
def cancel_construction(
    facility_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    infra = db.get(Infrastructure, facility_id)
    if not infra:
        raise HTTPException(status_code=404, detail="Facility not found")

    territory = db.get(Territory, infra.territory_id)
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not territory or not nation or territory.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="You do not control this territory")

    if infra.status != "under_construction":
        raise HTTPException(
            status_code=409,
            detail="Only facilities under construction can be cancelled",
        )

    cost = FACILITY_COSTS[infra.type]
    nation.minerals += cost["minerals"]
    nation.fuel += cost["fuel"]
    nation.currency += cost.get("currency", 0)

    db.delete(infra)
    db.commit()
    return {"detail": "Construction cancelled and resources refunded"}
