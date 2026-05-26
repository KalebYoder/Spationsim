from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.diplomacy import Diplomacy
from ..models.nation import Nation
from ..models.player import Player
from ..schemas.diplomacy import DeclareWarRequest, WarResponse
from ..routers.auth import get_current_player

router = APIRouter(prefix="/api/diplomacy", tags=["diplomacy"])

MIN_WAR_DURATION_HOURS = 24


def is_at_war(db: Session, nation_a_id: int, nation_b_id: int) -> bool:
    a, b = min(nation_a_id, nation_b_id), max(nation_a_id, nation_b_id)
    row = db.query(Diplomacy).filter(
        Diplomacy.nation_a == a,
        Diplomacy.nation_b == b,
        Diplomacy.status == "war",
    ).first()
    return row is not None


def _get_or_create_diplomacy(db: Session, nation_a_id: int, nation_b_id: int) -> Diplomacy:
    a, b = min(nation_a_id, nation_b_id), max(nation_a_id, nation_b_id)
    row = db.query(Diplomacy).filter(
        Diplomacy.nation_a == a,
        Diplomacy.nation_b == b,
    ).first()
    if not row:
        row = Diplomacy(nation_a=a, nation_b=b, status="neutral")
        db.add(row)
        db.flush()
    return row


@router.post("/war", status_code=200)
def declare_war(
    body: DeclareWarRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    if body.target_nation_id == nation.id:
        raise HTTPException(status_code=409, detail="Cannot declare war on yourself")

    target = db.get(Nation, body.target_nation_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target nation not found")

    target_player = db.get(Player, target.player_id)
    if target_player and target_player.vacation_mode:
        raise HTTPException(status_code=409, detail="Cannot declare war on a nation in vacation mode")

    row = _get_or_create_diplomacy(db, nation.id, target.id)
    if row.status == "war":
        return {"status": "war", "target_nation_id": target.id, "already_at_war": True}

    row.status = "war"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "war", "target_nation_id": target.id, "already_at_war": False}


@router.get("/wars", response_model=list[WarResponse])
def list_wars(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    rows = db.query(Diplomacy).filter(
        Diplomacy.status == "war",
        (Diplomacy.nation_a == nation.id) | (Diplomacy.nation_b == nation.id),
    ).all()

    result = []
    for row in rows:
        other_id = row.nation_b if row.nation_a == nation.id else row.nation_a
        other = db.get(Nation, other_id)
        if other:
            result.append(WarResponse(
                nation_id=other.id,
                nation_name=other.name,
                status=row.status,
                updated_at=row.updated_at.isoformat(),
            ))
    return result


@router.delete("/war/{target_nation_id}", status_code=200)
def end_war(
    target_nation_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    a, b = min(nation.id, target_nation_id), max(nation.id, target_nation_id)
    row = db.query(Diplomacy).filter(
        Diplomacy.nation_a == a,
        Diplomacy.nation_b == b,
        Diplomacy.status == "war",
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No active war with this nation")

    now = datetime.now(timezone.utc)
    if row.updated_at:
        war_started = row.updated_at if row.updated_at.tzinfo else row.updated_at.replace(tzinfo=timezone.utc)
        earliest_end = war_started + timedelta(hours=MIN_WAR_DURATION_HOURS)
        if now < earliest_end:
            remaining = earliest_end - now
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            raise HTTPException(
                status_code=409,
                detail=f"Wars cannot end within {MIN_WAR_DURATION_HOURS} hours of declaration. "
                       f"You can end this war in {hours}h {minutes}m.",
            )

    row.status = "neutral"
    row.updated_at = now
    db.commit()
    return {"status": "neutral", "target_nation_id": target_nation_id}
