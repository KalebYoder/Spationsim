import random
from datetime import datetime, timezone, timedelta
from math import ceil
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.colony_ship import ColonyShip
from ..models.probe_data import ProbeData, ProbeDataAccess
from ..models.probe_visibility import ProbeVisibility
from ..models.event import Event
from ..models.fleet import Fleet
from ..models.infrastructure import Infrastructure
from ..models.nation import Nation
from ..models.territory import Territory
from ..models.territory_population import TerritoryPopulation
from ..models.territory_dissent import TerritoryDissent
from ..models.player import Player
from ..services.pathfinding import compute_reachable_ids
from ..schemas.nation import (
    ClaimTerritoryResponse,
    ColonyShipCargoRequest,
    ColonyShipResponse,
    ColonyShipStatsResponse,
    FleetResponse,
    ManufactureColonyShipRequest,
    SendColonyShipRequest,
    SendFleetRequest,
    StarfighterManufactureRequest,
    UnitStatsResponse,
)
from ..routers.auth import get_current_player
from ..routers.diplomacy import is_at_war, get_diplomacy_status
from ..routers.tutorial import _apply_tutorial_action
from ..constants import COLONY_SHIP_STATS, UNIT_STATS, FACILITY_POPULATION_COST

router = APIRouter(prefix="/api/military", tags=["military"])

TICK_HOURS = 2


def _require_aggression_allowed(player: Player) -> None:
    if player.vacation_mode:
        raise HTTPException(status_code=409, detail="Cannot dispatch fleets while in vacation mode")
    now = datetime.now(timezone.utc)
    if player.aggression_lockout_until and player.aggression_lockout_until > now:
        until = player.aggression_lockout_until.strftime("%Y-%m-%d %H:%M UTC")
        raise HTTPException(
            status_code=409,
            detail=f"Post-vacation aggression lockout active until {until}",
        )


def _hex_distance(key_a: str, key_b: str) -> int:
    q1, r1 = map(int, key_a.split(","))
    q2, r2 = map(int, key_b.split(","))
    dq, dr = q2 - q1, r2 - r1
    return max(abs(dq), abs(dr), abs(dq + dr))


def _fleet_response(fleet: Fleet, db: Session) -> FleetResponse:
    origin = db.get(Territory, fleet.origin_territory) if fleet.origin_territory else None
    dest = db.get(Territory, fleet.destination_territory) if fleet.destination_territory else None

    dest_nation_id = dest.nation_id if dest else None
    dest_has_defenders = None
    if dest and dest.nation_id and dest.nation_id != fleet.nation_id:
        defender = (
            db.query(Fleet)
            .filter(
                Fleet.nation_id == dest.nation_id,
                Fleet.origin_territory == dest.id,
                Fleet.status == "stationed",
            )
            .first()
        )
        dest_has_defenders = defender is not None and defender.unit_count > 0

    return FleetResponse(
        id=fleet.id,
        unit_count=fleet.unit_count,
        status=fleet.status,
        standing_order=fleet.standing_order,
        origin_territory_id=fleet.origin_territory,
        origin_node_key=origin.node_key if origin else None,
        origin_name=origin.name if origin else None,
        origin_is_colonized=origin.is_colonized if origin else None,
        origin_nation_id=origin.nation_id if origin else None,
        destination_territory_id=fleet.destination_territory,
        destination_node_key=dest.node_key if dest else None,
        destination_name=dest.name if dest else None,
        destination_nation_id=dest_nation_id,
        destination_has_defenders=dest_has_defenders,
        arrives_at=fleet.arrives_at.isoformat() if fleet.arrives_at else None,
        confirmation_expires_at=fleet.confirmation_expires_at.isoformat() if fleet.confirmation_expires_at else None,
    )


def _nation_pop_stats(nation_id: int, db: Session) -> tuple[int, int]:
    territory_ids = [
        t_id for (t_id,) in
        db.query(Territory.id).filter(Territory.nation_id == nation_id).all()
    ]
    total = int(
        db.query(sqlfunc.sum(TerritoryPopulation.current))
        .filter(TerritoryPopulation.territory_id.in_(territory_ids))
        .scalar() or 0
    )
    facilities = (
        db.query(Infrastructure)
        .join(Territory, Infrastructure.territory_id == Territory.id)
        .filter(
            Territory.nation_id == nation_id,
            Infrastructure.status.in_(["active", "under_construction"]),
        )
        .all()
    )
    assigned = sum(FACILITY_POPULATION_COST.get(f.type, 0) for f in facilities)
    return total, assigned


@router.get("/units", response_model=list[UnitStatsResponse])
def get_units(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    return [
        UnitStatsResponse(
            type=unit_type,
            firepower=stats["firepower"],
            shields=stats["shields"],
            structural_integrity=stats["structural_integrity"],
            nodes_per_tick=stats["nodes_per_tick"],
            manufacture_cost_minerals=stats["manufacture_cost_minerals"],
            manufacture_cost_fuel=stats["manufacture_cost_fuel"],
            manufacture_cost_currency=stats["manufacture_cost_currency"],
        )
        for unit_type, stats in UNIT_STATS.items()
    ]


@router.get("/fleets", response_model=list[FleetResponse])
def list_fleets(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    fleets = db.query(Fleet).filter(Fleet.nation_id == nation.id).all()
    return [_fleet_response(f, db) for f in fleets]


@router.post("/manufacture/starfighter", response_model=FleetResponse, status_code=201)
def manufacture_starfighter(
    body: StarfighterManufactureRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    territory = db.get(Territory, body.territory_id)
    if not territory or territory.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="You do not control this territory")

    has_factory = (
        db.query(Infrastructure)
        .filter(
            Infrastructure.territory_id == territory.id,
            Infrastructure.type == "shipyard",
        )
        .first()
    )
    if not has_factory:
        raise HTTPException(status_code=409, detail="This territory has no shipyard")

    stats = UNIT_STATS["starfighter"]
    mineral_cost = stats["manufacture_cost_minerals"] * body.quantity
    fuel_cost = stats["manufacture_cost_fuel"] * body.quantity
    currency_cost = stats["manufacture_cost_currency"] * body.quantity

    if nation.minerals < mineral_cost or nation.fuel < fuel_cost or nation.currency < currency_cost:
        raise HTTPException(status_code=409, detail="Insufficient resources")

    pop_row = db.query(TerritoryPopulation).filter(
        TerritoryPopulation.territory_id == territory.id
    ).first()
    territory_pop = pop_row.current if pop_row else 0

    territory_facilities = db.query(Infrastructure).filter(
        Infrastructure.territory_id == territory.id,
        Infrastructure.status.in_(["active", "under_construction"]),
    ).all()
    territory_assigned = sum(FACILITY_POPULATION_COST.get(f.type, 0) for f in territory_facilities)
    territory_unassigned = territory_pop - territory_assigned

    if territory_unassigned < body.quantity:
        raise HTTPException(
            status_code=409,
            detail=f"Insufficient unassigned population at this territory (need {body.quantity}, have {max(0, territory_unassigned)})",
        )

    # Deduct from the shipyard territory's population only. Fighter deaths do
    # not restore population — pop spent at manufacture is permanently gone
    # when the unit is destroyed in combat.
    pop_row.current -= body.quantity

    nation.minerals -= mineral_cost
    nation.fuel -= fuel_cost
    nation.currency -= currency_cost

    # Add to existing stationed fleet at this territory or create one
    stationed = (
        db.query(Fleet)
        .filter(
            Fleet.nation_id == nation.id,
            Fleet.origin_territory == territory.id,
            Fleet.status == "stationed",
        )
        .first()
    )
    if stationed:
        stationed.unit_count += body.quantity
    else:
        stationed = Fleet(
            nation_id=nation.id,
            origin_territory=territory.id,
            unit_count=body.quantity,
            status="stationed",
            standing_order="hold",
        )
        db.add(stationed)

    _apply_tutorial_action(nation.id, "manufacture_fighter", db)
    db.commit()
    db.refresh(stationed)
    return _fleet_response(stationed, db)


@router.post("/fleets/send", response_model=FleetResponse, status_code=201)
def send_fleet(
    body: SendFleetRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    _require_aggression_allowed(player)
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    origin = db.get(Territory, body.from_territory_id)
    if not origin or origin.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="You do not control the origin territory")

    dest = db.get(Territory, body.to_territory_id)
    if not dest:
        raise HTTPException(status_code=404, detail="Destination territory not found")
    if body.from_territory_id == body.to_territory_id:
        raise HTTPException(status_code=409, detail="Origin and destination must differ")

    # Pathfinding reachability check — destination must be connected via passable tiles
    all_territories = db.query(Territory).all()
    territory_dicts = [
        {"id": t.id, "node_key": t.node_key, "territory_type": t.territory_type, "nation_id": t.nation_id}
        for t in all_territories
    ]
    reachable = compute_reachable_ids(origin.node_key, nation.id, territory_dicts)
    if dest.id not in reachable:
        raise HTTPException(status_code=409, detail="Destination is not reachable from origin")

    # Gate dispatch by diplomacy status and destination territory type
    if dest.nation_id and dest.nation_id != nation.id:
        diplo = get_diplomacy_status(db, nation.id, dest.nation_id)
        is_planet = dest.territory_type != "void"
        if diplo in ("neutral", "friend_pending") and is_planet:
            raise HTTPException(
                status_code=409,
                detail="Cannot dispatch fleets to a neutral nation's territory. War declaration required.",
            )
        # war, war_pending, and friendly all allow dispatch; neutral/friend_pending allows void only

    stationed = (
        db.query(Fleet)
        .filter(
            Fleet.nation_id == nation.id,
            Fleet.origin_territory == origin.id,
            Fleet.status == "stationed",
        )
        .first()
    )
    if not stationed or stationed.unit_count < body.quantity:
        available = stationed.unit_count if stationed else 0
        raise HTTPException(
            status_code=409,
            detail=f"Insufficient stationed fighters (have {available}, need {body.quantity})",
        )

    now = datetime.now(timezone.utc)
    distance = _hex_distance(origin.node_key, dest.node_key)
    transit_ticks = ceil(distance / UNIT_STATS["starfighter"]["nodes_per_tick"])
    arrives_at = now + timedelta(hours=transit_ticks * TICK_HOURS)

    stationed.unit_count -= body.quantity
    if stationed.unit_count == 0:
        db.delete(stationed)

    transit = Fleet(
        nation_id=nation.id,
        origin_territory=origin.id,
        destination_territory=dest.id,
        unit_count=body.quantity,
        status="in_transit",
        departs_at=now,
        arrives_at=arrives_at,
        standing_order="hold",
    )
    db.add(transit)
    _apply_tutorial_action(nation.id, "dispatch_fleet", db)
    db.commit()
    db.refresh(transit)
    return _fleet_response(transit, db)


@router.post("/fleets/{fleet_id}/confirm-attack", response_model=FleetResponse)
def confirm_attack(
    fleet_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    fleet = db.get(Fleet, fleet_id)
    if not fleet or fleet.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="Fleet not found or does not belong to you")

    if fleet.status not in ("pending_confirmation", "holding"):
        raise HTTPException(
            status_code=409,
            detail="Fleet must be pending confirmation or holding to confirm attack",
        )

    dest = db.get(Territory, fleet.destination_territory)
    if not dest or not dest.nation_id or dest.nation_id == nation.id:
        raise HTTPException(status_code=409, detail="No valid enemy territory at fleet destination")

    if not is_at_war(db, nation.id, dest.nation_id):
        raise HTTPException(status_code=409, detail="Not at war with the territory's owner")

    fleet.status = "engaged"
    fleet.confirmation_expires_at = None

    db.add(Event(
        type="attack_confirmed",
        payload={
            "fleet_id": fleet.id,
            "attacker_nation_id": nation.id,
            "defender_nation_id": dest.nation_id,
            "territory_id": dest.id,
            "node_key": dest.node_key,
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
        },
        scheduled_for=datetime.now(timezone.utc),
        processed_at=datetime.now(timezone.utc),
        status="processed",
    ))

    db.commit()
    db.refresh(fleet)
    return _fleet_response(fleet, db)


@router.post("/fleets/{fleet_id}/recall", response_model=FleetResponse)
def recall_fleet(
    fleet_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    fleet = db.get(Fleet, fleet_id)
    if not fleet or fleet.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="Fleet not found or does not belong to you")

    if fleet.status not in ("pending_confirmation", "holding"):
        raise HTTPException(
            status_code=409,
            detail="Fleet must be pending confirmation or holding to recall",
        )

    now = datetime.now(timezone.utc)
    home = db.get(Territory, fleet.origin_territory)
    current = db.get(Territory, fleet.destination_territory)
    if not home or not current:
        raise HTTPException(status_code=409, detail="Fleet territory data is inconsistent")

    distance = _hex_distance(home.node_key, current.node_key)
    transit_ticks = ceil(distance / UNIT_STATS["starfighter"]["nodes_per_tick"])
    arrives_at = now + timedelta(hours=transit_ticks * TICK_HOURS)

    enemy_territory_id = fleet.destination_territory
    home_territory_id = fleet.origin_territory

    fleet.status = "in_transit"
    fleet.origin_territory = current.id
    fleet.destination_territory = home.id
    fleet.departs_at = now
    fleet.arrives_at = arrives_at
    fleet.confirmation_expires_at = None

    db.add(Event(
        type="fleet_recalled",
        payload={
            "fleet_id": fleet.id,
            "nation_id": nation.id,
            "from_territory_id": enemy_territory_id,
            "to_territory_id": home_territory_id,
            "recalled_at": now.isoformat(),
        },
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))

    db.commit()
    db.refresh(fleet)
    return _fleet_response(fleet, db)


@router.post("/fleets/{fleet_id}/conquer", response_model=ClaimTerritoryResponse)
def conquer_territory(
    fleet_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    fleet = db.get(Fleet, fleet_id)
    if not fleet or fleet.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="Fleet not found or does not belong to you")

    if fleet.status != "engaged":
        raise HTTPException(status_code=409, detail="Fleet must be engaged to conquer territory")

    dest = db.get(Territory, fleet.destination_territory)
    if not dest:
        raise HTTPException(status_code=404, detail="Fleet has no destination territory")

    if dest.territory_type == "void":
        raise HTTPException(status_code=409, detail="Void territories cannot be conquered")

    if not dest.nation_id or dest.nation_id == nation.id:
        raise HTTPException(status_code=409, detail="Territory must be owned by an enemy nation")

    if not is_at_war(db, nation.id, dest.nation_id):
        raise HTTPException(status_code=409, detail="Not at war with the territory's owner")

    defender = (
        db.query(Fleet)
        .filter(
            Fleet.nation_id == dest.nation_id,
            Fleet.origin_territory == dest.id,
            Fleet.status == "stationed",
        )
        .first()
    )
    if defender and defender.unit_count > 0:
        raise HTTPException(
            status_code=409,
            detail="Territory has defenders — eliminate them before conquering",
        )

    now = datetime.now(timezone.utc)
    former_owner_id = dest.nation_id

    dest.nation_id = nation.id
    dest.is_colonized = True
    dest.colonized_at = now

    # Remove stale probe data — conquered territory is now visible on the map
    for pd in db.query(ProbeData).filter(ProbeData.territory_id == dest.id).all():
        db.query(ProbeDataAccess).filter(ProbeDataAccess.probe_data_id == pd.id).delete()
    db.query(ProbeData).filter(ProbeData.territory_id == dest.id).delete()
    db.query(ProbeVisibility).filter(ProbeVisibility.territory_id == dest.id).delete()

    # Conquered population starts hostile — set dissent to 60 instantly
    dissent_row = db.query(TerritoryDissent).filter(TerritoryDissent.territory_id == dest.id).first()
    if dissent_row:
        dissent_row.dissent = 60
    else:
        db.add(TerritoryDissent(territory_id=dest.id, dissent=60))

    fleet.status = "stationed"
    fleet.origin_territory = dest.id
    fleet.destination_territory = None
    fleet.arrives_at = None
    fleet.departs_at = None
    fleet.confirmation_expires_at = None

    db.add(Event(
        type="territory_conquered",
        payload={
            "fleet_id": fleet.id,
            "attacker_nation_id": nation.id,
            "defender_nation_id": former_owner_id,
            "territory_id": dest.id,
            "node_key": dest.node_key,
            "conquered_at": now.isoformat(),
        },
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))

    db.add(Event(
        type="territory_lost_to_conquest",
        payload={
            "nation_id": former_owner_id,
            "conquered_by_nation_id": nation.id,
            "territory_id": dest.id,
            "node_key": dest.node_key,
            "conquered_at": now.isoformat(),
        },
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))

    db.flush()
    colonized_count = db.query(Territory).filter(
        Territory.nation_id == nation.id,
        Territory.is_colonized == True,
    ).count()
    if colonized_count >= 2:
        _apply_tutorial_action(nation.id, "colonize_territory", db)
    if colonized_count > (nation.max_colonized_territory_count or 0):
        nation.max_colonized_territory_count = colonized_count

    db.commit()
    db.refresh(dest)
    return ClaimTerritoryResponse(
        territory_id=dest.id,
        node_key=dest.node_key,
        name=dest.name,
        nation_id=dest.nation_id,
        colonized_at=dest.colonized_at.isoformat(),
    )


@router.post("/fleets/{fleet_id}/rout", response_model=FleetResponse)
def rout_fleet(
    fleet_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    fleet = db.get(Fleet, fleet_id)
    if not fleet or fleet.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="Fleet not found or does not belong to you")

    if fleet.status != "post_battle_choice":
        raise HTTPException(status_code=409, detail="Fleet must be in post_battle_choice state to rout")

    dest = db.get(Territory, fleet.destination_territory)
    if not dest:
        raise HTTPException(status_code=404, detail="Fleet has no destination territory")

    now = datetime.now(timezone.utc)
    from sqlalchemy import cast, Integer as SAInt

    last_combat = (
        db.query(Event)
        .filter(
            Event.type == "combat_round",
            cast(Event.payload["fleet_id"].astext, SAInt) == fleet.id,
        )
        .order_by(Event.id.desc())
        .first()
    )

    bonus_damage = 0
    if last_combat and last_combat.payload:
        defender_losses = last_combat.payload.get("defender_losses", 0)
        bonus_damage = max(0, int(defender_losses * 0.25))

    defender_fleet = (
        db.query(Fleet)
        .filter(
            Fleet.nation_id == dest.nation_id,
            Fleet.origin_territory == dest.id,
            Fleet.status == "stationed",
        )
        .first()
    ) if dest.nation_id else None

    actual_damage = 0
    if defender_fleet and defender_fleet.unit_count > 0 and bonus_damage > 0:
        actual_damage = min(bonus_damage, defender_fleet.unit_count)
        defender_fleet.unit_count -= actual_damage
        if defender_fleet.unit_count == 0:
            db.delete(defender_fleet)

    fleet.status = "engaged"
    fleet.confirmation_expires_at = None

    db.add(Event(
        type="rout_applied",
        payload={
            "fleet_id": fleet.id,
            "attacker_nation_id": nation.id,
            "defender_nation_id": dest.nation_id,
            "territory_id": dest.id,
            "bonus_damage": actual_damage,
            "applied_at": now.isoformat(),
        },
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))

    db.commit()
    db.refresh(fleet)
    return _fleet_response(fleet, db)


@router.post("/fleets/{fleet_id}/raid", response_model=FleetResponse)
def raid_fleet(
    fleet_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    fleet = db.get(Fleet, fleet_id)
    if not fleet or fleet.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="Fleet not found or does not belong to you")

    if fleet.status != "post_battle_choice":
        raise HTTPException(status_code=409, detail="Fleet must be in post_battle_choice state to raid")

    dest = db.get(Territory, fleet.destination_territory)
    if not dest or not dest.nation_id or dest.nation_id == nation.id:
        raise HTTPException(status_code=409, detail="No valid enemy territory at fleet destination")

    defender_nation = db.get(Nation, dest.nation_id)
    if not defender_nation:
        raise HTTPException(status_code=404, detail="Defender nation not found")

    now = datetime.now(timezone.utc)
    firepower = fleet.unit_count * UNIT_STATS["starfighter"]["firepower"]

    minerals_stolen = min(
        random.uniform(0.5 * firepower, 1.5 * firepower),
        float(defender_nation.minerals),
    )
    fuel_stolen = min(
        random.uniform(0.5 * firepower, 1.5 * firepower),
        float(defender_nation.fuel),
    )
    currency_stolen = min(
        random.uniform(0.5 * firepower, 1.5 * firepower),
        float(defender_nation.currency),
    )

    defender_nation.minerals -= minerals_stolen
    defender_nation.fuel -= fuel_stolen
    defender_nation.currency -= currency_stolen
    nation.minerals += minerals_stolen
    nation.fuel += fuel_stolen
    nation.currency += currency_stolen

    fleet.status = "engaged"
    fleet.confirmation_expires_at = None

    db.add(Event(
        type="raid_applied",
        payload={
            "fleet_id": fleet.id,
            "attacker_nation_id": nation.id,
            "defender_nation_id": dest.nation_id,
            "territory_id": dest.id,
            "minerals_stolen": round(minerals_stolen, 2),
            "fuel_stolen": round(fuel_stolen, 2),
            "currency_stolen": round(currency_stolen, 2),
            "applied_at": now.isoformat(),
        },
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))

    db.commit()
    db.refresh(fleet)
    return _fleet_response(fleet, db)


@router.post("/fleets/{fleet_id}/raze", response_model=FleetResponse)
def raze_fleet(
    fleet_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    raise HTTPException(status_code=409, detail="Raze is not yet implemented")


@router.post("/fleets/{fleet_id}/claim", response_model=ClaimTerritoryResponse)
def claim_territory(
    fleet_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    fleet = db.get(Fleet, fleet_id)
    if not fleet or fleet.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="Fleet not found or does not belong to you")

    if fleet.status != "stationed":
        raise HTTPException(status_code=409, detail="Fleet must be stationed to claim territory")

    territory = db.get(Territory, fleet.origin_territory)
    if not territory:
        raise HTTPException(status_code=404, detail="Fleet has no current territory")

    if territory.territory_type != "normal":
        raise HTTPException(status_code=409, detail="Only normal territories can be claimed")

    if territory.is_colonized:
        raise HTTPException(status_code=409, detail="Territory is already claimed")

    now = datetime.now(timezone.utc)
    former_owner_id = territory.nation_id
    territory.is_colonized = True
    territory.nation_id = nation.id
    territory.colonized_at = now

    # Create dissent row at 0 for this newly-colonized territory
    if not db.query(TerritoryDissent).filter(TerritoryDissent.territory_id == territory.id).first():
        db.add(TerritoryDissent(territory_id=territory.id, dissent=0))

    # Remove stale probe data — territory is now on the map, visible to all
    for pd in db.query(ProbeData).filter(ProbeData.territory_id == territory.id).all():
        db.query(ProbeDataAccess).filter(ProbeDataAccess.probe_data_id == pd.id).delete()
    db.query(ProbeData).filter(ProbeData.territory_id == territory.id).delete()

    db.add(Event(
        type="territory_claimed",
        payload={
            "nation_id": nation.id,
            "territory_id": territory.id,
            "node_key": territory.node_key,
            "former_nation_id": former_owner_id,
        },
        scheduled_for=now,
        processed_at=now,
        status="processed",
    ))

    if former_owner_id is not None:
        db.add(Event(
            type="territory_lost",
            payload={
                "nation_id": former_owner_id,
                "claimed_by_nation_id": nation.id,
                "territory_id": territory.id,
                "node_key": territory.node_key,
            },
            scheduled_for=now,
            processed_at=now,
            status="processed",
        ))

    db.flush()
    colonized_count = db.query(Territory).filter(
        Territory.nation_id == nation.id,
        Territory.is_colonized == True,
    ).count()
    if colonized_count >= 2:
        _apply_tutorial_action(nation.id, "colonize_territory", db)
    if colonized_count > (nation.max_colonized_territory_count or 0):
        nation.max_colonized_territory_count = colonized_count

    db.commit()
    db.refresh(territory)
    return ClaimTerritoryResponse(
        territory_id=territory.id,
        node_key=territory.node_key,
        name=territory.name,
        nation_id=territory.nation_id,
        colonized_at=territory.colonized_at.isoformat(),
    )


# ── Colony ship helpers ──────────────────────────────────────────────────────

def _colony_ship_response(ship: ColonyShip, db: Session) -> ColonyShipResponse:
    origin = db.get(Territory, ship.origin_territory) if ship.origin_territory else None
    dest = db.get(Territory, ship.destination_territory) if ship.destination_territory else None
    origin_pop = None
    if origin:
        pop_row = db.query(TerritoryPopulation).filter(
            TerritoryPopulation.territory_id == origin.id
        ).first()
        origin_pop = pop_row.current if pop_row else 0
    return ColonyShipResponse(
        id=ship.id,
        status=ship.status,
        cargo_population=ship.cargo_population,
        origin_territory_id=ship.origin_territory,
        origin_node_key=origin.node_key if origin else None,
        origin_name=origin.name if origin else None,
        origin_is_colonized=origin.is_colonized if origin else None,
        origin_nation_id=origin.nation_id if origin else None,
        origin_current_population=origin_pop,
        destination_territory_id=ship.destination_territory,
        destination_node_key=dest.node_key if dest else None,
        destination_name=dest.name if dest else None,
        arrives_at=ship.arrives_at.isoformat() if ship.arrives_at else None,
    )


# ── Colony ship endpoints ────────────────────────────────────────────────────

@router.get("/colony-ships/stats", response_model=ColonyShipStatsResponse)
def get_colony_ship_stats(
    player: Player = Depends(get_current_player),
):
    return ColonyShipStatsResponse(
        nodes_per_tick=COLONY_SHIP_STATS["nodes_per_tick"],
        cargo_capacity=COLONY_SHIP_STATS["cargo_capacity"],
        manufacture_cost_minerals=COLONY_SHIP_STATS["manufacture_cost_minerals"],
        manufacture_cost_fuel=COLONY_SHIP_STATS["manufacture_cost_fuel"],
    )


@router.get("/colony-ships", response_model=list[ColonyShipResponse])
def list_colony_ships(
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")
    ships = db.query(ColonyShip).filter(ColonyShip.nation_id == nation.id).all()
    return [_colony_ship_response(s, db) for s in ships]


@router.post("/manufacture/colony-ship", response_model=ColonyShipResponse, status_code=201)
def manufacture_colony_ship(
    body: ManufactureColonyShipRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    territory = db.get(Territory, body.territory_id)
    if not territory or territory.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="You do not control this territory")

    has_shipyard = (
        db.query(Infrastructure)
        .filter(
            Infrastructure.territory_id == territory.id,
            Infrastructure.type == "shipyard",
        )
        .first()
    )
    if not has_shipyard:
        raise HTTPException(status_code=409, detail="This territory has no shipyard")

    mineral_cost = COLONY_SHIP_STATS["manufacture_cost_minerals"]
    fuel_cost = COLONY_SHIP_STATS["manufacture_cost_fuel"]
    if nation.minerals < mineral_cost or nation.fuel < fuel_cost:
        raise HTTPException(status_code=409, detail="Insufficient resources")

    nation.minerals -= mineral_cost
    nation.fuel -= fuel_cost

    ship = ColonyShip(
        nation_id=nation.id,
        origin_territory=territory.id,
        cargo_population=0,
        status="stationed",
    )
    db.add(ship)
    _apply_tutorial_action(nation.id, "manufacture_colony_ship", db)
    db.commit()
    db.refresh(ship)
    return _colony_ship_response(ship, db)


@router.post("/colony-ships/{ship_id}/send", response_model=ColonyShipResponse)
def send_colony_ship(
    ship_id: int,
    body: SendColonyShipRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    _require_aggression_allowed(player)
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    ship = db.get(ColonyShip, ship_id)
    if not ship or ship.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="Colony ship not found or does not belong to you")

    if ship.status != "stationed":
        raise HTTPException(status_code=409, detail="Colony ship is already in transit")

    origin = db.get(Territory, ship.origin_territory)
    if not origin or origin.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="Origin territory is not yours")

    dest = db.get(Territory, body.to_territory_id)
    if not dest:
        raise HTTPException(status_code=404, detail="Destination territory not found")
    if dest.id == origin.id:
        raise HTTPException(status_code=409, detail="Origin and destination must differ")
    if not dest.is_colonized or dest.nation_id != nation.id:
        raise HTTPException(status_code=409, detail="Colony ships can only travel to your own colonized territories")

    all_territories = db.query(Territory).all()
    territory_dicts = [
        {"id": t.id, "node_key": t.node_key, "territory_type": t.territory_type, "nation_id": t.nation_id}
        for t in all_territories
    ]
    reachable = compute_reachable_ids(origin.node_key, nation.id, territory_dicts)
    if dest.id not in reachable:
        raise HTTPException(status_code=409, detail="Destination is not reachable from origin")

    now = datetime.now(timezone.utc)
    distance = _hex_distance(origin.node_key, dest.node_key)
    transit_ticks = ceil(distance / COLONY_SHIP_STATS["nodes_per_tick"])
    arrives_at = now + timedelta(hours=transit_ticks * TICK_HOURS)

    ship.status = "in_transit"
    ship.destination_territory = dest.id
    ship.departs_at = now
    ship.arrives_at = arrives_at

    db.commit()
    db.refresh(ship)
    return _colony_ship_response(ship, db)


@router.post("/colony-ships/{ship_id}/load", response_model=ColonyShipResponse)
def load_colony_ship(
    ship_id: int,
    body: ColonyShipCargoRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    _require_aggression_allowed(player)
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    ship = db.get(ColonyShip, ship_id)
    if not ship or ship.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="Colony ship not found or does not belong to you")

    if ship.status != "stationed":
        raise HTTPException(status_code=409, detail="Colony ship must be stationed to load population")

    territory = db.get(Territory, ship.origin_territory)
    if not territory or territory.nation_id != nation.id or not territory.is_colonized:
        raise HTTPException(status_code=409, detail="Colony ship is not at a colonized territory you own")
    if territory.territory_type != "normal":
        raise HTTPException(status_code=409, detail="Cannot load population from void space")

    capacity = COLONY_SHIP_STATS["cargo_capacity"]
    space_remaining = capacity - ship.cargo_population
    if space_remaining <= 0:
        raise HTTPException(status_code=409, detail="Colony ship cargo is full")

    pop_row = db.query(TerritoryPopulation).filter(
        TerritoryPopulation.territory_id == territory.id
    ).first()
    total_pop = pop_row.current if pop_row else 0
    assigned_pop = db.query(sqlfunc.coalesce(sqlfunc.sum(Infrastructure.population_assigned), 0)).filter(
        Infrastructure.territory_id == territory.id
    ).scalar()
    available_pop = total_pop - assigned_pop
    if available_pop <= 0:
        raise HTTPException(status_code=409, detail="Territory has no unassigned population to load")

    quantity = min(body.quantity, space_remaining, available_pop)
    if quantity <= 0:
        raise HTTPException(status_code=409, detail="Cannot load 0 population")

    pop_row.current -= quantity
    ship.cargo_population += quantity

    db.commit()
    db.refresh(ship)
    return _colony_ship_response(ship, db)


@router.post("/colony-ships/{ship_id}/unload", response_model=ColonyShipResponse)
def unload_colony_ship(
    ship_id: int,
    body: ColonyShipCargoRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    ship = db.get(ColonyShip, ship_id)
    if not ship or ship.nation_id != nation.id:
        raise HTTPException(status_code=403, detail="Colony ship not found or does not belong to you")

    if ship.status != "stationed":
        raise HTTPException(status_code=409, detail="Colony ship must be stationed to unload population")

    territory = db.get(Territory, ship.origin_territory)
    if not territory or territory.nation_id != nation.id or not territory.is_colonized:
        raise HTTPException(status_code=409, detail="Colony ship is not at a colonized territory you own")
    if territory.territory_type != "normal":
        raise HTTPException(status_code=409, detail="Cannot unload population into void space")

    if ship.cargo_population <= 0:
        raise HTTPException(status_code=409, detail="Colony ship has no population to unload")

    quantity = min(body.quantity, ship.cargo_population)

    pop_row = db.query(TerritoryPopulation).filter(
        TerritoryPopulation.territory_id == territory.id
    ).first()
    if pop_row:
        pop_row.current += quantity
    else:
        db.add(TerritoryPopulation(
            territory_id=territory.id,
            current=quantity,
            last_updated=datetime.now(timezone.utc),
        ))

    ship.cargo_population -= quantity

    db.commit()
    db.refresh(ship)
    return _colony_ship_response(ship, db)
