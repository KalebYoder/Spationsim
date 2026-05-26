from datetime import datetime, timezone, timedelta
from math import ceil
from sqlalchemy import text, func as sqlfunc
from ..celery_app import celery_app
from ..db.database import SessionLocal
from ..models.colony_ship import ColonyShip
from ..models.fleet import Fleet
from ..models.nation import Nation
from ..models.infrastructure import Infrastructure
from ..models.territory import Territory
from ..models.resource_log import ResourceLog
from ..models.event import Event
from ..models.territory_population import TerritoryPopulation
from ..models.diplomacy import Diplomacy
from ..models.probe import Probe
from ..models.probe_data import ProbeData
from ..constants import POPULATION_GROWTH_RATE, POPULATION_CAP_MULTIPLIER, PROBE_VISION_RADIUS, UNIT_STATS
from ..map_gen import generate_territory

TICK_HOURS = 2
_CONFIRMATION_WINDOW = timedelta(hours=TICK_HOURS * 2)  # 2 ticks = 4 hours


def _nations_at_war(db, nation_a_id: int, nation_b_id: int) -> bool:
    a, b = min(nation_a_id, nation_b_id), max(nation_a_id, nation_b_id)
    return db.query(Diplomacy).filter(
        Diplomacy.nation_a == a,
        Diplomacy.nation_b == b,
        Diplomacy.status == "war",
    ).first() is not None


def _send_fleet_home(db, fleet: Fleet, now: datetime) -> None:
    """Reverse a fleet's route so it travels back to its launch origin."""
    home = db.get(Territory, fleet.origin_territory)
    current = db.get(Territory, fleet.destination_territory)
    if not home or not current:
        return
    hq, hr = _parse_key(home.node_key)
    cq, cr = _parse_key(current.node_key)
    distance = _hex_dist(cq, cr, hq, hr)
    transit_ticks = ceil(distance / UNIT_STATS["starfighter"]["nodes_per_tick"])
    fleet.status = "in_transit"
    fleet.origin_territory = current.id
    fleet.destination_territory = home.id
    fleet.departs_at = now
    fleet.arrives_at = now + timedelta(hours=transit_ticks * TICK_HOURS)
    fleet.confirmation_expires_at = None


def _parse_key(key: str):
    q, r = key.split(",")
    return int(q), int(r)


def _hex_dist(q1, r1, q2, r2):
    dq, dr = q2 - q1, r2 - r1
    return max(abs(dq), abs(dr), abs(dq + dr))


def _next_step(cq, cr, dq, dr):
    neighbors = [(cq+1, cr), (cq-1, cr), (cq, cr+1), (cq, cr-1), (cq+1, cr-1), (cq-1, cr+1)]
    return min(neighbors, key=lambda nb: _hex_dist(nb[0], nb[1], dq, dr))


@celery_app.task(name="app.tasks.tick.run_tick")
def run_tick():
    db = SessionLocal()
    tick_at = datetime.now(timezone.utc)
    try:
        nations = db.query(Nation).all()

        for nation in nations:
            territory_ids = [
                t_id for (t_id,) in
                db.query(Territory.id).filter(Territory.nation_id == nation.id).all()
            ]

            facilities = (
                db.query(Infrastructure.type, Territory.mineral_richness, Territory.fuel_richness)
                .join(Territory, Infrastructure.territory_id == Territory.id)
                .filter(Territory.nation_id == nation.id)
                .all()
            )

            minerals_delta = 0
            fuel_delta = 0
            for ftype, mineral_richness, fuel_richness in facilities:
                if ftype == "mine":
                    minerals_delta += round(2 * float(mineral_richness))
                elif ftype == "refinery":
                    fuel_delta += round(2 * float(fuel_richness))

            # 500 currency per colonized territory that has at least one mine or refinery
            income_territory_count = (
                db.query(Territory.id)
                .join(Infrastructure, Territory.id == Infrastructure.territory_id)
                .filter(
                    Territory.nation_id == nation.id,
                    Territory.is_colonized == True,
                    Infrastructure.type.in_(["mine", "refinery"]),
                )
                .distinct()
                .count()
            )
            currency_delta = 500 * income_territory_count

            # Upkeep: 2 currency per fighter per tick
            fighter_upkeep = (
                db.query(sqlfunc.coalesce(sqlfunc.sum(Fleet.unit_count), 0))
                .filter(Fleet.nation_id == nation.id)
                .scalar()
            )
            currency_delta -= fighter_upkeep * 2

            # Grow population in each territory (5% per tick, capped by richness)
            pop_rows = (
                db.query(TerritoryPopulation, Territory.mineral_richness, Territory.fuel_richness)
                .join(Territory, TerritoryPopulation.territory_id == Territory.id)
                .filter(TerritoryPopulation.territory_id.in_(territory_ids))
                .all()
            )
            population_delta = 0
            for pop, mineral_richness, fuel_richness in pop_rows:
                cap = round(POPULATION_CAP_MULTIPLIER * (float(mineral_richness) + float(fuel_richness)))
                if pop.current < cap:
                    growth = min(round(pop.current * POPULATION_GROWTH_RATE), cap - pop.current)
                    pop.current += growth
                    population_delta += growth
                    pop.last_updated = tick_at

            if minerals_delta or fuel_delta or population_delta or currency_delta:
                nation.minerals += minerals_delta
                nation.fuel += fuel_delta
                nation.currency += currency_delta
                db.add(ResourceLog(
                    nation_id=nation.id,
                    tick_at=tick_at,
                    minerals_delta=minerals_delta,
                    fuel_delta=fuel_delta,
                    population_delta=population_delta,
                    currency_delta=currency_delta,
                ))

        # Land in-transit fleets that have arrived
        arrived_fleets = (
            db.query(Fleet)
            .filter(Fleet.status == "in_transit", Fleet.arrives_at <= tick_at)
            .all()
        )
        for fleet in arrived_fleets:
            dest = db.get(Territory, fleet.destination_territory)
            if not dest:
                continue

            dest_id = dest.id
            is_enemy_territory = (
                dest.nation_id is not None
                and dest.nation_id != fleet.nation_id
                and _nations_at_war(db, fleet.nation_id, dest.nation_id)
            )

            if is_enemy_territory:
                fleet.status = "pending_confirmation"
                fleet.confirmation_expires_at = tick_at + _CONFIRMATION_WINDOW
                db.add(Event(
                    type="fleet_arrived_at_enemy_territory",
                    payload={
                        "fleet_id": fleet.id,
                        "attacker_nation_id": fleet.nation_id,
                        "defender_nation_id": dest.nation_id,
                        "territory_id": dest_id,
                        "node_key": dest.node_key,
                        "confirmation_expires_at": fleet.confirmation_expires_at.isoformat(),
                        "tick_at": tick_at.isoformat(),
                    },
                    scheduled_for=tick_at,
                    processed_at=tick_at,
                    status="processed",
                ))
                db.add(Event(
                    type="enemy_fleet_arrived",
                    payload={
                        "fleet_id": fleet.id,
                        "attacker_nation_id": fleet.nation_id,
                        "defender_nation_id": dest.nation_id,
                        "territory_id": dest_id,
                        "node_key": dest.node_key,
                        "unit_count": fleet.unit_count,
                        "confirmation_expires_at": fleet.confirmation_expires_at.isoformat(),
                        "tick_at": tick_at.isoformat(),
                    },
                    scheduled_for=tick_at,
                    processed_at=tick_at,
                    status="processed",
                ))
            else:
                existing = (
                    db.query(Fleet)
                    .filter(
                        Fleet.nation_id == fleet.nation_id,
                        Fleet.origin_territory == dest_id,
                        Fleet.status == "stationed",
                    )
                    .first()
                )
                if existing:
                    existing.unit_count += fleet.unit_count
                    db.delete(fleet)
                    db.add(Event(
                        type="fleet_stationed",
                        payload={
                            "fleet_id": existing.id,
                            "nation_id": fleet.nation_id,
                            "territory_id": dest_id,
                            "territory_node_key": dest.node_key,
                            "unit_count": existing.unit_count,
                            "tick_at": tick_at.isoformat(),
                        },
                        scheduled_for=tick_at,
                        processed_at=tick_at,
                        status="processed",
                    ))
                else:
                    fleet.status = "stationed"
                    fleet.origin_territory = dest_id
                    fleet.destination_territory = None
                    fleet.arrives_at = None
                    fleet.departs_at = None
                    db.add(Event(
                        type="fleet_stationed",
                        payload={
                            "fleet_id": fleet.id,
                            "nation_id": fleet.nation_id,
                            "territory_id": dest_id,
                            "territory_node_key": dest.node_key,
                            "unit_count": fleet.unit_count,
                            "tick_at": tick_at.isoformat(),
                        },
                        scheduled_for=tick_at,
                        processed_at=tick_at,
                        status="processed",
                    ))

        # Process expired confirmation windows
        expired_confirmation = (
            db.query(Fleet)
            .filter(
                Fleet.status == "pending_confirmation",
                Fleet.confirmation_expires_at <= tick_at,
            )
            .all()
        )
        for fleet in expired_confirmation:
            if fleet.standing_order == "recall":
                enemy_territory_id = fleet.destination_territory
                home_territory_id = fleet.origin_territory
                _send_fleet_home(db, fleet, tick_at)
                db.add(Event(
                    type="fleet_recalled_on_expiry",
                    payload={
                        "fleet_id": fleet.id,
                        "nation_id": fleet.nation_id,
                        "from_territory_id": enemy_territory_id,
                        "to_territory_id": home_territory_id,
                        "tick_at": tick_at.isoformat(),
                    },
                    scheduled_for=tick_at,
                    processed_at=tick_at,
                    status="processed",
                ))
            else:
                fleet.status = "holding"
                fleet.confirmation_expires_at = None
                db.add(Event(
                    type="fleet_holding_at_enemy_territory",
                    payload={
                        "fleet_id": fleet.id,
                        "nation_id": fleet.nation_id,
                        "territory_id": fleet.destination_territory,
                        "tick_at": tick_at.isoformat(),
                    },
                    scheduled_for=tick_at,
                    processed_at=tick_at,
                    status="processed",
                ))

        # Process engaged fleets (combat resolution per tick)
        engaged_fleets = (
            db.query(Fleet)
            .filter(Fleet.status == "engaged")
            .all()
        )
        for fleet in engaged_fleets:
            dest = db.get(Territory, fleet.destination_territory)
            if not dest:
                continue

            if not dest.nation_id or dest.nation_id == fleet.nation_id:
                fleet.status = "holding"
                continue

            if not _nations_at_war(db, fleet.nation_id, dest.nation_id):
                fleet.status = "holding"
                continue

            stats = UNIT_STATS["starfighter"]
            defender_fleet = (
                db.query(Fleet)
                .filter(
                    Fleet.nation_id == dest.nation_id,
                    Fleet.origin_territory == dest.id,
                    Fleet.status == "stationed",
                )
                .first()
            )

            if defender_fleet and defender_fleet.unit_count > 0:
                attacker_count = fleet.unit_count
                defender_count = defender_fleet.unit_count
                attacker_losses = max(1, round(defender_count * stats["attack"] / stats["hp"]))
                defender_losses = max(1, round(attacker_count * stats["attack"] / stats["hp"]))
                fleet.unit_count = max(0, attacker_count - attacker_losses)
                defender_fleet.unit_count = max(0, defender_count - defender_losses)

                if defender_fleet.unit_count == 0:
                    db.delete(defender_fleet)

                db.add(Event(
                    type="combat_round",
                    payload={
                        "fleet_id": fleet.id,
                        "attacker_nation_id": fleet.nation_id,
                        "defender_nation_id": dest.nation_id,
                        "territory_id": dest.id,
                        "attacker_losses": attacker_losses,
                        "defender_losses": defender_losses,
                        "attacker_remaining": fleet.unit_count,
                        "defender_remaining": max(0, defender_count - defender_losses),
                        "tick_at": tick_at.isoformat(),
                    },
                    scheduled_for=tick_at,
                    processed_at=tick_at,
                    status="processed",
                ))

                if fleet.unit_count == 0:
                    db.add(Event(
                        type="fleet_destroyed_in_combat",
                        payload={
                            "fleet_id": fleet.id,
                            "nation_id": fleet.nation_id,
                            "territory_id": dest.id,
                            "tick_at": tick_at.isoformat(),
                        },
                        scheduled_for=tick_at,
                        processed_at=tick_at,
                        status="processed",
                    ))
                    db.delete(fleet)
            else:
                # No defenders — drain resources from territory owner (soft damage model)
                defender_nation = db.get(Nation, dest.nation_id)
                if defender_nation:
                    minerals_drain = max(0, round(float(defender_nation.minerals) * 0.05))
                    fuel_drain = max(0, round(float(defender_nation.fuel) * 0.05))
                    defender_nation.minerals = max(0, defender_nation.minerals - minerals_drain)
                    defender_nation.fuel = max(0, defender_nation.fuel - fuel_drain)
                    db.add(Event(
                        type="resources_drained_by_occupation",
                        payload={
                            "fleet_id": fleet.id,
                            "attacker_nation_id": fleet.nation_id,
                            "defender_nation_id": dest.nation_id,
                            "territory_id": dest.id,
                            "minerals_drained": minerals_drain,
                            "fuel_drained": fuel_drain,
                            "tick_at": tick_at.isoformat(),
                        },
                        scheduled_for=tick_at,
                        processed_at=tick_at,
                        status="processed",
                    ))

        # Land in-transit colony ships that have arrived
        arrived_colony_ships = (
            db.query(ColonyShip)
            .filter(ColonyShip.status == "in_transit", ColonyShip.arrives_at <= tick_at)
            .all()
        )
        for ship in arrived_colony_ships:
            dest_key = db.get(Territory, ship.destination_territory)
            ship.status = "stationed"
            ship.origin_territory = ship.destination_territory
            ship.destination_territory = None
            ship.arrives_at = None
            ship.departs_at = None
            db.add(Event(
                type="colony_ship_stationed",
                payload={
                    "ship_id": ship.id,
                    "nation_id": ship.nation_id,
                    "territory_id": ship.origin_territory,
                    "territory_node_key": dest_key.node_key if dest_key else None,
                    "tick_at": tick_at.isoformat(),
                },
                scheduled_for=tick_at,
                processed_at=tick_at,
                status="processed",
            ))

        # Build territory lookup for probe movement
        all_territories = db.query(Territory).all()
        territory_by_key = {t.node_key: t for t in all_territories}

        active_probes = (
            db.query(Probe)
            .filter(Probe.status.in_(["in_transit", "stationed"]))
            .all()
        )
        for probe in active_probes:
            current_t = db.get(Territory, probe.current_territory) if probe.current_territory else None
            if not current_t:
                continue

            # Detect probes in enemy territory; destroy only during wartime
            if current_t.nation_id and current_t.nation_id != probe.nation_id:
                a = min(probe.nation_id, current_t.nation_id)
                b = max(probe.nation_id, current_t.nation_id)
                war_row = db.query(Diplomacy).filter(
                    Diplomacy.nation_a == a,
                    Diplomacy.nation_b == b,
                    Diplomacy.status == "war",
                ).first()
                # Always notify territory owner regardless of war status
                db.add(Event(
                    type="enemy_probe_detected",
                    payload={
                        "probe_id": probe.id,
                        "probe_nation_id": probe.nation_id,
                        "territory_id": current_t.id,
                        "territory_nation_id": current_t.nation_id,
                        "at_war": war_row is not None,
                        "tick_at": tick_at.isoformat(),
                    },
                    scheduled_for=tick_at,
                    processed_at=tick_at,
                    status="processed",
                ))
                if war_row:
                    probe.status = "destroyed"
                    db.add(Event(
                        type="probe_destroyed_in_enemy_territory",
                        payload={
                            "probe_id": probe.id,
                            "probe_nation_id": probe.nation_id,
                            "territory_id": current_t.id,
                            "territory_nation_id": current_t.nation_id,
                            "tick_at": tick_at.isoformat(),
                        },
                        scheduled_for=tick_at,
                        processed_at=tick_at,
                        status="processed",
                    ))
                    continue

            if probe.status == "in_transit":
                dest_t = db.get(Territory, probe.destination_territory)
                if dest_t and current_t.id != dest_t.id:
                    cq, cr = _parse_key(current_t.node_key)
                    dq, dr = _parse_key(dest_t.node_key)
                    nq, nr = _next_step(cq, cr, dq, dr)
                    next_key = f"{nq},{nr}"
                    next_t = territory_by_key.get(next_key)
                    if next_t:
                        probe.current_territory = next_t.id
                        current_t = next_t
                if dest_t and current_t.id == dest_t.id:
                    probe.status = "stationed"
                    probe.origin_territory = current_t.id
                    probe.destination_territory = None
                    probe.arrives_at = None
                    probe.departs_at = None
                    db.add(Event(
                        type="probe_stationed",
                        payload={
                            "probe_id": probe.id,
                            "nation_id": probe.nation_id,
                            "territory_id": current_t.id,
                            "territory_node_key": current_t.node_key,
                            "tick_at": tick_at.isoformat(),
                        },
                        scheduled_for=tick_at,
                        processed_at=tick_at,
                        status="processed",
                    ))

            scan_q, scan_r = _parse_key(current_t.node_key)

            # Generate any uncharted territories within probe vision radius
            for dq in range(-PROBE_VISION_RADIUS, PROBE_VISION_RADIUS + 1):
                for dr in range(-PROBE_VISION_RADIUS, PROBE_VISION_RADIUS + 1):
                    if _hex_dist(0, 0, dq, dr) > PROBE_VISION_RADIUS:
                        continue
                    vq, vr = scan_q + dq, scan_r + dr
                    vkey = f"{vq},{vr}"
                    if vkey not in territory_by_key:
                        new_t = generate_territory(vq, vr)
                        db.add(new_t)
                        db.flush()
                        territory_by_key[vkey] = new_t

            # Record ProbeData for non-void territories in vision radius
            for dq in range(-PROBE_VISION_RADIUS, PROBE_VISION_RADIUS + 1):
                for dr in range(-PROBE_VISION_RADIUS, PROBE_VISION_RADIUS + 1):
                    if _hex_dist(0, 0, dq, dr) > PROBE_VISION_RADIUS:
                        continue
                    vq, vr = scan_q + dq, scan_r + dr
                    t = territory_by_key.get(f"{vq},{vr}")
                    if not t or t.territory_type == "void":
                        continue
                    existing = db.query(ProbeData).filter(
                        ProbeData.territory_id == t.id,
                        ProbeData.discovered_by == probe.nation_id,
                    ).first()
                    if existing:
                        existing.mineral_richness = t.mineral_richness
                        existing.fuel_richness = t.fuel_richness
                        existing.discovered_at = tick_at
                    else:
                        db.add(ProbeData(
                            territory_id=t.id,
                            discovered_by=probe.nation_id,
                            mineral_richness=t.mineral_richness,
                            fuel_richness=t.fuel_richness,
                        ))

        db.add(Event(
            type="tick",
            payload={"tick_at": tick_at.isoformat(), "nations_processed": len(nations)},
            scheduled_for=tick_at,
            processed_at=tick_at,
            status="processed",
        ))

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
