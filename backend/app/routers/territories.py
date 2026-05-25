from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.territory import Territory
from ..models.nation import Nation
from ..models.player import Player
from ..schemas.nation import TerritoryResponse, TerritoryMapResponse, TerritoryRenameRequest
from ..routers.auth import get_current_player

RENAME_COOLDOWN_HOURS = 24  # 12 ticks × 2 h/tick

router = APIRouter(prefix="/api/territories", tags=["territories"])


@router.get("", response_model=list[TerritoryMapResponse])
def all_territories(db: Session = Depends(get_db)):
    rows = (
        db.query(Territory, Nation.name)
        .outerjoin(Nation, Territory.nation_id == Nation.id)
        .all()
    )
    return [
        TerritoryMapResponse(
            id=t.id,
            node_key=t.node_key,
            territory_type=t.territory_type,
            distance_from_center=t.distance_from_center,
            is_colonized=t.is_colonized,
            nation_id=t.nation_id,
            nation_name=name,
            mineral_richness=float(t.mineral_richness),
            fuel_richness=float(t.fuel_richness),
        )
        for t, name in rows
    ]


@router.get("/available", response_model=list[TerritoryResponse])
def available_territories(db: Session = Depends(get_db)):
    return (
        db.query(Territory)
        .filter(Territory.is_colonized == False, Territory.territory_type == 'normal')
        .order_by(Territory.distance_from_center)
        .all()
    )


@router.patch("/{territory_id}/name", response_model=TerritoryResponse)
def rename_territory(
    territory_id: int,
    body: TerritoryRenameRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    territory = db.get(Territory, territory_id)
    if not territory:
        raise HTTPException(status_code=404, detail="Territory not found")
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation or territory.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="You do not control this territory")
    if territory.last_renamed_at is not None:
        now = datetime.now(timezone.utc)
        earliest_next = territory.last_renamed_at + timedelta(hours=RENAME_COOLDOWN_HOURS)
        if now < earliest_next:
            remaining = earliest_next - now
            total_minutes = int(remaining.total_seconds() / 60)
            hours, minutes = divmod(total_minutes, 60)
            raise HTTPException(
                status_code=409,
                detail=f"Territories can only be renamed once every {RENAME_COOLDOWN_HOURS} hours. "
                       f"You can rename again in {hours}h {minutes}m",
            )
    territory.name = body.name
    territory.last_renamed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(territory)
    return territory
