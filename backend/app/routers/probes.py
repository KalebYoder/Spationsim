from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.infrastructure import Infrastructure
from ..models.nation import Nation
from ..models.event import Event
from ..models.probe import Probe
from ..models.probe_data import ProbeData
from ..models.territory import Territory
from ..models.player import Player
from ..schemas.nation import (
    ManufactureRequest, NationResponse, ProbeStatsResponse,
    DispatchProbeRequest, ProbeResponse, ProbeDataResponse,
)
from ..routers.auth import get_current_player
from ..constants import PROBE_STATS, PROBE_RANGE

router = APIRouter(prefix="/api/probes", tags=["probes"])


def _parse_key(key: str):
    q, r = key.split(",")
    return int(q), int(r)


def _hex_dist(q1, r1, q2, r2):
    dq, dr = q2 - q1, r2 - r1
    return max(abs(dq), abs(dr), abs(dq + dr))


def _probe_response(probe: Probe, db: Session) -> ProbeResponse:
    origin_t = db.get(Territory, probe.origin_territory) if probe.origin_territory else None
    current_t = db.get(Territory, probe.current_territory) if probe.current_territory else None
    dest_t = db.get(Territory, probe.destination_territory) if probe.destination_territory else None
    return ProbeResponse(
        id=probe.id,
        status=probe.status,
        origin_node_key=origin_t.node_key if origin_t else None,
        origin_name=origin_t.name if origin_t else None,
        current_node_key=current_t.node_key if current_t else None,
        destination_node_key=dest_t.node_key if dest_t else None,
        destination_name=dest_t.name if dest_t else None,
        arrives_at=probe.arrives_at.isoformat() if probe.arrives_at else None,
        departs_at=probe.departs_at.isoformat() if probe.departs_at else None,
    )


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
        manufacture_cost_currency=PROBE_STATS["manufacture_cost_currency"],
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
        .filter(Territory.nation_id == nation.id, Infrastructure.type == "shipyard")
        .first()
    )
    if not has_factory:
        raise HTTPException(status_code=409, detail="You need a shipyard to manufacture probes")

    mineral_cost = PROBE_STATS["manufacture_cost_minerals"] * body.quantity
    fuel_cost = PROBE_STATS["manufacture_cost_fuel"] * body.quantity
    currency_cost = PROBE_STATS["manufacture_cost_currency"] * body.quantity

    if nation.minerals < mineral_cost or nation.fuel < fuel_cost or nation.currency < currency_cost:
        raise HTTPException(status_code=409, detail="Insufficient resources")

    nation.minerals -= mineral_cost
    nation.fuel -= fuel_cost
    nation.currency -= currency_cost
    nation.probes_reserve += body.quantity

    db.commit()
    db.refresh(nation)
    return nation


@router.get("/active", response_model=list[ProbeResponse])
def get_active_probes(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    probes = (
        db.query(Probe)
        .filter(
            Probe.nation_id == nation.id,
            Probe.status.in_(["in_transit", "stationed"]),
        )
        .all()
    )
    return [_probe_response(p, db) for p in probes]


@router.post("/dispatch", response_model=ProbeResponse)
def dispatch_probe(
    body: DispatchProbeRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    if nation.probes_reserve < 1:
        raise HTTPException(status_code=409, detail="No probes in reserve")

    from_t = db.get(Territory, body.from_territory_id)
    if not from_t or from_t.nation_id != nation.id or not from_t.is_owned:
        raise HTTPException(status_code=409, detail="Origin must be an owned, colonized territory")
    if from_t.territory_type == "void":
        raise HTTPException(status_code=409, detail="Cannot launch from void territory")

    to_t = db.get(Territory, body.to_territory_id)
    if not to_t:
        raise HTTPException(status_code=404, detail="Destination territory not found")
    if to_t.territory_type == "void":
        raise HTTPException(status_code=409, detail="Cannot probe void territory")

    owned_territories = (
        db.query(Territory)
        .filter(Territory.nation_id == nation.id, Territory.is_owned == True)
        .all()
    )

    dq, dr = _parse_key(to_t.node_key)
    min_dist = min(
        _hex_dist(*_parse_key(ot.node_key), dq, dr)
        for ot in owned_territories
    )
    if min_dist > PROBE_RANGE:
        raise HTTPException(status_code=409, detail="Destination is out of probe range")

    now = datetime.now(timezone.utc)
    fq, fr = _parse_key(from_t.node_key)
    distance = _hex_dist(fq, fr, dq, dr)

    nation.probes_reserve -= 1

    if distance == 0:
        probe = Probe(
            nation_id=nation.id,
            origin_territory=from_t.id,
            current_territory=from_t.id,
            destination_territory=None,
            status="stationed",
            departs_at=now,
            arrives_at=None,
        )
    else:
        arrives_at = now + timedelta(hours=2 * distance)
        probe = Probe(
            nation_id=nation.id,
            origin_territory=from_t.id,
            current_territory=from_t.id,
            destination_territory=to_t.id,
            status="in_transit",
            departs_at=now,
            arrives_at=arrives_at,
        )

    db.add(probe)
    db.commit()
    db.refresh(probe)
    return _probe_response(probe, db)


@router.post("/{probe_id}/recall", response_model=ProbeResponse)
def recall_probe(
    probe_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    probe = db.get(Probe, probe_id)
    if not probe or probe.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="Probe not found or does not belong to you")

    if probe.status != "in_transit":
        raise HTTPException(status_code=409, detail="Only in-transit probes can be recalled")

    origin = db.get(Territory, probe.origin_territory)
    current = db.get(Territory, probe.current_territory)
    if not origin or not current:
        raise HTTPException(status_code=409, detail="Probe territory data is inconsistent")

    now = datetime.now(timezone.utc)

    if current.id == origin.id:
        probe.status = "stationed"
        probe.destination_territory = None
        probe.arrives_at = None
        probe.departs_at = None
    else:
        cq, cr = _parse_key(current.node_key)
        oq, or_ = _parse_key(origin.node_key)
        distance = _hex_dist(cq, cr, oq, or_)
        probe.destination_territory = origin.id
        probe.arrives_at = now + timedelta(hours=2 * distance)

    db.add(Event(
        type="probe_recalled",
        payload={
            "probe_id": probe.id,
            "nation_id": nation.id,
            "current_territory_id": current.id,
            "origin_territory_id": origin.id,
            "recalled_at": now.isoformat(),
        },
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))

    db.commit()
    db.refresh(probe)
    return _probe_response(probe, db)


@router.get("/data", response_model=list[ProbeDataResponse])
def get_probe_data(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    rows = (
        db.query(ProbeData, Territory, Nation)
        .join(Territory, ProbeData.territory_id == Territory.id)
        .outerjoin(Nation, Territory.nation_id == Nation.id)
        .filter(ProbeData.discovered_by == nation.id)
        .order_by(ProbeData.discovered_at.desc())
        .all()
    )

    result = []
    for pd, t, n in rows:
        result.append(ProbeDataResponse(
            id=pd.id,
            territory_id=t.id,
            node_key=t.node_key,
            territory_name=t.name,
            mineral_richness=float(pd.mineral_richness),
            fuel_richness=float(pd.fuel_richness),
            discovered_at=pd.discovered_at.isoformat(),
            is_owned=t.is_owned,
            nation_id=n.id if n else None,
            nation_name=n.name if n else None,
        ))
    return result
