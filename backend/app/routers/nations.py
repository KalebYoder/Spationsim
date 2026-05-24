from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.nation import Nation
from ..models.territory import Territory
from ..models.player import Player
from ..schemas.nation import NationCreateRequest, NationResponse, TerritoryResponse
from ..routers.auth import get_current_player

router = APIRouter(prefix="/api/nations", tags=["nations"])


@router.post("", response_model=NationResponse, status_code=201)
def create_nation(
    body: NationCreateRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    if db.query(Nation).filter(Nation.player_id == player.id).first():
        raise HTTPException(status_code=409, detail="You already have a nation")
    if db.query(Nation).filter(Nation.name == body.name).first():
        raise HTTPException(status_code=409, detail="Nation name already taken")

    territory = db.get(Territory, body.home_territory_id)
    if not territory:
        raise HTTPException(status_code=404, detail="Territory not found")
    if territory.is_colonized:
        raise HTTPException(status_code=409, detail="Territory is already occupied")

    nation = Nation(
        player_id=player.id,
        name=body.name,
        currency_name=body.currency_name,
        flag_color=body.flag_color,
        home_territory_id=body.home_territory_id,
        minerals=100,
        fuel=100,
    )
    db.add(nation)
    db.flush()  # get nation.id before updating territory

    territory.nation_id = nation.id
    territory.is_colonized = True
    territory.colonized_at = datetime.now(timezone.utc)
    territory.name = body.home_planet_name

    db.commit()
    db.refresh(nation)
    return nation


@router.get("/mine", response_model=NationResponse)
def get_my_nation(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    return nation


@router.get("/mine/territories", response_model=list[TerritoryResponse])
def get_my_territories(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    return db.query(Territory).filter(Territory.nation_id == nation.id).all()
