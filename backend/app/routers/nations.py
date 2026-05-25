from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.nation import Nation
from ..models.territory import Territory
from ..models.territory_population import TerritoryPopulation
from ..models.player import Player
from ..schemas.nation import NationCreateRequest, NationResponse, TerritoryResponse
from ..routers.auth import get_current_player
from ..constants import POPULATION_START

VACATION_MIN_HOURS = 48
LOCKOUT_HOURS = 48

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
        growth_rate=0,
    ))

    db.commit()
    db.refresh(nation)
    return nation


def _nation_response(nation: Nation, player: Player) -> NationResponse:
    return NationResponse(
        id=nation.id,
        name=nation.name,
        currency_name=nation.currency_name,
        flag_color=nation.flag_color,
        home_territory_id=nation.home_territory_id,
        minerals=float(nation.minerals),
        fuel=float(nation.fuel),
        starfighters=nation.starfighters,
        probes_reserve=nation.probes_reserve,
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
    return _nation_response(nation, player)


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
