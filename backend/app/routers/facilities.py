from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.infrastructure import Infrastructure
from ..models.nation import Nation
from ..models.territory import Territory
from ..models.player import Player
from ..schemas.nation import InfrastructureBuildRequest, InfrastructureResponse
from ..routers.auth import get_current_player
from ..constants import FACILITY_COSTS

router = APIRouter(prefix="/api/facilities", tags=["facilities"])

COSTS = FACILITY_COSTS


def _to_response(infra: Infrastructure, territory: Territory) -> InfrastructureResponse:
    return InfrastructureResponse(
        id=infra.id,
        territory_id=infra.territory_id,
        territory_node_key=territory.node_key,
        territory_name=territory.name,
        type=infra.type,
        level=infra.level,
        built_at=infra.built_at.isoformat() if infra.built_at else None,
    )


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
    if territory.territory_type == 'void':
        raise HTTPException(status_code=409, detail="Cannot build facilities in void space")

    cost = COSTS[body.type]
    if nation.minerals < cost["minerals"] or nation.fuel < cost["fuel"]:
        raise HTTPException(status_code=409, detail="Insufficient resources")

    nation.minerals -= cost["minerals"]
    nation.fuel -= cost["fuel"]

    infra = Infrastructure(territory_id=territory.id, type=body.type)
    db.add(infra)
    db.commit()
    db.refresh(infra)
    return _to_response(infra, territory)
