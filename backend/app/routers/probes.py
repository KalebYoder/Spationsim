from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.infrastructure import Infrastructure
from ..models.nation import Nation
from ..models.territory import Territory
from ..models.player import Player
from ..schemas.nation import ManufactureRequest, NationResponse, ProbeStatsResponse
from ..routers.auth import get_current_player
from ..constants import PROBE_STATS

router = APIRouter(prefix="/api/probes", tags=["probes"])


@router.get("/stats", response_model=ProbeStatsResponse)
def get_probe_stats(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    return ProbeStatsResponse(
        nodes_per_tick=PROBE_STATS["nodes_per_tick"],
        reserve=nation.probes_reserve,
        manufacture_cost_minerals=PROBE_STATS["manufacture_cost_minerals"],
        manufacture_cost_fuel=PROBE_STATS["manufacture_cost_fuel"],
    )


@router.post("/manufacture", response_model=NationResponse)
def manufacture_probes(
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
        .filter(Territory.nation_id == nation.id, Infrastructure.type == "probe_factory")
        .first()
    )
    if not has_factory:
        raise HTTPException(status_code=409, detail="You need a probe factory to manufacture probes")

    mineral_cost = PROBE_STATS["manufacture_cost_minerals"] * body.quantity
    fuel_cost = PROBE_STATS["manufacture_cost_fuel"] * body.quantity

    if nation.minerals < mineral_cost or nation.fuel < fuel_cost:
        raise HTTPException(status_code=409, detail="Insufficient resources")

    nation.minerals -= mineral_cost
    nation.fuel -= fuel_cost
    nation.probes_reserve += body.quantity

    db.commit()
    db.refresh(nation)
    return nation
