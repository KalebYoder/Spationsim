from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.diplomacy import Diplomacy
from ..models.nation import Nation
from ..models.player import Player
from ..models.event import Event
from ..schemas.diplomacy import SetStatusRequest, DiplomacyRelationResponse, WarResponse
from ..routers.auth import get_current_player

router = APIRouter(prefix="/api/diplomacy", tags=["diplomacy"])

WAR_PENDING_HOURS = 4  # 2 ticks


def get_diplomacy_status(db: Session, nation_a_id: int, nation_b_id: int) -> str:
    """Return the current diplomacy status between two nations ('neutral' if no row exists)."""
    a, b = min(nation_a_id, nation_b_id), max(nation_a_id, nation_b_id)
    row = db.query(Diplomacy).filter(Diplomacy.nation_a == a, Diplomacy.nation_b == b).first()
    return row.status if row else "neutral"


def is_at_war(db: Session, nation_a_id: int, nation_b_id: int) -> bool:
    return get_diplomacy_status(db, nation_a_id, nation_b_id) == "war"


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


@router.get("/friends", response_model=list[DiplomacyRelationResponse])
def list_friends(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    """Return accepted friends and pending friend requests (both incoming and outgoing)."""
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    rows = db.query(Diplomacy).filter(
        Diplomacy.status.in_(["friendly", "friend_pending"]),
        (Diplomacy.nation_a == nation.id) | (Diplomacy.nation_b == nation.id),
    ).all()

    result = []
    for row in rows:
        other_id = row.nation_b if row.nation_a == nation.id else row.nation_a
        other = db.get(Nation, other_id)
        if other:
            result.append(DiplomacyRelationResponse(
                nation_id=other.id,
                nation_name=other.name,
                status=row.status,
                updated_at=row.updated_at.isoformat(),
                requested_by=row.requested_by,
            ))
    return result


@router.get("/relations", response_model=list[DiplomacyRelationResponse])
def list_relations(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    """Return all non-neutral diplomatic relationships for the current nation."""
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    rows = db.query(Diplomacy).filter(
        Diplomacy.status != "neutral",
        (Diplomacy.nation_a == nation.id) | (Diplomacy.nation_b == nation.id),
    ).all()

    result = []
    for row in rows:
        other_id = row.nation_b if row.nation_a == nation.id else row.nation_a
        other = db.get(Nation, other_id)
        if other:
            result.append(DiplomacyRelationResponse(
                nation_id=other.id,
                nation_name=other.name,
                status=row.status,
                updated_at=row.updated_at.isoformat(),
            ))
    return result


@router.get("/{target_nation_id}", response_model=DiplomacyRelationResponse)
def get_relation(
    target_nation_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    """Return the current diplomacy status with a specific nation."""
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    target = db.get(Nation, target_nation_id)
    if not target:
        raise HTTPException(status_code=404, detail="Nation not found")

    row = _get_or_create_diplomacy(db, nation.id, target_nation_id)
    return DiplomacyRelationResponse(
        nation_id=target.id,
        nation_name=target.name,
        status=row.status,
        updated_at=row.updated_at.isoformat() if row.updated_at else datetime.now(timezone.utc).isoformat(),
        requested_by=row.requested_by,
    )


@router.put("/{target_nation_id}", status_code=200)
def set_relation(
    target_nation_id: int,
    body: SetStatusRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    """Set diplomacy status with another nation to war, neutral, or friendly."""
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    if target_nation_id == nation.id:
        raise HTTPException(status_code=409, detail="Cannot set diplomacy status with yourself")

    target = db.get(Nation, target_nation_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target nation not found")

    if body.status == "war":
        target_player = db.get(Player, target.player_id)
        if target_player and target_player.vacation_mode:
            raise HTTPException(status_code=409, detail="Cannot declare war on a nation in vacation mode")

    row = _get_or_create_diplomacy(db, nation.id, target.id)
    current_status = row.status

    if current_status in ("war", "war_pending") and body.status not in ("war", "war_pending"):
        raise HTTPException(
            status_code=409,
            detail="Wars can only end through a mutually agreed peace trade.",
        )

    # If already in a war-like state, don't re-declare
    if current_status in ("war", "war_pending") and body.status == "war":
        return {"status": current_status, "target_nation_id": target.id}

    if row.status == body.status:
        return {"status": row.status, "target_nation_id": target.id}

    now = datetime.now(timezone.utc)
    if body.status == "war":
        # Enter 2-tick grace period before hostilities begin
        row.status = "war_pending"
        row.war_starts_at = now + timedelta(hours=WAR_PENDING_HOURS)
        row.updated_at = now
        row.declared_by = nation.id   # immutable — never mutated after this point
        db.flush()
        # Notify both parties via event log
        db.add(Event(
            type="war_declared",
            payload={
                "declaring_nation_id": nation.id,
                "declaring_nation_name": nation.name,
                "target_nation_id": target.id,
                "target_nation_name": target.name,
                "war_starts_at": row.war_starts_at.isoformat(),
            },
            scheduled_for=now,
            processed_at=now,
            status="processed",
        ))
    else:
        row.status = body.status
        row.war_starts_at = None
        row.updated_at = now

    db.commit()
    return {"status": row.status, "target_nation_id": target.id}


@router.post("/{target_nation_id}/friend-request", status_code=200)
def send_friend_request(
    target_nation_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    if target_nation_id == nation.id:
        raise HTTPException(status_code=409, detail="Cannot send a friend request to yourself")

    target = db.get(Nation, target_nation_id)
    if not target:
        raise HTTPException(status_code=404, detail="Nation not found")

    row = _get_or_create_diplomacy(db, nation.id, target.id)
    if row.status in ("war", "war_pending"):
        raise HTTPException(status_code=409, detail="Cannot send a friend request while at war")
    if row.status == "friendly":
        return {"status": "friendly", "target_nation_id": target.id}
    if row.status == "friend_pending":
        return {"status": "friend_pending", "target_nation_id": target.id}

    now = datetime.now(timezone.utc)
    row.status = "friend_pending"
    row.requested_by = nation.id
    row.updated_at = now
    db.flush()
    db.add(Event(
        type="friend_request_received",
        payload={
            "requesting_nation_id": nation.id,
            "requesting_nation_name": nation.name,
            "target_nation_id": target.id,
            "target_nation_name": target.name,
        },
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))
    db.commit()
    return {"status": "friend_pending", "target_nation_id": target.id}


@router.post("/{target_nation_id}/accept-friend", status_code=200)
def accept_friend_request(
    target_nation_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    a, b = min(nation.id, target_nation_id), max(nation.id, target_nation_id)
    row = db.query(Diplomacy).filter(Diplomacy.nation_a == a, Diplomacy.nation_b == b).first()

    if not row or row.status != "friend_pending":
        raise HTTPException(status_code=409, detail="No pending friend request with this nation")
    if row.requested_by == nation.id:
        raise HTTPException(status_code=409, detail="Cannot accept your own outgoing friend request")

    row.status = "friendly"
    row.requested_by = None
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "friendly", "target_nation_id": target_nation_id}


@router.post("/{target_nation_id}/refuse-friend", status_code=200)
def refuse_friend_request(
    target_nation_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    """Refuse an incoming request, or cancel your own outgoing one."""
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    a, b = min(nation.id, target_nation_id), max(nation.id, target_nation_id)
    row = db.query(Diplomacy).filter(Diplomacy.nation_a == a, Diplomacy.nation_b == b).first()

    if not row or row.status != "friend_pending":
        raise HTTPException(status_code=409, detail="No pending friend request with this nation")

    row.status = "neutral"
    row.requested_by = None
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "neutral", "target_nation_id": target_nation_id}


@router.post("/{target_nation_id}/remove-friend", status_code=200)
def remove_friend(
    target_nation_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    """Unilaterally remove a friendly relationship. No confirmation from other player."""
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    a, b = min(nation.id, target_nation_id), max(nation.id, target_nation_id)
    row = db.query(Diplomacy).filter(Diplomacy.nation_a == a, Diplomacy.nation_b == b).first()

    if not row or row.status != "friendly":
        raise HTTPException(status_code=409, detail="Not currently friends with this nation")

    row.status = "neutral"
    row.requested_by = None
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "neutral", "target_nation_id": target_nation_id}


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


