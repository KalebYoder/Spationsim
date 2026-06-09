from collections import deque
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_
from ..db.database import get_db
from ..models.territory import Territory
from ..models.nation import Nation
from ..models.player import Player
from ..models.probe_data import ProbeData
from ..models.probe_visibility import ProbeVisibility
from ..models.fleet import Fleet
from ..models.probe import Probe
from ..models.diplomacy import Diplomacy
from ..schemas.nation import TerritoryResponse, TerritoryMapResponse, TerritoryRenameRequest
from ..routers.auth import get_current_player

RENAME_COOLDOWN_HOURS = 24  # 12 ticks × 2 h/tick

router = APIRouter(prefix="/api/territories", tags=["territories"])

_HEX_NEIGHBORS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]


def _compute_detail_visible_ids(nation_id: int, db: Session) -> set[int]:
    all_territories = db.query(Territory).all()
    by_key: dict[str, Territory] = {t.node_key: t for t in all_territories}

    seeds: set[int] = set()

    own_ids = {
        t_id for (t_id,) in
        db.query(Territory.id).filter(Territory.nation_id == nation_id).all()
    }
    seeds |= own_ids

    stationed_fleets = db.query(Fleet).filter(
        Fleet.nation_id == nation_id,
        Fleet.status == "stationed",
        Fleet.origin_territory.isnot(None),
    ).all()
    for f in stationed_fleets:
        seeds.add(f.origin_territory)

    moving_fleets = db.query(Fleet).filter(
        Fleet.nation_id == nation_id,
        Fleet.status.in_(["pending_confirmation", "holding", "engaged", "post_battle_choice", "in_transit"]),
        Fleet.destination_territory.isnot(None),
    ).all()
    for f in moving_fleets:
        seeds.add(f.destination_territory)

    probes = db.query(Probe).filter(
        Probe.nation_id == nation_id,
        Probe.current_territory.isnot(None),
    ).all()
    for p in probes:
        seeds.add(p.current_territory)

    visited: set[int] = set()
    queue: deque[tuple[int, int]] = deque()

    by_id: dict[int, Territory] = {t.id: t for t in all_territories}

    for seed_id in seeds:
        if seed_id not in visited:
            visited.add(seed_id)
            queue.append((seed_id, 0))

    while queue:
        t_id, dist = queue.popleft()
        if t_id not in by_id:
            continue
        t = by_id[t_id]
        if dist >= 3:
            continue
        q, r = map(int, t.node_key.split(","))
        for dq, dr in _HEX_NEIGHBORS:
            nkey = f"{q + dq},{r + dr}"
            if nkey not in by_key:
                continue
            neighbor = by_key[nkey]
            if neighbor.id not in visited:
                visited.add(neighbor.id)
                queue.append((neighbor.id, dist + 1))

    return visited


@router.get("", response_model=list[TerritoryMapResponse])
def all_territories(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()

    # Territories whose richness values are visible (own + probe_data)
    revealed_ids: set[int] = set()
    # Territories visible as probe path tiles (existence only, no richness)
    visibility_ids: set[int] = set()
    detail_ids: set[int] = set()

    if nation:
        own_ids = {
            t_id for (t_id,) in
            db.query(Territory.id).filter(Territory.nation_id == nation.id).all()
        }
        probed_ids = {
            t_id for (t_id,) in
            db.query(ProbeData.territory_id).filter(ProbeData.discovered_by == nation.id).all()
        }
        visibility_ids = {
            t_id for (t_id,) in
            db.query(ProbeVisibility.territory_id).filter(ProbeVisibility.nation_id == nation.id).all()
        }
        revealed_ids = own_ids | probed_ids
        detail_ids = _compute_detail_visible_ids(nation.id, db)

    # Visible = claimed by anyone (spec: colonized territories are visible to all)
    #         + probe path tiles seen by this player
    rows = (
        db.query(Territory, Nation.name)
        .outerjoin(Nation, Territory.nation_id == Nation.id)
        .filter(
            or_(
                Territory.nation_id.is_not(None),   # any claimed territory
                Territory.id.in_(visibility_ids),   # probe path tile
            )
        )
        .all()
    )
    return [
        TerritoryMapResponse(
            id=t.id,
            node_key=t.node_key,
            territory_type=t.territory_type,
            distance_from_center=t.distance_from_center,
            is_owned=t.is_owned,
            nation_id=t.nation_id,
            nation_name=name,
            mineral_richness=float(t.mineral_richness) if t.id in revealed_ids else None,
            fuel_richness=float(t.fuel_richness) if t.id in revealed_ids else None,
            detail_visible=t.id in detail_ids,
        )
        for t, name in rows
    ]


@router.get("/map-fleets")
def map_fleets(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        return []

    detail_ids = _compute_detail_visible_ids(nation.id, db)
    if not detail_ids:
        return []

    all_fleets = db.query(Fleet).filter(Fleet.unit_count > 0).all()

    # Collect territory IDs needed for lookup (all endpoints, not filtered yet)
    territory_ids_needed: set[int] = set()
    for f in all_fleets:
        if f.origin_territory:
            territory_ids_needed.add(f.origin_territory)
        if f.destination_territory:
            territory_ids_needed.add(f.destination_territory)

    relevant_territories = db.query(Territory).filter(
        Territory.id.in_(territory_ids_needed)
    ).all()
    territory_map: dict[int, Territory] = {t.id: t for t in relevant_territories}

    def _get_relation(fleet_nation_id: int) -> str:
        if fleet_nation_id == nation.id:
            return "own"
        a = min(nation.id, fleet_nation_id)
        b = max(nation.id, fleet_nation_id)
        row = db.query(Diplomacy).filter(
            Diplomacy.status == "war",
            Diplomacy.nation_a == a,
            Diplomacy.nation_b == b,
        ).first()
        return "hostile" if row else "neutral"

    relation_cache: dict[int, str] = {}

    # --- Stationary/arrived fleets → circles ---
    # Group by (territory_id, fleet.nation_id); location must be in detail_ids
    circle_groups: dict[tuple[int, int], dict] = {}
    for f in all_fleets:
        if f.status == "in_transit":
            continue
        loc = f.origin_territory if f.status == "stationed" else f.destination_territory
        if loc is None or loc not in territory_map or loc not in detail_ids:
            continue
        key = (loc, f.nation_id)
        if key not in circle_groups:
            if f.nation_id not in relation_cache:
                relation_cache[f.nation_id] = _get_relation(f.nation_id)
            t = territory_map[loc]
            circle_groups[key] = {
                "territory_id": loc,
                "node_key": t.node_key,
                "nation_id": f.nation_id,
                "total_power": 0,
                "relation": relation_cache[f.nation_id],
                "status": f.status,
            }
        circle_groups[key]["total_power"] += f.unit_count * 2

    # --- In-transit fleets → triangles ---
    # Visible if origin OR destination is within detail range.
    # Group by (nation_id, origin_territory, destination_territory).
    transit_groups: dict[tuple[int, int, int], dict] = {}
    for f in all_fleets:
        if f.status != "in_transit":
            continue
        oid, did = f.origin_territory, f.destination_territory
        if oid is None or did is None:
            continue
        if oid not in detail_ids and did not in detail_ids:
            continue
        origin_t = territory_map.get(oid)
        dest_t = territory_map.get(did)
        if origin_t is None or dest_t is None:
            continue
        key = (f.nation_id, oid, did)
        if key not in transit_groups:
            if f.nation_id not in relation_cache:
                relation_cache[f.nation_id] = _get_relation(f.nation_id)
            transit_groups[key] = {
                "territory_id": None,
                "node_key": None,
                "origin_node_key": origin_t.node_key,
                "destination_node_key": dest_t.node_key,
                "departs_at": f.departs_at.isoformat() if f.departs_at else None,
                "arrives_at": f.arrives_at.isoformat() if f.arrives_at else None,
                "nation_id": f.nation_id,
                "total_power": 0,
                "relation": relation_cache[f.nation_id],
                "status": "in_transit",
            }
        transit_groups[key]["total_power"] += f.unit_count * 2

    return list(circle_groups.values()) + list(transit_groups.values())


@router.get("/available", response_model=list[TerritoryResponse])
def available_territories(db: Session = Depends(get_db)):
    return (
        db.query(Territory)
        .filter(Territory.is_owned == False, Territory.territory_type == 'normal')
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
