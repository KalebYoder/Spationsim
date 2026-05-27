from fastapi import APIRouter, Depends, Query
from sqlalchemy import cast, Integer, or_
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models.event import Event
from ..models.nation import Nation
from ..models.player import Player
from ..models.resource_log import ResourceLog
from ..routers.auth import get_current_player

router = APIRouter(prefix="/api/events", tags=["events"])

# Event types that are relevant to a specific nation identified by payload field
_NATION_ID_TYPES = {
    "fleet_stationed",
    "fleet_recalled_on_expiry",
    "fleet_holding_at_enemy_territory",
    "probe_stationed",
    "probe_destroyed_in_enemy_territory",
    "colony_ship_stationed",
}
_ATTACKER_TYPES = {"fleet_arrived_at_enemy_territory"}
_DEFENDER_TYPES = {"enemy_fleet_arrived"}
_PROBE_NATION_TYPES = {"probe_destroyed_in_enemy_territory"}
_TERRITORY_NATION_TYPES = {"enemy_probe_detected_and_destroyed"}


@router.get("/log")
def get_event_log(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        return []

    nid = nation.id

    # Fetch the last `limit` resource_log entries for this nation
    resource_logs = (
        db.query(ResourceLog)
        .filter(ResourceLog.nation_id == nid)
        .order_by(ResourceLog.tick_at.desc())
        .limit(limit)
        .all()
    )

    # Fetch relevant events: any event where this nation appears in a known payload field
    relevant_events = (
        db.query(Event)
        .filter(
            Event.type.notin_(["tick"]),
            or_(
                Event.payload["nation_id"].astext.cast(Integer) == nid,
                Event.payload["attacker_nation_id"].astext.cast(Integer) == nid,
                Event.payload["defender_nation_id"].astext.cast(Integer) == nid,
                Event.payload["probe_nation_id"].astext.cast(Integer) == nid,
                Event.payload["territory_nation_id"].astext.cast(Integer) == nid,
            ),
        )
        .order_by(Event.scheduled_for.desc())
        .limit(limit * 10)
        .all()
    )

    # Build a unified set of tick timestamps from both sources
    tick_timestamps = {rl.tick_at for rl in resource_logs}
    for ev in relevant_events:
        tick_timestamps.add(ev.scheduled_for)

    # Index resource_log and events by tick timestamp
    economy_by_tick = {rl.tick_at: rl for rl in resource_logs}
    events_by_tick: dict = {}
    for ev in relevant_events:
        events_by_tick.setdefault(ev.scheduled_for, []).append(ev)

    # Sort ticks newest-first, apply limit
    sorted_ticks = sorted(tick_timestamps, reverse=True)[:limit]

    result = []
    for tick_at in sorted_ticks:
        rl = economy_by_tick.get(tick_at)
        economy = None
        if rl:
            economy = {
                "minerals_delta": float(rl.minerals_delta or 0),
                "fuel_delta": float(rl.fuel_delta or 0),
                "population_delta": int(rl.population_delta or 0),
                "currency_delta": float(rl.currency_delta or 0),
            }

        tick_events = [
            {"type": ev.type, "payload": ev.payload}
            for ev in events_by_tick.get(tick_at, [])
        ]

        result.append({
            "tick_at": tick_at.isoformat(),
            "economy": economy,
            "events": tick_events,
        })

    return result
