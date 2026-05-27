from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func as sqlfunc
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.fleet import Fleet
from ..models.infrastructure import Infrastructure
from ..models.nation import Nation
from ..models.territory import Territory
from ..models.territory_population import TerritoryPopulation
from ..models.player import Player
from ..schemas.nation import NationCreateRequest, NationResponse, PublicNationResponse, TerritoryResponse
from ..schemas.messaging import NationListItem
from ..routers.auth import get_current_player
from ..constants import POPULATION_START

VACATION_MIN_HOURS = 48
LOCKOUT_HOURS = 48

router = APIRouter(prefix="/api/nations", tags=["nations"])

_INDUSTRIAL_FACILITIES = {"mine", "refinery", "shipyard"}


def _power_metrics(db: Session, nation_id: int) -> tuple[int, int]:
    military = int(
        db.query(sqlfunc.coalesce(sqlfunc.sum(Fleet.unit_count), 0))
        .filter(Fleet.nation_id == nation_id)
        .scalar()
    )
    industrial = int(
        db.query(sqlfunc.coalesce(sqlfunc.sum(
            case((Infrastructure.type == "shipyard", 2), else_=1)
        ), 0))
        .join(Territory, Infrastructure.territory_id == Territory.id)
        .filter(
            Territory.nation_id == nation_id,
            Infrastructure.type.in_(_INDUSTRIAL_FACILITIES),
            Infrastructure.status == "active",
        )
        .scalar()
    )
    return military, industrial


@router.get("", response_model=list[NationListItem])
def list_nations(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    return db.query(Nation).order_by(Nation.name).all()


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
    if territory.territory_type == 'void':
        raise HTTPException(status_code=409, detail="Cannot settle in void space")
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
        currency=2000,
    )
    db.add(nation)
    db.flush()  # get nation.id before updating territory

    territory.nation_id = nation.id
    territory.is_colonized = True
    territory.colonized_at = datetime.now(timezone.utc)
    territory.name = body.home_planet_name

    db.add(TerritoryPopulation(
        territory_id=territory.id,
        current=POPULATION_START,
    ))

    db.commit()
    db.refresh(nation)
    return _nation_response(nation, player, db)


def _nation_response(nation: Nation, player: Player, db: Session) -> NationResponse:
    military, industrial = _power_metrics(db, nation.id)
    return NationResponse(
        id=nation.id,
        name=nation.name,
        currency_name=nation.currency_name,
        flag_color=nation.flag_color,
        home_territory_id=nation.home_territory_id,
        minerals=float(nation.minerals),
        fuel=float(nation.fuel),
        currency=float(nation.currency),
        probes_reserve=nation.probes_reserve,
        military_strength=military,
        industrial_strength=industrial,
        vacation_mode=player.vacation_mode,
        vacation_since=player.vacation_since.isoformat() if player.vacation_since else None,
        aggression_lockout_until=(
            player.aggression_lockout_until.isoformat()
            if player.aggression_lockout_until else None
        ),
    )


@router.get("/mine", response_model=NationResponse)
def get_my_nation(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    return _nation_response(nation, player, db)


@router.post("/me/vacation/enter", status_code=204)
def enter_vacation(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    if player.vacation_mode:
        raise HTTPException(status_code=409, detail="Already in vacation mode")
    now = datetime.now(timezone.utc)
    if player.aggression_lockout_until and player.aggression_lockout_until > now:
        until = player.aggression_lockout_until.strftime("%Y-%m-%d %H:%M UTC")
        raise HTTPException(
            status_code=409,
            detail=f"Cannot enter vacation mode during post-vacation lockout (expires {until})",
        )
    player.vacation_mode = True
    player.vacation_since = now
    db.commit()


@router.post("/me/vacation/exit", status_code=204)
def exit_vacation(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    if not player.vacation_mode:
        raise HTTPException(status_code=409, detail="Not in vacation mode")
    now = datetime.now(timezone.utc)
    earliest_exit = player.vacation_since + timedelta(hours=VACATION_MIN_HOURS)
    if now < earliest_exit:
        remaining = earliest_exit - now
        total_minutes = int(remaining.total_seconds() / 60)
        hours, minutes = divmod(total_minutes, 60)
        raise HTTPException(
            status_code=409,
            detail=f"Minimum {VACATION_MIN_HOURS}-hour stay not met. You can exit in {hours}h {minutes}m",
        )
    player.vacation_mode = False
    player.vacation_since = None
    player.aggression_lockout_until = now + timedelta(hours=LOCKOUT_HOURS)
    db.commit()


@router.get("/mine/territories", response_model=list[TerritoryResponse])
def get_my_territories(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    return db.query(Territory).filter(Territory.nation_id == nation.id).all()


@router.get("/{nation_id}", response_model=PublicNationResponse)
def get_nation_public(
    nation_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.get(Nation, nation_id)
    if not nation:
        raise HTTPException(status_code=404, detail="Nation not found")

    territory_count = (
        db.query(Territory)
        .filter(Territory.nation_id == nation_id, Territory.is_colonized == True)
        .count()
    )

    starfighter_count = (
        db.query(sqlfunc.coalesce(sqlfunc.sum(Fleet.unit_count), 0))
        .filter(Fleet.nation_id == nation_id)
        .scalar()
    )

    military, industrial = _power_metrics(db, nation_id)
    owner = db.get(Player, nation.player_id)

    return PublicNationResponse(
        id=nation.id,
        name=nation.name,
        flag_color=nation.flag_color,
        currency_name=nation.currency_name,
        territory_count=territory_count,
        military={"starfighter": int(starfighter_count)},
        military_strength=military,
        industrial_strength=industrial,
        vacation_mode=owner.vacation_mode if owner else False,
        vacation_since=owner.vacation_since.isoformat() if owner and owner.vacation_since else None,
    )
