from collections import deque
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.diplomacy import Diplomacy
from ..models.nation import Nation
from ..models.territory import Territory
from ..models.player import Player
from ..models.trade import Trade
from ..models.event import Event
from ..models.probe_data import ProbeData, ProbeDataAccess
from ..models.probe_visibility import ProbeVisibility
from ..routers.auth import get_current_player
from ..routers.diplomacy import is_at_war, _get_or_create_diplomacy
from ..services.pathfinding import compute_reachable_ids

router = APIRouter(prefix="/api/trade", tags=["trade"])

CONFIRM_COOLDOWN_SECONDS = 5
_TICK_HOURS = 2
_WAR_MIN_TICKS = 12       # war must last at least 12 ticks before peace
_PEACE_COOLDOWN_TICKS = 36  # post-peace lockout before re-declaration


class ProposeTradeRequest(BaseModel):
    to_nation_id: int
    offer_minerals: float = 0
    offer_fuel: float = 0
    offer_currency: float = 0
    request_minerals: float = 0
    request_fuel: float = 0
    request_currency: float = 0
    includes_peace: bool = False
    offer_territory_id: int | None = None
    request_territory_id: int | None = None
    offer_probe_data_ids: list[int] = []


class EditTradeRequest(BaseModel):
    offer_minerals: float = 0
    offer_fuel: float = 0
    offer_currency: float = 0
    request_minerals: float = 0
    request_fuel: float = 0
    request_currency: float = 0
    includes_peace: bool = False
    offer_territory_id: int | None = None
    request_territory_id: int | None = None
    offer_probe_data_ids: list[int] = []


def _trade_response(trade: Trade, db: Session, viewer_nation_id: int | None = None) -> dict:
    def _iso(dt):
        return dt.isoformat() if dt else None

    offer_terr = trade.offer_territory
    request_terr = trade.request_territory

    # Build probe data entries — coordinates are never exposed in trade responses.
    # Reachability is computed from the viewer's territory network when viewer is known.
    probe_ids: list[int] = trade.offer_probe_data_ids or []
    reachable_territory_ids: set[int] = set()
    if probe_ids and viewer_nation_id:
        all_territories = db.query(Territory).all()
        td = [
            {"id": t.id, "node_key": t.node_key, "territory_type": t.territory_type, "nation_id": t.nation_id}
            for t in all_territories
        ]
        for owned in (t for t in td if t["nation_id"] == viewer_nation_id):
            reachable_territory_ids |= compute_reachable_ids(owned["node_key"], viewer_nation_id, td)

    offer_probe_data = []
    for pd_id in probe_ids:
        pd = db.get(ProbeData, pd_id)
        if pd is None:
            continue  # deleted when territory was colonised
        t = db.get(Territory, pd.territory_id)
        entry: dict = {
            "probe_data_id": pd.id,
            "mineral_richness": float(pd.mineral_richness),
            "fuel_richness": float(pd.fuel_richness),
            "territory_type": t.territory_type if t else "normal",
        }
        if viewer_nation_id:
            entry["is_reachable"] = pd.territory_id in reachable_territory_ids
        offer_probe_data.append(entry)

    return {
        "id": trade.id,
        "from_nation_id": trade.from_nation_id,
        "from_nation_name": trade.from_nation.name,
        "to_nation_id": trade.to_nation_id,
        "to_nation_name": trade.to_nation.name,
        "offer_minerals": float(trade.offer_minerals),
        "offer_fuel": float(trade.offer_fuel),
        "offer_currency": float(trade.offer_currency),
        "request_minerals": float(trade.request_minerals),
        "request_fuel": float(trade.request_fuel),
        "request_currency": float(trade.request_currency),
        "status": trade.status,
        "created_at": _iso(trade.created_at),
        "resolved_at": _iso(trade.resolved_at),
        "from_accepted_at": _iso(trade.from_accepted_at),
        "from_confirmed_at": _iso(trade.from_confirmed_at),
        "to_accepted_at": _iso(trade.to_accepted_at),
        "to_confirmed_at": _iso(trade.to_confirmed_at),
        "includes_peace": trade.includes_peace,
        "offer_territory_id": trade.offer_territory_id,
        "offer_territory_name": (offer_terr.name or offer_terr.node_key) if offer_terr else None,
        "request_territory_id": trade.request_territory_id,
        "request_territory_name": (request_terr.name or request_terr.node_key) if request_terr else None,
        "offer_probe_data": offer_probe_data,
    }


def _parse_node_key(key: str) -> tuple[int, int] | None:
    parts = key.split(",")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _hex_neighbors(q: int, r: int) -> list[str]:
    return [
        f"{q+1},{r}",
        f"{q-1},{r}",
        f"{q},{r+1}",
        f"{q},{r-1}",
        f"{q+1},{r-1}",
        f"{q-1},{r+1}",
    ]


def _check_trade_route(db: Session, nation_a_id: int, nation_b_id: int) -> tuple[bool, str | None]:
    war_rows = db.query(Diplomacy).filter(Diplomacy.status == "war").all()

    hostile: set[int] = set()
    for row in war_rows:
        a, b = row.nation_a, row.nation_b
        if a == nation_a_id or b == nation_a_id:
            other = b if a == nation_a_id else a
            if other != nation_b_id:
                hostile.add(other)
        if a == nation_b_id or b == nation_b_id:
            other = b if a == nation_b_id else a
            if other != nation_a_id:
                hostile.add(other)

    territory_rows = db.query(Territory.node_key, Territory.nation_id).all()
    territory_map: dict[str, int | None] = {row.node_key: row.nation_id for row in territory_rows}

    source_keys = {key for key, owner in territory_map.items() if owner == nation_a_id}
    target_keys = {key for key, owner in territory_map.items() if owner == nation_b_id}

    if not source_keys:
        return False, "No owned territories to route from"
    if not target_keys:
        return False, "Target nation has no territories"

    visited: set[str] = set()
    queue: deque[str] = deque(source_keys)
    visited.update(source_keys)

    while queue:
        current = queue.popleft()
        if current in target_keys:
            return True, None

        coords = _parse_node_key(current)
        if coords is None:
            continue
        q, r = coords

        for neighbor_key in _hex_neighbors(q, r):
            if neighbor_key in visited:
                continue
            if neighbor_key not in territory_map:
                continue
            owner = territory_map[neighbor_key]
            if owner is not None and owner in hostile:
                continue
            visited.add(neighbor_key)
            queue.append(neighbor_key)

    return False, "No safe trade route exists between the two nations"


def _execute_trade(trade: Trade, proposer: Nation, recipient: Nation, now: datetime, db: Session):
    """Transfer resources atomically when both parties have confirmed."""
    if float(proposer.minerals) < float(trade.offer_minerals):
        raise HTTPException(status_code=409, detail="Proposer no longer has sufficient minerals")
    if float(proposer.fuel) < float(trade.offer_fuel):
        raise HTTPException(status_code=409, detail="Proposer no longer has sufficient fuel")
    if float(proposer.currency) < float(trade.offer_currency):
        raise HTTPException(status_code=409, detail="Proposer no longer has sufficient currency")
    if float(recipient.minerals) < float(trade.request_minerals):
        raise HTTPException(status_code=409, detail="Insufficient minerals to fulfill request")
    if float(recipient.fuel) < float(trade.request_fuel):
        raise HTTPException(status_code=409, detail="Insufficient fuel to fulfill request")
    if float(recipient.currency) < float(trade.request_currency):
        raise HTTPException(status_code=409, detail="Insufficient currency to fulfill request")

    proposer.minerals = float(proposer.minerals) - float(trade.offer_minerals) + float(trade.request_minerals)
    proposer.fuel     = float(proposer.fuel)     - float(trade.offer_fuel)     + float(trade.request_fuel)
    proposer.currency = float(proposer.currency) - float(trade.offer_currency) + float(trade.request_currency)

    recipient.minerals = float(recipient.minerals) - float(trade.request_minerals) + float(trade.offer_minerals)
    recipient.fuel     = float(recipient.fuel)     - float(trade.request_fuel)     + float(trade.offer_fuel)
    recipient.currency = float(recipient.currency) - float(trade.request_currency) + float(trade.offer_currency)

    if trade.offer_territory_id:
        terr = db.get(Territory, trade.offer_territory_id)
        if not terr or terr.nation_id != trade.from_nation_id:
            raise HTTPException(status_code=409, detail="Offered territory is no longer under proposer's control")
        terr.nation_id = trade.to_nation_id

    if trade.request_territory_id:
        terr = db.get(Territory, trade.request_territory_id)
        if not terr or terr.nation_id != trade.to_nation_id:
            raise HTTPException(status_code=409, detail="Requested territory is no longer under recipient's control")
        terr.nation_id = trade.from_nation_id

    if trade.includes_peace:
        diplo = _get_or_create_diplomacy(db, trade.from_nation_id, trade.to_nation_id)
        min_duration = timedelta(hours=_WAR_MIN_TICKS * _TICK_HOURS)
        if diplo.war_started_at is None or (now - diplo.war_started_at) < min_duration:
            raise HTTPException(
                status_code=409,
                detail=f"War must last at least {_WAR_MIN_TICKS} ticks before peace can be agreed",
            )
        diplo.status = "neutral"
        diplo.peace_until = now + timedelta(hours=_PEACE_COOLDOWN_TICKS * _TICK_HOURS)
        diplo.updated_at = now

    # Grant probe data access and map visibility to recipient
    for pd_id in (trade.offer_probe_data_ids or []):
        pd = db.get(ProbeData, pd_id)
        if pd is None:
            continue
        already = db.query(ProbeDataAccess).filter(
            ProbeDataAccess.probe_data_id == pd_id,
            ProbeDataAccess.granted_to == trade.to_nation_id,
        ).first()
        if not already:
            db.add(ProbeDataAccess(
                probe_data_id=pd_id,
                granted_to=trade.to_nation_id,
            ))
        vis_exists = db.query(ProbeVisibility).filter(
            ProbeVisibility.nation_id == trade.to_nation_id,
            ProbeVisibility.territory_id == pd.territory_id,
        ).first()
        if not vis_exists:
            db.add(ProbeVisibility(
                nation_id=trade.to_nation_id,
                territory_id=pd.territory_id,
            ))

    trade.status = "accepted"
    trade.resolved_at = now

    db.add(Event(
        type="trade_accepted",
        payload={
            "trade_id": trade.id,
            "from_nation_id": trade.from_nation_id,
            "to_nation_id": trade.to_nation_id,
            "includes_peace": trade.includes_peace,
            "offer_territory_id": trade.offer_territory_id,
            "request_territory_id": trade.request_territory_id,
        },
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))


@router.get("")
def list_trades(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    trades = db.query(Trade).filter(
        Trade.status == "pending",
        (Trade.from_nation_id == nation.id) | (Trade.to_nation_id == nation.id),
    ).all()

    return [_trade_response(t, db, viewer_nation_id=nation.id) for t in trades]


@router.get("/route/{nation_id}")
def check_trade_route(
    nation_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    target = db.get(Nation, nation_id)
    if not target:
        raise HTTPException(status_code=404, detail="Nation not found")

    has_route, reason = _check_trade_route(db, nation.id, nation_id)
    return {"has_route": has_route, "reason": reason}


@router.post("")
def propose_trade(
    body: ProposeTradeRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    if body.to_nation_id == nation.id:
        raise HTTPException(status_code=409, detail="Cannot trade with yourself")

    target = db.get(Nation, body.to_nation_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target nation not found")

    if is_at_war(db, nation.id, body.to_nation_id) and not body.includes_peace:
        raise HTTPException(
            status_code=409,
            detail="Cannot trade with a nation you are at war with. Include peace terms to negotiate.",
        )
    if body.includes_peace and not is_at_war(db, nation.id, body.to_nation_id):
        raise HTTPException(status_code=409, detail="Not currently at war with this nation")

    amounts = [
        body.offer_minerals, body.offer_fuel, body.offer_currency,
        body.request_minerals, body.request_fuel, body.request_currency,
    ]
    if any(v < 0 for v in amounts):
        raise HTTPException(status_code=422, detail="Trade amounts cannot be negative")

    offer_amounts = [body.offer_minerals, body.offer_fuel, body.offer_currency]
    request_amounts = [body.request_minerals, body.request_fuel, body.request_currency]
    has_resources = not all(v == 0 for v in offer_amounts + request_amounts)
    if not has_resources and not body.includes_peace and not body.offer_territory_id and not body.request_territory_id and not body.offer_probe_data_ids:
        raise HTTPException(status_code=422, detail="At least one trade term must be specified")

    if float(nation.minerals) < body.offer_minerals:
        raise HTTPException(status_code=409, detail="Insufficient minerals to offer")
    if float(nation.fuel) < body.offer_fuel:
        raise HTTPException(status_code=409, detail="Insufficient fuel to offer")
    if float(nation.currency) < body.offer_currency:
        raise HTTPException(status_code=409, detail="Insufficient currency to offer")

    if body.offer_territory_id:
        terr = db.get(Territory, body.offer_territory_id)
        if not terr or terr.nation_id != nation.id:
            raise HTTPException(status_code=403, detail="You do not control the offered territory")
        if terr.territory_type == "void":
            raise HTTPException(status_code=409, detail="Void territories cannot be traded")

    if body.request_territory_id:
        terr = db.get(Territory, body.request_territory_id)
        if not terr or terr.nation_id != target.id:
            raise HTTPException(status_code=409, detail="Target nation does not control the requested territory")
        if terr.territory_type == "void":
            raise HTTPException(status_code=409, detail="Void territories cannot be traded")

    for pd_id in body.offer_probe_data_ids:
        pd = db.get(ProbeData, pd_id)
        if not pd or pd.discovered_by != nation.id:
            raise HTTPException(status_code=403, detail=f"Probe data {pd_id} not found in your intelligence")

    if not body.includes_peace:
        has_route, reason = _check_trade_route(db, nation.id, body.to_nation_id)
        if not has_route:
            raise HTTPException(status_code=409, detail=reason or "No trade route exists")

    now = datetime.now(timezone.utc)
    trade = Trade(
        from_nation_id=nation.id,
        to_nation_id=body.to_nation_id,
        offer_minerals=body.offer_minerals,
        offer_fuel=body.offer_fuel,
        offer_currency=body.offer_currency,
        request_minerals=body.request_minerals,
        request_fuel=body.request_fuel,
        request_currency=body.request_currency,
        status="pending",
        from_accepted_at=now,
        includes_peace=body.includes_peace,
        offer_territory_id=body.offer_territory_id,
        request_territory_id=body.request_territory_id,
        offer_probe_data_ids=body.offer_probe_data_ids,
    )
    db.add(trade)
    db.flush()

    db.add(Event(
        type="trade_proposed",
        payload={
            "trade_id": trade.id,
            "from_nation_id": nation.id,
            "from_nation_name": nation.name,
            "to_nation_id": target.id,
            "to_nation_name": target.name,
        },
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))

    db.commit()
    db.refresh(trade)
    return _trade_response(trade, db, viewer_nation_id=nation.id)


@router.put("/{trade_id}")
def edit_trade(
    trade_id: int,
    body: EditTradeRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    """Edit trade terms. Either party may edit. Resets all confirmation state."""
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    trade = db.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    if trade.from_nation_id != nation.id and trade.to_nation_id != nation.id:
        raise HTTPException(status_code=403, detail="Not a party to this trade")

    if trade.status != "pending":
        raise HTTPException(status_code=409, detail="Trade is no longer pending")

    amounts = [
        body.offer_minerals, body.offer_fuel, body.offer_currency,
        body.request_minerals, body.request_fuel, body.request_currency,
    ]
    if any(v < 0 for v in amounts):
        raise HTTPException(status_code=422, detail="Trade amounts cannot be negative")

    has_resources = not all(v == 0 for v in amounts)
    if not has_resources and not body.includes_peace and not body.offer_territory_id and not body.request_territory_id and not body.offer_probe_data_ids:
        raise HTTPException(status_code=422, detail="At least one trade term must be specified")

    from_id = trade.from_nation_id
    to_id   = trade.to_nation_id

    if body.offer_territory_id:
        terr = db.get(Territory, body.offer_territory_id)
        if not terr or terr.nation_id != from_id:
            raise HTTPException(status_code=403, detail="You do not control the offered territory")
        if terr.territory_type == "void":
            raise HTTPException(status_code=409, detail="Void territories cannot be traded")

    if body.request_territory_id:
        terr = db.get(Territory, body.request_territory_id)
        if not terr or terr.nation_id != to_id:
            raise HTTPException(status_code=409, detail="Target nation does not control the requested territory")
        if terr.territory_type == "void":
            raise HTTPException(status_code=409, detail="Void territories cannot be traded")

    for pd_id in body.offer_probe_data_ids:
        pd = db.get(ProbeData, pd_id)
        if not pd or pd.discovered_by != from_id:
            raise HTTPException(status_code=403, detail=f"Probe data {pd_id} not found in proposer's intelligence")

    trade.offer_minerals        = body.offer_minerals
    trade.offer_fuel            = body.offer_fuel
    trade.offer_currency        = body.offer_currency
    trade.request_minerals      = body.request_minerals
    trade.request_fuel          = body.request_fuel
    trade.request_currency      = body.request_currency
    trade.includes_peace        = body.includes_peace
    trade.offer_territory_id    = body.offer_territory_id
    trade.request_territory_id  = body.request_territory_id
    trade.offer_probe_data_ids  = body.offer_probe_data_ids

    # Reset all confirmation state for both parties
    trade.from_accepted_at  = None
    trade.from_confirmed_at = None
    trade.to_accepted_at    = None
    trade.to_confirmed_at   = None

    db.commit()
    db.refresh(trade)
    return _trade_response(trade, db, viewer_nation_id=nation.id)


@router.post("/{trade_id}/accept")
def accept_trade(
    trade_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    """
    Two-click confirmation per party:
    - First click: sets accepted_at (starts 5s cooldown)
    - Second click (≥5s after first): sets confirmed_at
    - When both confirmed → execute trade
    """
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    trade = db.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    if trade.from_nation_id != nation.id and trade.to_nation_id != nation.id:
        raise HTTPException(status_code=403, detail="Not a party to this trade")

    if trade.status != "pending":
        raise HTTPException(status_code=409, detail="Trade is no longer pending")

    now = datetime.now(timezone.utc)
    is_from = trade.from_nation_id == nation.id

    if is_from:
        accepted_at  = trade.from_accepted_at
        confirmed_at = trade.from_confirmed_at
    else:
        accepted_at  = trade.to_accepted_at
        confirmed_at = trade.to_confirmed_at

    if confirmed_at is not None:
        return _trade_response(trade, db, viewer_nation_id=nation.id)  # already fully confirmed on this side, no-op

    if accepted_at is None:
        # First click: start cooldown
        if is_from:
            trade.from_accepted_at = now
        else:
            trade.to_accepted_at = now
    else:
        # Second click: require cooldown elapsed
        elapsed = (now - accepted_at.replace(tzinfo=timezone.utc) if accepted_at.tzinfo is None else now - accepted_at).total_seconds()
        if elapsed < CONFIRM_COOLDOWN_SECONDS:
            raise HTTPException(
                status_code=409,
                detail=f"Wait {CONFIRM_COOLDOWN_SECONDS - int(elapsed)}s before confirming"
            )
        if is_from:
            trade.from_confirmed_at = now
        else:
            trade.to_confirmed_at = now

    # Check if both sides are now confirmed
    if trade.from_confirmed_at and trade.to_confirmed_at:
        proposer  = db.get(Nation, trade.from_nation_id)
        recipient = db.get(Nation, trade.to_nation_id)
        _execute_trade(trade, proposer, recipient, now, db)

    db.commit()
    db.refresh(trade)
    return _trade_response(trade, db, viewer_nation_id=nation.id)


@router.post("/{trade_id}/reject")
def reject_trade(
    trade_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    trade = db.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    if trade.to_nation_id != nation.id:
        raise HTTPException(status_code=403, detail="This trade was not sent to your nation")

    if trade.status != "pending":
        raise HTTPException(status_code=409, detail="Trade is no longer pending")

    now = datetime.now(timezone.utc)
    trade.status = "rejected"
    trade.resolved_at = now

    db.add(Event(
        type="trade_rejected",
        payload={
            "trade_id": trade.id,
            "from_nation_id": trade.from_nation_id,
            "to_nation_id": trade.to_nation_id,
        },
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))

    db.commit()
    db.refresh(trade)
    return _trade_response(trade, db, viewer_nation_id=nation.id)


@router.post("/{trade_id}/cancel")
def cancel_trade(
    trade_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    trade = db.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    if trade.from_nation_id != nation.id:
        raise HTTPException(status_code=403, detail="This is not your outgoing trade")

    if trade.status != "pending":
        raise HTTPException(status_code=409, detail="Trade is no longer pending")

    now = datetime.now(timezone.utc)
    trade.status = "cancelled"
    trade.resolved_at = now

    db.add(Event(
        type="trade_cancelled",
        payload={
            "trade_id": trade.id,
            "from_nation_id": trade.from_nation_id,
            "to_nation_id": trade.to_nation_id,
        },
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))

    db.commit()
    db.refresh(trade)
    return _trade_response(trade, db, viewer_nation_id=nation.id)
