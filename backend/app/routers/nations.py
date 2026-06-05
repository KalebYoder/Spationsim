from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, cast, case, func as sqlfunc, Integer, or_
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.event import Event
from ..models.fleet import Fleet
from ..models.infrastructure import Infrastructure
from ..models.nation import Nation
from ..models.territory import Territory
from ..models.territory_population import TerritoryPopulation
from ..models.territory_dissent import TerritoryDissent
from ..models.tutorial import TutorialState
from ..models.player import Player
from ..schemas.nation import NationCreateRequest, NationResponse, PublicNationResponse, TerritoryResponse
from ..schemas.messaging import NationListItem
from ..routers.auth import get_current_player
from ..constants import POPULATION_START, UNIT_STATS, TERRITORY_UPKEEP_K, LOGISTICS_FUEL_K
from ..services.logistics import compute_logistics_fuel_cost

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

    nation.max_colonized_territory_count = 1  # home territory

    db.add(TerritoryPopulation(
        territory_id=territory.id,
        current=POPULATION_START,
    ))
    db.add(TerritoryDissent(territory_id=territory.id, dissent=0))
    db.add(TutorialState(nation_id=nation.id))

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


@router.get("/mine/territories/yields")
def get_territory_yields(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    from ..services.territory_yield import compute_territory_yield, dissent_production_modifier

    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    territories = db.query(Territory).filter(Territory.nation_id == nation.id).all()
    territory_ids = [t.id for t in territories]
    if not territory_ids:
        return []

    facility_rows = (
        db.query(Infrastructure.territory_id, Infrastructure.type, sqlfunc.count())
        .filter(
            Infrastructure.territory_id.in_(territory_ids),
            Infrastructure.type.in_(["mine", "refinery"]),
            Infrastructure.status == "active",
        )
        .group_by(Infrastructure.territory_id, Infrastructure.type)
        .all()
    )
    mine_counts: dict[int, int] = {}
    refinery_counts: dict[int, int] = {}
    for tid, ftype, cnt in facility_rows:
        if ftype == "mine":
            mine_counts[tid] = cnt
        else:
            refinery_counts[tid] = cnt

    fleet_rows = (
        db.query(Fleet.origin_territory, sqlfunc.sum(Fleet.unit_count))
        .filter(
            Fleet.nation_id == nation.id,
            Fleet.status == "stationed",
            Fleet.origin_territory.in_(territory_ids),
        )
        .group_by(Fleet.origin_territory)
        .all()
    )
    stationed: dict[int, int] = {tid: int(cnt) for tid, cnt in fleet_rows}

    dissent_map = {
        r.territory_id: r.dissent
        for r in db.query(TerritoryDissent).filter(TerritoryDissent.territory_id.in_(territory_ids)).all()
    }

    n = len(territories)
    # Per-territory share of nation-wide currency upkeep (k × N² total, k × N each).
    territory_upkeep_currency = TERRITORY_UPKEEP_K * n if n > 0 else 0
    # Per-territory share of logistics fuel upkeep (k × N(N+1)/2 total, divided evenly).
    logistics_fuel_total = compute_logistics_fuel_cost(n, k=LOGISTICS_FUEL_K)
    logistics_fuel_per_territory = round(logistics_fuel_total / n) if n > 0 else 0

    result = []
    for t in territories:
        y = compute_territory_yield(
            territory_type=t.territory_type,
            mineral_richness=float(t.mineral_richness),
            fuel_richness=float(t.fuel_richness),
            mine_count=mine_counts.get(t.id, 0),
            refinery_count=refinery_counts.get(t.id, 0),
            stationed_fighters=stationed.get(t.id, 0),
            dissent_modifier=dissent_production_modifier(dissent_map.get(t.id, 0)),
        )
        result.append({
            "territory_id": t.id,
            "dissent": dissent_map.get(t.id, 0),
            "dissent_modifier": round(dissent_production_modifier(dissent_map.get(t.id, 0)), 4),
            **y,
            "territory_upkeep_currency_per_tick": territory_upkeep_currency,
            "logistics_fuel_upkeep_per_tick": logistics_fuel_per_territory,
            "fuel_net_per_tick": y["fuel_per_tick"] - logistics_fuel_per_territory,
            # Override: full net includes fighter upkeep + territory upkeep
            "currency_net_per_tick": y["currency_net_per_tick"] - territory_upkeep_currency,
        })
    return result


@router.get("/mine/territories", response_model=list[TerritoryResponse])
def get_my_territories(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    territories = db.query(Territory).filter(Territory.nation_id == nation.id).all()
    t_ids = [t.id for t in territories]
    dissent_map = {
        r.territory_id: r.dissent
        for r in db.query(TerritoryDissent).filter(TerritoryDissent.territory_id.in_(t_ids)).all()
    } if t_ids else {}
    return [
        {
            "id": t.id,
            "node_key": t.node_key,
            "name": t.name,
            "territory_type": t.territory_type,
            "mineral_richness": float(t.mineral_richness),
            "fuel_richness": float(t.fuel_richness),
            "distance_from_center": t.distance_from_center,
            "is_colonized": t.is_colonized,
            "dissent": dissent_map.get(t.id, 0),
        }
        for t in territories
    ]


@router.get("/{nation_id}/territories", response_model=list[TerritoryResponse])
def get_nation_territories(
    nation_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.get(Nation, nation_id)
    if not nation:
        raise HTTPException(status_code=404, detail="Nation not found")
    return (
        db.query(Territory)
        .filter(Territory.nation_id == nation_id, Territory.is_colonized == True)
        .all()
    )


@router.get("/list")
def list_other_nations(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    others = db.query(Nation).order_by(Nation.name).all()
    return [
        {"id": n.id, "name": n.name}
        for n in others
        if nation is None or n.id != nation.id
    ]


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


@router.get("/{nation_id}/wars")
def get_nation_wars(
    nation_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    if not db.get(Nation, nation_id):
        raise HTTPException(status_code=404, detail="Nation not found")

    war_events = (
        db.query(Event)
        .filter(
            Event.type == "war_declared",
            or_(
                Event.payload["declaring_nation_id"].astext.cast(Integer) == nation_id,
                Event.payload["target_nation_id"].astext.cast(Integer) == nation_id,
            ),
        )
        .order_by(Event.scheduled_for.desc())
        .all()
    )

    result = []
    for ev in war_events:
        declaring_id = int(ev.payload["declaring_nation_id"])
        target_id = int(ev.payload["target_nation_id"])
        if declaring_id == nation_id:
            opponent_id = target_id
            opponent_name = ev.payload.get("target_nation_name", f"Nation #{target_id}")
        else:
            opponent_id = declaring_id
            opponent_name = ev.payload.get("declaring_nation_name", f"Nation #{declaring_id}")

        peace_event = (
            db.query(Event)
            .filter(
                Event.type == "trade_accepted",
                Event.payload["includes_peace"].astext == "true",
                Event.scheduled_for >= ev.scheduled_for,
                or_(
                    and_(
                        Event.payload["from_nation_id"].astext.cast(Integer) == nation_id,
                        Event.payload["to_nation_id"].astext.cast(Integer) == opponent_id,
                    ),
                    and_(
                        Event.payload["from_nation_id"].astext.cast(Integer) == opponent_id,
                        Event.payload["to_nation_id"].astext.cast(Integer) == nation_id,
                    ),
                ),
            )
            .order_by(Event.scheduled_for.asc())
            .first()
        )

        result.append({
            "opponent_id": opponent_id,
            "opponent_name": opponent_name,
            "declared_at": ev.scheduled_for.isoformat(),
            "ended_at": peace_event.scheduled_for.isoformat() if peace_event else None,
            "is_active": peace_event is None,
        })

    return result


@router.get("/{nation_id}/wars/{opponent_id}/log")
def get_war_combat_log(
    nation_id: int,
    opponent_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.get(Nation, nation_id)
    opponent = db.get(Nation, opponent_id)
    if not nation or not opponent:
        raise HTTPException(status_code=404, detail="Nation not found")

    combat_events = (
        db.query(Event)
        .filter(
            Event.type.in_(["combat_round", "resources_drained_by_occupation"]),
            or_(
                and_(
                    Event.payload["attacker_nation_id"].astext.cast(Integer) == nation_id,
                    Event.payload["defender_nation_id"].astext.cast(Integer) == opponent_id,
                ),
                and_(
                    Event.payload["attacker_nation_id"].astext.cast(Integer) == opponent_id,
                    Event.payload["defender_nation_id"].astext.cast(Integer) == nation_id,
                ),
            ),
        )
        .order_by(Event.scheduled_for.asc())
        .all()
    )

    territory_ids = {
        ev.payload["territory_id"]
        for ev in combat_events
        if ev.payload.get("territory_id") is not None
    }
    territories = {}
    if territory_ids:
        territories = {
            t.id: t
            for t in db.query(Territory).filter(Territory.id.in_(territory_ids)).all()
        }

    def enrich(ev):
        p = dict(ev.payload)
        tid = p.get("territory_id")
        if tid is not None and tid in territories:
            t = territories[tid]
            p["territory_node_key"] = t.node_key
            p["territory_name"] = t.name
        return {"type": ev.type, "tick_at": ev.scheduled_for.isoformat(), "payload": p}

    return {
        "nation_id": nation_id,
        "nation_name": nation.name,
        "opponent_id": opponent_id,
        "opponent_name": opponent.name,
        "events": [enrich(ev) for ev in combat_events],
    }


@router.get("/{nation_id}/wars/{opponent_id}/status")
def get_war_status(
    nation_id: int,
    opponent_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.get(Nation, nation_id)
    opponent = db.get(Nation, opponent_id)
    if not nation or not opponent:
        raise HTTPException(status_code=404, detail="Nation not found")

    a_id, b_id = min(nation_id, opponent_id), max(nation_id, opponent_id)

    # ── Find most recent war declaration for this pair ──────────────────────
    declared_event = (
        db.query(Event)
        .filter(
            Event.type == "war_declared",
            or_(
                and_(
                    Event.payload["declaring_nation_id"].astext.cast(Integer) == a_id,
                    Event.payload["target_nation_id"].astext.cast(Integer) == b_id,
                ),
                and_(
                    Event.payload["declaring_nation_id"].astext.cast(Integer) == b_id,
                    Event.payload["target_nation_id"].astext.cast(Integer) == a_id,
                ),
            ),
        )
        .order_by(Event.scheduled_for.desc())
        .first()
    )
    if not declared_event:
        raise HTTPException(status_code=404, detail="No war found between these nations")

    declared_at = declared_event.scheduled_for

    # ── Find when war actually started (war_pending → war) ──────────────────
    started_event = (
        db.query(Event)
        .filter(
            Event.type == "war_started",
            Event.scheduled_for >= declared_at,
            or_(
                and_(
                    Event.payload["nation_a"].astext.cast(Integer) == a_id,
                    Event.payload["nation_b"].astext.cast(Integer) == b_id,
                ),
                and_(
                    Event.payload["nation_a"].astext.cast(Integer) == b_id,
                    Event.payload["nation_b"].astext.cast(Integer) == a_id,
                ),
            ),
        )
        .order_by(Event.scheduled_for.asc())
        .first()
    )
    started_at = started_event.scheduled_for if started_event else None

    # ── Find peace event (if war ended) ─────────────────────────────────────
    peace_cutoff = started_at or declared_at
    peace_event = (
        db.query(Event)
        .filter(
            Event.type == "trade_accepted",
            Event.payload["includes_peace"].astext == "true",
            Event.scheduled_for >= peace_cutoff,
            or_(
                and_(
                    Event.payload["from_nation_id"].astext.cast(Integer) == nation_id,
                    Event.payload["to_nation_id"].astext.cast(Integer) == opponent_id,
                ),
                and_(
                    Event.payload["from_nation_id"].astext.cast(Integer) == opponent_id,
                    Event.payload["to_nation_id"].astext.cast(Integer) == nation_id,
                ),
            ),
        )
        .order_by(Event.scheduled_for.asc())
        .first()
    )
    ended_at = peace_event.scheduled_for if peace_event else None
    is_active = ended_at is None

    # ── Collect combat events scoped to this war ─────────────────────────────
    # Lower bound: when war started (or declared if still pending)
    event_after = started_at or declared_at
    event_before = ended_at  # None = open-ended (still ongoing)

    combat_filter = [
        Event.type.in_(["combat_round", "resources_drained_by_occupation"]),
        Event.scheduled_for >= event_after,
        or_(
            and_(
                Event.payload["attacker_nation_id"].astext.cast(Integer) == nation_id,
                Event.payload["defender_nation_id"].astext.cast(Integer) == opponent_id,
            ),
            and_(
                Event.payload["attacker_nation_id"].astext.cast(Integer) == opponent_id,
                Event.payload["defender_nation_id"].astext.cast(Integer) == nation_id,
            ),
        ),
    ]
    if event_before:
        combat_filter.append(Event.scheduled_for <= event_before)

    combat_events = db.query(Event).filter(*combat_filter).all()

    conquest_filter = [
        Event.type == "territory_conquered",
        Event.scheduled_for >= event_after,
        or_(
            and_(
                Event.payload["attacker_nation_id"].astext.cast(Integer) == nation_id,
                Event.payload["defender_nation_id"].astext.cast(Integer) == opponent_id,
            ),
            and_(
                Event.payload["attacker_nation_id"].astext.cast(Integer) == opponent_id,
                Event.payload["defender_nation_id"].astext.cast(Integer) == nation_id,
            ),
        ),
    ]
    if event_before:
        conquest_filter.append(Event.scheduled_for <= event_before)

    conquest_events = db.query(Event).filter(*conquest_filter).all()

    # Pre-fetch territory richness for conquered territories so we can split
    # planets (richness > 0) from void captures.
    conquered_territory_ids = {
        int(ev.payload["territory_id"])
        for ev in conquest_events
        if ev.payload.get("territory_id") is not None
    }
    planet_territory_ids: set[int] = set()
    if conquered_territory_ids:
        planet_territory_ids = {
            t.id
            for t in db.query(Territory.id, Territory.mineral_richness, Territory.fuel_richness)
                       .filter(Territory.id.in_(conquered_territory_ids))
                       .all()
            if float(t.mineral_richness) > 0 or float(t.fuel_richness) > 0
        }

    # ── Aggregate per-nation stats ────────────────────────────────────────────
    def _make_stats():
        return {
            "fighter_losses": 0,
            "minerals_stolen": 0,
            "fuel_stolen": 0,
            "minerals_lost": 0,
            "fuel_lost": 0,
            "territories_gained": 0,
            "territories_lost": 0,
            "planets_gained": 0,
            "planets_lost": 0,
        }

    stats = {nation_id: _make_stats(), opponent_id: _make_stats()}

    for ev in combat_events:
        p = ev.payload
        att = int(p["attacker_nation_id"])
        dfn = int(p["defender_nation_id"])
        if ev.type == "combat_round":
            if att in stats:
                stats[att]["fighter_losses"] += int(p.get("attacker_losses", 0))
            if dfn in stats:
                stats[dfn]["fighter_losses"] += int(p.get("defender_losses", 0))
        elif ev.type == "resources_drained_by_occupation":
            min_d = int(p.get("minerals_drained", 0))
            fuel_d = int(p.get("fuel_drained", 0))
            if att in stats:
                stats[att]["minerals_stolen"] += min_d
                stats[att]["fuel_stolen"] += fuel_d
            if dfn in stats:
                stats[dfn]["minerals_lost"] += min_d
                stats[dfn]["fuel_lost"] += fuel_d

    for ev in conquest_events:
        p = ev.payload
        att = int(p["attacker_nation_id"])
        dfn = int(p["defender_nation_id"])
        tid = int(p.get("territory_id", 0))
        is_planet = tid in planet_territory_ids
        if att in stats:
            stats[att]["territories_gained"] += 1
            if is_planet:
                stats[att]["planets_gained"] += 1
        if dfn in stats:
            stats[dfn]["territories_lost"] += 1
            if is_planet:
                stats[dfn]["planets_lost"] += 1

    # ── Compute war cost (fighter losses × manufacture cost) ─────────────────
    sf = UNIT_STATS["starfighter"]
    for nid, s in stats.items():
        losses = s["fighter_losses"]
        s["war_cost_minerals"] = losses * sf["manufacture_cost_minerals"]
        s["war_cost_fuel"] = losses * sf["manufacture_cost_fuel"]
        s["war_cost_currency"] = losses * sf["manufacture_cost_currency"]

    # ── Duration ─────────────────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    if started_at:
        end = ended_at or now
        elapsed_seconds = int((end - started_at).total_seconds())
    else:
        elapsed_seconds = None

    declaring_id = int(declared_event.payload["declaring_nation_id"])

    return {
        "nation_id": nation_id,
        "nation_name": nation.name,
        "opponent_id": opponent_id,
        "opponent_name": opponent.name,
        "declared_at": declared_at.isoformat(),
        "declared_by_nation_id": declaring_id,
        "started_at": started_at.isoformat() if started_at else None,
        "ended_at": ended_at.isoformat() if ended_at else None,
        "is_active": is_active,
        "elapsed_seconds": elapsed_seconds,
        "nation_stats": stats[nation_id],
        "opponent_stats": stats[opponent_id],
    }
