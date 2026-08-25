from datetime import datetime, timezone, timedelta
from math import ceil
from sqlalchemy import or_, and_, text, func as sqlfunc
from ..celery_app import celery_app
from ..db.database import SessionLocal
from ..models.colony_ship import ColonyShip
from ..models.fleet import Fleet
from ..models.nation import Nation
from ..models.infrastructure import Infrastructure
from ..models.player import Player
from ..models.territory import Territory
from ..models.resource_log import ResourceLog
from ..models.event import Event
from ..models.territory_population import TerritoryPopulation
from ..models.territory_dissent import TerritoryDissent
from ..models.tutorial import TutorialState
from ..models.diplomacy import Diplomacy
from ..services.tutorial import should_complete_step, get_tutorial_reward, next_step as tutorial_next_step, should_complete_step_on_action
from ..models.probe import Probe
from ..models.probe_data import ProbeData
from .email_tasks import send_email_task
from ..models.probe_visibility import ProbeVisibility
from ..services.combat import resolve_combat_tick
from ..services.logistics import compute_logistics_fuel_cost
from ..services.territory_yield import compute_territory_yield, dissent_production_modifier
from ..constants import (
    POPULATION_GROWTH_RATE, POPULATION_CAP_MULTIPLIER, PROBE_VISION_RADIUS,
    UNIT_STATS, FACILITY_COSTS, FACILITY_POPULATION_COST, DEMOLISH_REFUND_FRACTION, LOGISTICS_FUEL_K,
    TERRITORY_UPKEEP_K,
    DISSENT_WAR_AGGRESSOR, DISSENT_WAR_DEFENDER,
    DISSENT_FLEET_HOLDING, DISSENT_FLEET_ENGAGED, DISSENT_CONQUEST_RESET,
    DISSENT_DECAY_PEACE, DISSENT_DECAY_WAR, DISSENT_DECAY_OCCUPIED,
    DISSENT_OFFICE_BONUS_NORMAL, DISSENT_OFFICE_BONUS_OCCUPIED,
    DISSENT_LOPSIDED_MULTIPLIER, DISSENT_OFFICE_BONUS_AGGRESSOR,
    HOME_TERRITORY_DEFENSE_MULTIPLIER,
    HOLDING_ATTRITION_RATE,
    DEFENDER_AUTO_ROUT_FRACTION,
    WAR_MAX_DURATION_DAYS,
)
from ..services.dissent import compute_territory_dissent_delta
from ..map_gen import generate_territory

TICK_HOURS = 2
_CONFIRMATION_WINDOW = timedelta(hours=TICK_HOURS * 2)  # 2 ticks = 4 hours


def _get_diplomacy_status(db, nation_a_id: int, nation_b_id: int) -> str:
    a, b = min(nation_a_id, nation_b_id), max(nation_a_id, nation_b_id)
    row = db.query(Diplomacy).filter(Diplomacy.nation_a == a, Diplomacy.nation_b == b).first()
    return row.status if row else "neutral"


def _nations_at_war(db, nation_a_id: int, nation_b_id: int) -> bool:
    return _get_diplomacy_status(db, nation_a_id, nation_b_id) == "war"


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


_DISSENT_THRESHOLDS = (25, 50, 75, 100)


def _next_step(cq, cr, dq, dr):
    neighbors = [(cq+1, cr), (cq-1, cr), (cq, cr+1), (cq, cr-1), (cq+1, cr-1), (cq-1, cr+1)]
    return min(neighbors, key=lambda nb: _hex_dist(nb[0], nb[1], dq, dr))


@celery_app.task(name="app.tasks.tick.run_tick")
def run_tick():
    db = SessionLocal()
    tick_at = datetime.now(timezone.utc)
    try:
        # Promote war_pending rows whose grace period has elapsed to full war
        pending_wars = (
            db.query(Diplomacy)
            .filter(Diplomacy.status == "war_pending", Diplomacy.war_starts_at <= tick_at)
            .all()
        )
        for row in pending_wars:
            row.status = "war"
            row.war_starts_at = None
            row.war_started_at = tick_at
            row.updated_at = tick_at
            db.add(Event(
                type="war_started",
                payload={
                    "nation_a": row.nation_a,
                    "nation_b": row.nation_b,
                    "tick_at": tick_at.isoformat(),
                },
                scheduled_for=tick_at,
                processed_at=tick_at,
                status="processed",
            ))

            # War-activation sweep: any fleet that was already stationed or holding
            # at an enemy planet (staged during war_pending) enters pending_confirmation
            # now so the defender gets the standard 4-hour response window from the
            # moment hostilities begin.
            for attacker_id, defender_id in [
                (row.nation_a, row.nation_b),
                (row.nation_b, row.nation_a),
            ]:
                defender_territory_ids = [
                    t.id for t in db.query(Territory).filter(Territory.nation_id == defender_id).all()
                ]
                if not defender_territory_ids:
                    continue

                # stationed fleets: origin_territory is where they're parked
                pre_staged_stationed = db.query(Fleet).filter(
                    Fleet.nation_id == attacker_id,
                    Fleet.status == "stationed",
                    Fleet.origin_territory.in_(defender_territory_ids),
                ).all()
                for fleet in pre_staged_stationed:
                    enemy_territory = db.get(Territory, fleet.origin_territory)
                    fleet.status = "pending_confirmation"
                    fleet.destination_territory = fleet.origin_territory
                    fleet.confirmation_expires_at = tick_at + _CONFIRMATION_WINDOW
                    db.add(Event(
                        type="fleet_arrived_at_enemy_territory",
                        payload={
                            "fleet_id": fleet.id,
                            "attacker_nation_id": attacker_id,
                            "defender_nation_id": defender_id,
                            "territory_id": fleet.origin_territory,
                            "node_key": enemy_territory.node_key if enemy_territory else None,
                            "confirmation_expires_at": fleet.confirmation_expires_at.isoformat(),
                            "reason": "war_activation_sweep",
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
                            "attacker_nation_id": attacker_id,
                            "defender_nation_id": defender_id,
                            "territory_id": fleet.origin_territory,
                            "node_key": enemy_territory.node_key if enemy_territory else None,
                            "unit_count": fleet.unit_count,
                            "confirmation_expires_at": fleet.confirmation_expires_at.isoformat(),
                            "reason": "war_activation_sweep",
                            "tick_at": tick_at.isoformat(),
                        },
                        scheduled_for=tick_at,
                        processed_at=tick_at,
                        status="processed",
                    ))

                # holding fleets (from war_pending arrival quarantine):
                # destination_territory is already the enemy planet
                pre_staged_holding = db.query(Fleet).filter(
                    Fleet.nation_id == attacker_id,
                    Fleet.status == "holding",
                    Fleet.destination_territory.in_(defender_territory_ids),
                ).all()
                for fleet in pre_staged_holding:
                    enemy_territory = db.get(Territory, fleet.destination_territory)
                    fleet.status = "pending_confirmation"
                    fleet.confirmation_expires_at = tick_at + _CONFIRMATION_WINDOW
                    db.add(Event(
                        type="fleet_arrived_at_enemy_territory",
                        payload={
                            "fleet_id": fleet.id,
                            "attacker_nation_id": attacker_id,
                            "defender_nation_id": defender_id,
                            "territory_id": fleet.destination_territory,
                            "node_key": enemy_territory.node_key if enemy_territory else None,
                            "confirmation_expires_at": fleet.confirmation_expires_at.isoformat(),
                            "reason": "war_activation_sweep",
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
                            "attacker_nation_id": attacker_id,
                            "defender_nation_id": defender_id,
                            "territory_id": fleet.destination_territory,
                            "node_key": enemy_territory.node_key if enemy_territory else None,
                            "unit_count": fleet.unit_count,
                            "confirmation_expires_at": fleet.confirmation_expires_at.isoformat(),
                            "reason": "war_activation_sweep",
                            "tick_at": tick_at.isoformat(),
                        },
                        scheduled_for=tick_at,
                        processed_at=tick_at,
                        status="processed",
                    ))

        # Auto white-peace: wars exceeding WAR_MAX_DURATION_DAYS resolve automatically.
        # Covers inactive/deleted players who cannot confirm a bilateral peace.
        # 48h redeclaration cooldown applies to prevent immediate re-escalation.
        expired_wars = (
            db.query(Diplomacy)
            .filter(
                Diplomacy.status == "war",
                Diplomacy.war_started_at <= tick_at - timedelta(days=WAR_MAX_DURATION_DAYS),
            )
            .all()
        )
        for row in expired_wars:
            row.status = "neutral"
            row.war_started_at = None
            row.declared_by = None
            row.peace_until = tick_at + timedelta(hours=48)
            row.updated_at = tick_at
            db.add(Event(
                type="war_auto_ended",
                payload={
                    "nation_a": row.nation_a,
                    "nation_b": row.nation_b,
                    "reason": "maximum_duration_reached",
                    "max_days": WAR_MAX_DURATION_DAYS,
                    "tick_at": tick_at.isoformat(),
                },
                scheduled_for=tick_at,
                processed_at=tick_at,
                status="processed",
            ))

        nations = db.query(Nation).all()

        # Pre-load dissent values for all territories (used for production modifier this tick)
        dissent_map: dict[int, int] = {
            row.territory_id: row.dissent
            for row in db.query(TerritoryDissent).all()
        }

        # Build per-nation dissent accumulation from all active wars.
        # Each planet accrues from only one war — the one with the highest contribution.
        # A nation in multiple wars does not stack penalties; the worst single war sets the rate.
        # war_state maps nation_id -> (max_contribution, is_aggressor_in_max_war, is_lopsided_in_max_war)
        war_state: dict[int, tuple[int, bool, bool]] = {}
        aggressor_nation_ids: set[int] = set()
        at_war: set[int] = set()
        for war_row in db.query(Diplomacy).filter(Diplomacy.status == "war").all():
            for nid in (war_row.nation_a, war_row.nation_b):
                is_agg = war_row.declared_by == nid
                if is_agg:
                    lopsided = bool(war_row.is_lopsided)
                    contribution = round(DISSENT_WAR_AGGRESSOR * DISSENT_LOPSIDED_MULTIPLIER) if lopsided else DISSENT_WAR_AGGRESSOR
                    aggressor_nation_ids.add(nid)
                else:
                    lopsided = False
                    contribution = DISSENT_WAR_DEFENDER
                current = war_state.get(nid)
                if current is None or contribution > current[0]:
                    war_state[nid] = (contribution, is_agg, lopsided and is_agg)
                at_war.add(nid)
        war_dissent_delta: dict[int, int] = {nid: v[0] for nid, v in war_state.items()}

        for nation in nations:
            territory_ids = [
                t_id for (t_id,) in
                db.query(Territory.id).filter(Territory.nation_id == nation.id).all()
            ]

            facilities = (
                db.query(
                    Infrastructure.type,
                    Infrastructure.territory_id,
                    Territory.mineral_richness,
                    Territory.fuel_richness,
                    Territory.territory_type,
                )
                .join(Territory, Infrastructure.territory_id == Territory.id)
                .filter(Territory.nation_id == nation.id, Infrastructure.status == "active")
                .all()
            )

            minerals_delta = 0
            fuel_delta = 0
            for ftype, t_id, mineral_richness, fuel_richness, territory_type in facilities:
                modifier = dissent_production_modifier(dissent_map.get(t_id, 0))
                if ftype == "mine":
                    r = float(mineral_richness)
                    if territory_type == "anomaly":
                        minerals_delta += round((r * 2 + 10) * modifier)
                    else:
                        minerals_delta += round(max(5, round(r * 2)) * modifier)
                elif ftype == "refinery":
                    r = float(fuel_richness)
                    if territory_type == "anomaly":
                        fuel_delta += round((r * 2 + 10) * modifier)
                    else:
                        fuel_delta += round(max(5, round(r * 2)) * modifier)

            # 30 currency per active mine or refinery
            income_facility_count = sum(1 for ftype, *_ in facilities if ftype in ("mine", "refinery"))
            currency_delta = 30 * income_facility_count

            # Currency upkeep: 2 currency per fighter per tick (all fleets regardless of status)
            fighter_upkeep = (
                db.query(sqlfunc.coalesce(sqlfunc.sum(Fleet.unit_count), 0))
                .filter(Fleet.nation_id == nation.id)
                .scalar()
            )
            currency_delta -= fighter_upkeep * 2

            # Territory count upkeep: k × N² per tick, where N = territories owned.
            # Creates superlinear expansion cost so large empires can't accumulate
            # currency faster than small ones indefinitely.
            currency_delta -= TERRITORY_UPKEEP_K * len(territory_ids) ** 2

            # Fuel upkeep: 1 fuel per fighter not docked on own territory.
            # "Docked" = stationed on a territory owned by this nation.
            # All other statuses (in_transit, holding, engaged, pending_confirmation)
            # and stationed fleets on foreign/unclaimed territory all pay upkeep.
            in_space_units = (
                db.query(sqlfunc.coalesce(sqlfunc.sum(Fleet.unit_count), 0))
                .filter(
                    Fleet.nation_id == nation.id,
                    Fleet.status != "stationed",
                )
                .scalar()
            )
            stationed_foreign_units = (
                db.query(sqlfunc.coalesce(sqlfunc.sum(Fleet.unit_count), 0))
                .join(Territory, Fleet.origin_territory == Territory.id)
                .filter(
                    Fleet.nation_id == nation.id,
                    Fleet.status == "stationed",
                    or_(Territory.nation_id.is_(None), Territory.nation_id != nation.id),
                )
                .scalar()
            )
            fuel_delta -= (in_space_units + stationed_foreign_units)

            # Logistics upkeep: quadratic fuel cost on territory count.
            # The Nth territory costs N fuel/tick; total = N(N+1)/2.
            # k=1 is the beta starting point; adjust LOGISTICS_FUEL_K to tune.
            fuel_delta -= compute_logistics_fuel_cost(len(territory_ids), k=LOGISTICS_FUEL_K)

            # Grow population in each territory (1%/tick of free pop, capped by richness).
            # Cap applies to total pop (free + employed); pre-load facility costs per territory.
            facility_pop_by_territory: dict[int, int] = {}
            for tid, ftype in (
                db.query(Infrastructure.territory_id, Infrastructure.type)
                .filter(
                    Infrastructure.territory_id.in_(territory_ids),
                    Infrastructure.status.in_(["active", "under_construction"]),
                )
                .all()
            ):
                facility_pop_by_territory[tid] = (
                    facility_pop_by_territory.get(tid, 0) + FACILITY_POPULATION_COST.get(ftype, 0)
                )

            pop_rows = (
                db.query(TerritoryPopulation, Territory.mineral_richness, Territory.fuel_richness)
                .join(Territory, TerritoryPopulation.territory_id == Territory.id)
                .filter(TerritoryPopulation.territory_id.in_(territory_ids))
                .all()
            )
            population_delta = 0
            for pop, mineral_richness, fuel_richness in pop_rows:
                cap = round(POPULATION_CAP_MULTIPLIER * (float(mineral_richness) + float(fuel_richness)))
                employed = facility_pop_by_territory.get(pop.territory_id, 0)
                total_pop = pop.current + employed
                if total_pop < cap:
                    growth = min(max(1, round(pop.current * POPULATION_GROWTH_RATE)), cap - total_pop)
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

        # Complete facility constructions
        due_constructions = (
            db.query(Infrastructure)
            .filter(Infrastructure.status == "under_construction", Infrastructure.completes_at <= tick_at)
            .all()
        )
        for infra in due_constructions:
            infra.status = "active"
            infra.completes_at = None
            db.add(Event(
                type="facility_construction_complete",
                payload={
                    "infrastructure_id": infra.id,
                    "territory_id": infra.territory_id,
                    "facility_type": infra.type,
                    "tick_at": tick_at.isoformat(),
                },
                scheduled_for=tick_at,
                processed_at=tick_at,
                status="processed",
            ))
            territory_obj = db.get(Territory, infra.territory_id)
            if territory_obj and territory_obj.nation_id:
                tutorial = db.query(TutorialState).filter(
                    TutorialState.nation_id == territory_obj.nation_id,
                    TutorialState.dismissed == False,
                ).first()
                if tutorial and should_complete_step(tutorial.current_step, infra.type):
                    reward = get_tutorial_reward(tutorial.current_step)
                    nation_obj = db.get(Nation, territory_obj.nation_id)
                    if nation_obj:
                        nation_obj.minerals += reward["minerals"]
                        nation_obj.fuel += reward["fuel"]
                        nation_obj.currency += reward["currency"]
                    completed_step = tutorial.current_step
                    setattr(tutorial, f"step{completed_step}_completed_at", tick_at)
                    tutorial.current_step = tutorial_next_step(tutorial.current_step)
                    db.add(Event(
                        type="tutorial_step_complete",
                        payload={
                            "step": completed_step,
                            "nation_id": territory_obj.nation_id,
                            "reward_minerals": reward["minerals"],
                            "reward_fuel": reward["fuel"],
                            "reward_currency": reward["currency"],
                            "tick_at": tick_at.isoformat(),
                        },
                        scheduled_for=tick_at,
                        processed_at=tick_at,
                        status="processed",
                    ))

        # Complete facility demolitions — refund 25% of build cost (floored)
        due_demolitions = (
            db.query(Infrastructure, Territory.nation_id)
            .join(Territory, Infrastructure.territory_id == Territory.id)
            .filter(Infrastructure.status == "demolishing", Infrastructure.completes_at <= tick_at)
            .all()
        )
        for infra, nation_id in due_demolitions:
            nation_obj = db.get(Nation, nation_id)
            if nation_obj:
                cost = FACILITY_COSTS.get(infra.type, {"minerals": 0, "fuel": 0})
                minerals_refund = int(cost["minerals"] * DEMOLISH_REFUND_FRACTION)
                fuel_refund = int(cost["fuel"] * DEMOLISH_REFUND_FRACTION)
                currency_refund = int(cost.get("currency", 0) * DEMOLISH_REFUND_FRACTION)
                nation_obj.minerals += minerals_refund
                nation_obj.fuel += fuel_refund
                nation_obj.currency += currency_refund
                pop_cost = FACILITY_POPULATION_COST.get(infra.type, 0)
                if pop_cost > 0:
                    pop_row = db.query(TerritoryPopulation).filter(
                        TerritoryPopulation.territory_id == infra.territory_id
                    ).first()
                    if pop_row:
                        pop_row.current += pop_cost
                db.add(Event(
                    type="facility_demolition_complete",
                    payload={
                        "infrastructure_id": infra.id,
                        "territory_id": infra.territory_id,
                        "facility_type": infra.type,
                        "minerals_refunded": minerals_refund,
                        "fuel_refunded": fuel_refund,
                        "currency_refunded": currency_refund,
                        "tick_at": tick_at.isoformat(),
                    },
                    scheduled_for=tick_at,
                    processed_at=tick_at,
                    status="processed",
                ))
            db.delete(infra)

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
            dest_owner = dest.nation_id
            is_other_nation = dest_owner is not None and dest_owner != fleet.nation_id
            is_planet = dest.territory_type != "void"

            if is_other_nation:
                diplo = _get_diplomacy_status(db, fleet.nation_id, dest_owner)

                if diplo == "war" and is_planet:
                    # Confirmation window required; alert both sides
                    fleet.status = "pending_confirmation"
                    fleet.confirmation_expires_at = tick_at + _CONFIRMATION_WINDOW
                    db.add(Event(
                        type="fleet_arrived_at_enemy_territory",
                        payload={
                            "fleet_id": fleet.id,
                            "attacker_nation_id": fleet.nation_id,
                            "defender_nation_id": dest_owner,
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
                            "defender_nation_id": dest_owner,
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
                    continue

                if diplo == "war_pending" and is_planet:
                    # Fleet arrives at a planet during the grace period before war activates.
                    # Land as holding (not stationed) so it cannot attack the instant war
                    # begins. The war-activation sweep will move it to pending_confirmation
                    # when the war row promotes to "war", giving the defender the standard
                    # 4-hour response window from the moment hostilities begin.
                    fleet.status = "holding"
                    fleet.arrives_at = None
                    fleet.departs_at = None
                    db.add(Event(
                        type="enemy_fleet_holding_at_border",
                        payload={
                            "fleet_id": fleet.id,
                            "attacker_nation_id": fleet.nation_id,
                            "defender_nation_id": dest_owner,
                            "territory_id": dest_id,
                            "node_key": dest.node_key,
                            "unit_count": fleet.unit_count,
                            "tick_at": tick_at.isoformat(),
                        },
                        scheduled_for=tick_at,
                        processed_at=tick_at,
                        status="processed",
                    ))
                    continue

                if diplo in ("war", "war_pending") and not is_planet:
                    # Fleet (at war or pre-war) enters void territory: alert and land normally.
                    db.add(Event(
                        type="enemy_fleet_entered_territory",
                        payload={
                            "fleet_id": fleet.id,
                            "attacker_nation_id": fleet.nation_id,
                            "defender_nation_id": dest_owner,
                            "territory_id": dest_id,
                            "node_key": dest.node_key,
                            "unit_count": fleet.unit_count,
                            "territory_type": dest.territory_type,
                            "diplomacy_status": diplo,
                            "tick_at": tick_at.isoformat(),
                        },
                        scheduled_for=tick_at,
                        processed_at=tick_at,
                        status="processed",
                    ))
                    # fall through to normal landing below

            # Normal landing: merge into stationed or create new stationed fleet
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
                # Email the attacker: they missed their post-battle choice window.
                attacker_nation = db.get(Nation, fleet.nation_id)
                if attacker_nation:
                    attacker_player = db.query(Player).filter(
                        Player.id == attacker_nation.player_id
                    ).first()
                    if attacker_player and attacker_player.email_notifications_enabled:
                        dest_territory = db.get(Territory, fleet.destination_territory)
                        territory_name = (
                            dest_territory.name or dest_territory.node_key
                            if dest_territory else "unknown territory"
                        )
                        send_email_task.delay(
                            attacker_player.email,
                            "Spationsim: Fleet confirmation window expired",
                            (
                                f"Hi {attacker_player.username},\n\n"
                                f"Your fleet at {territory_name} did not receive orders before "
                                f"the confirmation window closed. It is now holding in place.\n\n"
                                f"Log in to issue new orders: Raid, Rout, Raze, or Recall.\n\n"
                                f"Spationsim"
                            ),
                        )

        # Snapshot fleet presence BEFORE combat so dissent reflects this tick's battle state.
        # engaged/holding fleets transition to occupying/post_battle_choice during combat,
        # so we must capture the starting status here before the combat loop mutates it.
        holding_on: set[int] = set()   # territory_ids with a holding enemy fleet
        engaged_on: set[int] = set()   # territory_ids with an engaged enemy fleet
        for _sf in db.query(Fleet).filter(Fleet.status.in_(["holding", "engaged", "occupying"])).all():
            if _sf.destination_territory is None:
                continue
            _sf_dest = db.get(Territory, _sf.destination_territory)
            if _sf_dest and _sf_dest.nation_id and _sf_dest.nation_id != _sf.nation_id:
                if _sf.status in ("holding", "occupying"):
                    holding_on.add(_sf_dest.id)
                else:
                    engaged_on.add(_sf_dest.id)

        # Process engaged fleets and holding fleets with standing_order='engage' (combat resolution per tick)
        combat_fleets = (
            db.query(Fleet)
            .filter(
                or_(
                    Fleet.status == "engaged",
                    and_(Fleet.status == "holding", Fleet.standing_order == "engage")
                )
            )
            .all()
        )
        for fleet in combat_fleets:
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
                multiplier = (
                    HOME_TERRITORY_DEFENSE_MULTIPLIER
                    if dest.is_owned and dest.nation_id == defender_fleet.nation_id
                    else 1.0
                )
                attacker_losses, defender_losses = resolve_combat_tick(
                    attacker_count, stats,
                    defender_count, stats,
                    home_territory_multiplier=multiplier,
                )
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

                # Defender auto-rout: bonus damage when defender survived and attacker took losses.
                # Fires even if attacker was already wiped in normal combat (fleet.unit_count may be 0).
                # bonus_damage records the raw formula result; actual damage applied is capped at remaining fleet.
                if attacker_losses > 0 and fleet.unit_count > 0 and defender_fleet.unit_count > 0:
                    auto_rout_bonus = max(1, round(attacker_losses * DEFENDER_AUTO_ROUT_FRACTION))
                    actual_auto_rout = min(auto_rout_bonus, fleet.unit_count)
                    fleet.unit_count -= actual_auto_rout
                    db.add(Event(
                        type="auto_rout_applied",
                        payload={
                            "fleet_id": fleet.id,
                            "attacker_nation_id": fleet.nation_id,
                            "defender_nation_id": dest.nation_id,
                            "territory_id": dest.id,
                            "bonus_damage": auto_rout_bonus,
                            "damage_applied": actual_auto_rout,
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
                    # Attacker survived — pause for post-battle choice (Rout/Raid/Raze).
                    # standing_order resets to 'hold' so inaction on PBC expiry is safe.
                    fleet.status = "post_battle_choice"
                    fleet.standing_order = "hold"
                    fleet.confirmation_expires_at = tick_at + _CONFIRMATION_WINDOW

            else:
                # Enemy territory, no defending fleet — enter occupation window
                fleet.status = "occupying"
                fleet.occupation_expires_at = tick_at + timedelta(hours=12)
                db.add(Event(
                    type="territory_uncontested",
                    payload={
                        "fleet_id": fleet.id,
                        "attacker_nation_id": fleet.nation_id,
                        "territory_id": dest.id,
                        "node_key": dest.node_key,
                        "tick_at": tick_at.isoformat(),
                    },
                    scheduled_for=tick_at,
                    processed_at=tick_at,
                    status="processed",
                ))

        # Expired post_battle_choice fleets go to holding by default (inaction = safe).
        # Exception: if the destination territory has sortie_queued=True, go to engaged instead.
        expired_pbc = (
            db.query(Fleet)
            .filter(Fleet.status == "post_battle_choice", Fleet.confirmation_expires_at <= tick_at)
            .all()
        )
        for fleet in expired_pbc:
            fleet.confirmation_expires_at = None
            fleet.standing_order = "hold"
            dest_territory = db.get(Territory, fleet.destination_territory) if fleet.destination_territory else None
            if dest_territory and getattr(dest_territory, "sortie_queued", False):
                fleet.status = "engaged"
                dest_territory.sortie_queued = False
            else:
                fleet.status = "holding"

        # territory_id -> set of nation_ids with stationed fleets there
        stationed_at: dict[int, set[int]] = {}
        for sf in db.query(Fleet).filter(Fleet.status == "stationed").all():
            stationed_at.setdefault(sf.origin_territory, set()).add(sf.nation_id)

        # nation_id -> set of nation_ids it is currently at war with
        at_war_with: dict[int, set[int]] = {}
        for war_row in db.query(Diplomacy).filter(Diplomacy.status == "war").all():
            at_war_with.setdefault(war_row.nation_a, set()).add(war_row.nation_b)
            at_war_with.setdefault(war_row.nation_b, set()).add(war_row.nation_a)

        # Attrition only applies when the holding fleet shares its destination territory
        # with stationed fleets from a nation it is at war with.
        holding_fleets = (
            db.query(Fleet)
            .filter(Fleet.status == "holding")
            .all()
        )
        for fleet in holding_fleets:
            nations_present = stationed_at.get(fleet.destination_territory, set())
            enemies = at_war_with.get(fleet.nation_id, set())
            if not nations_present & enemies:
                continue
            losses = max(1, round(fleet.unit_count * HOLDING_ATTRITION_RATE))
            remaining = fleet.unit_count - losses
            if remaining <= 0:
                db.add(Event(
                    type="fleet_destroyed_by_attrition",
                    payload={
                        "fleet_id": fleet.id,
                        "nation_id": fleet.nation_id,
                        "tick_at": tick_at.isoformat(),
                    },
                    scheduled_for=tick_at,
                    processed_at=tick_at,
                    status="processed",
                ))
                db.delete(fleet)
            else:
                fleet.unit_count = remaining
                db.add(Event(
                    type="holding_fleet_attrition",
                    payload={
                        "fleet_id": fleet.id,
                        "nation_id": fleet.nation_id,
                        "losses": losses,
                        "remaining": remaining,
                        "tick_at": tick_at.isoformat(),
                    },
                    scheduled_for=tick_at,
                    processed_at=tick_at,
                    status="processed",
                ))

        # ── Occupation window processing ─────────────────────────────────────
        occupying_fleets = (
            db.query(Fleet)
            .filter(Fleet.status == "occupying")
            .all()
        )
        for fleet in occupying_fleets:
            dest = db.get(Territory, fleet.destination_territory)
            if not dest:
                continue

            # Enemy defender returned — cancel window and revert to holding
            enemy_stationed = (
                db.query(Fleet)
                .filter(
                    Fleet.nation_id == dest.nation_id,
                    Fleet.origin_territory == dest.id,
                    Fleet.status == "stationed",
                )
                .first()
            )
            if enemy_stationed and enemy_stationed.unit_count > 0:
                fleet.status = "holding"
                fleet.occupation_expires_at = None
                db.add(Event(
                    type="occupation_window_cancelled",
                    payload={
                        "fleet_id": fleet.id,
                        "territory_id": dest.id,
                        "tick_at": tick_at.isoformat(),
                    },
                    scheduled_for=tick_at,
                    processed_at=tick_at,
                    status="processed",
                ))
                continue

            # Window expired — auto-recall
            if fleet.occupation_expires_at and fleet.occupation_expires_at <= tick_at:
                recall_from = fleet.destination_territory
                _send_fleet_home(db, fleet, tick_at)
                fleet.occupation_expires_at = None

                db.add(Event(
                    type="occupation_window_expired",
                    payload={
                        "fleet_id": fleet.id,
                        "nation_id": fleet.nation_id,
                        "territory_id": recall_from,
                        "tick_at": tick_at.isoformat(),
                    },
                    scheduled_for=tick_at,
                    processed_at=tick_at,
                    status="processed",
                ))

        # ── Dissent update ────────────────────────────────────────────────────
        # holding_on/engaged_on were snapshotted before the combat loop above.

        # Propaganda Office presence: set of territory_ids with an active office
        office_territories: set[int] = {
            t_id for (t_id,) in db.query(Infrastructure.territory_id).filter(
                Infrastructure.type == "propaganda_office",
                Infrastructure.status == "active",
            ).all()
        }

        # Rebuild war dissent delta with fresh data (war_pending may have promoted above).
        # war_state maps nation_id -> (max_contribution, is_aggressor_in_max_war, is_lopsided_in_max_war)
        war_state = {}
        aggressor_nation_ids = set()
        at_war = set()
        for war_row in db.query(Diplomacy).filter(Diplomacy.status == "war").all():
            for nid in (war_row.nation_a, war_row.nation_b):
                is_agg = war_row.declared_by == nid
                if is_agg:
                    lopsided = bool(war_row.is_lopsided)
                    contribution = round(DISSENT_WAR_AGGRESSOR * DISSENT_LOPSIDED_MULTIPLIER) if lopsided else DISSENT_WAR_AGGRESSOR
                    aggressor_nation_ids.add(nid)
                else:
                    lopsided = False
                    contribution = DISSENT_WAR_DEFENDER
                current = war_state.get(nid)
                if current is None or contribution > current[0]:
                    war_state[nid] = (contribution, is_agg, lopsided and is_agg)
                at_war.add(nid)
        war_dissent_delta = {nid: v[0] for nid, v in war_state.items()}

        # Vacation-mode nations: tick is frozen, dissent must not accumulate or decay
        vacation_nation_ids: set[int] = {
            n_id for (n_id,) in
            db.query(Nation.id)
            .join(Player, Nation.player_id == Player.id)
            .filter(Player.vacation_mode.is_(True))
            .all()
        }

        # Process dissent for every colonized territory
        for t in db.query(Territory).filter(Territory.is_owned == True).all():
            if t.nation_id is None:
                continue
            if t.nation_id in vacation_nation_ids:
                continue

            row = db.query(TerritoryDissent).filter(TerritoryDissent.territory_id == t.id).first()
            if row is None:
                row = TerritoryDissent(territory_id=t.id, dissent=0)
                db.add(row)

            old_dissent = row.dissent
            contrib, is_agg, is_lopsided_agg = war_state.get(t.nation_id, (0, False, False))
            fleet_status_str = ("engaged" if t.id in engaged_on else
                                ("holding" if t.id in holding_on else None))
            delta = compute_territory_dissent_delta(
                at_war=t.nation_id in at_war,
                is_aggressor=is_agg,
                is_lopsided_aggressor=is_lopsided_agg,
                fleet_status=fleet_status_str,
                has_propaganda_office=t.id in office_territories,
                is_aggressor_in_any_active_war=t.nation_id in aggressor_nation_ids,
            )

            new_dissent = max(0, min(100, old_dissent + delta))
            row.dissent = new_dissent
            row.last_updated = tick_at

            # Log threshold crossings (both rising and falling)
            for threshold in _DISSENT_THRESHOLDS:
                crossed_up = old_dissent < threshold <= new_dissent
                crossed_down = old_dissent >= threshold > new_dissent
                if crossed_up or crossed_down:
                    db.add(Event(
                        type="dissent_threshold_crossed",
                        payload={
                            "nation_id": t.nation_id,
                            "territory_id": t.id,
                            "node_key": t.node_key,
                            "threshold": threshold,
                            "direction": "rising" if crossed_up else "falling",
                            "dissent": new_dissent,
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
            dest_territory = db.get(Territory, ship.destination_territory)

            claimed_now = False
            if dest_territory and dest_territory.nation_id is None:
                dest_territory.nation_id = ship.nation_id
                dest_territory.is_owned = True
                dest_territory.owned_at = tick_at
                claimed_now = True
                if not db.query(TerritoryDissent).filter(TerritoryDissent.territory_id == dest_territory.id).first():
                    db.add(TerritoryDissent(territory_id=dest_territory.id, dissent=0))
                db.add(Event(
                    type="territory_claimed",
                    payload={
                        "nation_id": ship.nation_id,
                        "territory_id": dest_territory.id,
                        "node_key": dest_territory.node_key if dest_territory else None,
                        "claimed_by": "colony_ship",
                        "tick_at": tick_at.isoformat(),
                    },
                    scheduled_for=tick_at,
                    processed_at=tick_at,
                    status="processed",
                ))

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
                    "territory_node_key": dest_territory.node_key if dest_territory else None,
                    "claimed_now": claimed_now,
                    "tick_at": tick_at.isoformat(),
                },
                scheduled_for=tick_at,
                processed_at=tick_at,
                status="processed",
            ))
            if ship.nation_id:
                colonized_count = db.query(Territory).filter(
                    Territory.nation_id == ship.nation_id,
                    Territory.is_owned == True,
                ).count()
                if colonized_count >= 2:
                    tutorial = db.query(TutorialState).filter(
                        TutorialState.nation_id == ship.nation_id,
                        TutorialState.dismissed == False,
                    ).first()
                    if tutorial and should_complete_step_on_action(tutorial.current_step, "colonize_territory"):
                        reward = get_tutorial_reward(tutorial.current_step)
                        nation_obj = db.get(Nation, ship.nation_id)
                        if nation_obj:
                            nation_obj.minerals += reward["minerals"]
                            nation_obj.fuel += reward["fuel"]
                            nation_obj.currency += reward["currency"]
                        completed_step = tutorial.current_step
                        tutorial.current_step = tutorial_next_step(tutorial.current_step)
                        db.add(Event(
                            type="tutorial_step_complete",
                            payload={
                                "step": completed_step,
                                "nation_id": ship.nation_id,
                                "reward_minerals": reward["minerals"],
                                "reward_fuel": reward["fuel"],
                                "reward_currency": reward["currency"],
                                "tick_at": tick_at.isoformat(),
                            },
                            scheduled_for=tick_at,
                            processed_at=tick_at,
                            status="processed",
                        ))

        def _record_visibility(nation_id: int, territory_id: int) -> None:
            """Mark a territory as seen by a nation (probe path tile). Idempotent."""
            exists = db.query(ProbeVisibility).filter(
                ProbeVisibility.nation_id == nation_id,
                ProbeVisibility.territory_id == territory_id,
            ).first()
            if not exists:
                db.add(ProbeVisibility(nation_id=nation_id, territory_id=territory_id))

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

            # Detect probes in foreign territory; destroy only during wartime.
            if current_t.nation_id and current_t.nation_id != probe.nation_id:
                a = min(probe.nation_id, current_t.nation_id)
                b = max(probe.nation_id, current_t.nation_id)
                war_row = db.query(Diplomacy).filter(
                    Diplomacy.nation_a == a,
                    Diplomacy.nation_b == b,
                    Diplomacy.status == "war",
                ).first()
                # Notify territory owner only on first entry into this nation's space.
                # Moving between territories of the same nation doesn't re-fire.
                if probe.last_detected_nation_id != current_t.nation_id:
                    db.add(Event(
                        type="foreign_probe_detected",
                        payload={
                            "probe_id": probe.id,
                            "probe_nation_id": probe.nation_id,
                            "territory_id": current_t.id,
                            "territory_nation_id": current_t.nation_id,
                            "node_key": current_t.node_key,
                            "at_war": war_row is not None,
                            "tick_at": tick_at.isoformat(),
                        },
                        scheduled_for=tick_at,
                        processed_at=tick_at,
                        status="processed",
                    ))
                    probe.last_detected_nation_id = current_t.nation_id
                if war_row:
                    probe.status = "destroyed"
                    db.add(Event(
                        type="probe_destroyed_in_enemy_territory",
                        payload={
                            "probe_id": probe.id,
                            "probe_nation_id": probe.nation_id,
                            "territory_id": current_t.id,
                            "territory_nation_id": current_t.nation_id,
                            "node_key": current_t.node_key,
                            "tick_at": tick_at.isoformat(),
                        },
                        scheduled_for=tick_at,
                        processed_at=tick_at,
                        status="processed",
                    ))
                    continue
            else:
                # Probe is in own or unclaimed space — reset so re-entry fires again.
                probe.last_detected_nation_id = None

            # Pre-generate nodes within vision radius before movement so the
            # probe's next step is guaranteed to exist in territory_by_key.
            pre_q, pre_r = _parse_key(current_t.node_key)
            for gdq in range(-PROBE_VISION_RADIUS, PROBE_VISION_RADIUS + 1):
                for gdr in range(-PROBE_VISION_RADIUS, PROBE_VISION_RADIUS + 1):
                    if _hex_dist(0, 0, gdq, gdr) > PROBE_VISION_RADIUS:
                        continue
                    vq, vr = pre_q + gdq, pre_r + gdr
                    vkey = f"{vq},{vr}"
                    if vkey not in territory_by_key:
                        new_t = generate_territory(vq, vr)
                        db.add(new_t)
                        db.flush()
                        territory_by_key[vkey] = new_t

            # Record that this probe physically visited its current tile.
            _record_visibility(probe.nation_id, current_t.id)

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
                        # Record visibility for the tile the probe just moved into.
                        _record_visibility(probe.nation_id, current_t.id)
                if dest_t and current_t.id == dest_t.id:
                    probe.status = "stationed"
                    probe.origin_territory = current_t.id
                    probe.destination_territory = None
                    probe.arrives_at = None
                    probe.departs_at = None

                    # Record probe data (richness) only for the destination tile.
                    if current_t.territory_type != "void":
                        existing_pd = db.query(ProbeData).filter(
                            ProbeData.territory_id == current_t.id,
                            ProbeData.discovered_by == probe.nation_id,
                        ).first()
                        if existing_pd:
                            existing_pd.mineral_richness = current_t.mineral_richness
                            existing_pd.fuel_richness = current_t.fuel_richness
                            existing_pd.discovered_at = tick_at
                        else:
                            db.add(ProbeData(
                                territory_id=current_t.id,
                                discovered_by=probe.nation_id,
                                mineral_richness=current_t.mineral_richness,
                                fuel_richness=current_t.fuel_richness,
                            ))

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
