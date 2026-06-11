"""
Test suite for two new tick.py behaviours related to war_pending status.

Change 1 — Fleet arrival quarantine during war_pending
------------------------------------------------------
When a fleet arrives at an enemy *planet* (territory_type != "void") while
diplomacy status is "war_pending", the tick must:
  - Set the fleet status = "holding"  (NOT "stationed")
  - Clear arrives_at and departs_at
  - Fire an enemy_fleet_holding_at_border event with the required payload fields

A fleet arriving at an enemy *void* territory during war_pending is NOT
quarantined — it lands normally as "stationed".

A fleet arriving at an enemy planet during full "war" is NOT quarantined —
it enters "pending_confirmation" as normal (already covered by
test_confirmation_window.py; included here as a regression guard).

Change 2 — War-activation sweep
--------------------------------
When the tick promotes a war_pending diplomacy row to "war", it must
immediately sweep for pre-staged fleets and put them in pending_confirmation.

  Case A (stationed fleet): fleet.origin_territory is the enemy territory.
  Case B (holding fleet):   fleet.destination_territory is the enemy territory.
  No double-sweep:          already-pending_confirmation fleets are not touched.
  Neutral fleets unaffected: fleets belonging to a third nation are not swept.
  Both events fired:        fleet_arrived_at_enemy_territory (attacker) and
                            enemy_fleet_arrived (defender), both with
                            reason="war_activation_sweep" in payload.
  Void exclusion note:      the sweep queries Territory.nation_id == defender_id
                            with no territory_type filter; both planet and void
                            territories owned by the defender are swept.
"""

from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    os.getenv("TEST_DATABASE_URL", "postgresql://spationsim:SpationDev2026@db/spationsim_test"),
)
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.diplomacy import Diplomacy
from app.models.event import Event
from app.models.fleet import Fleet
from app.models.nation import Nation
from app.models.player import Player
from app.models.territory import Territory
from app.core.security import hash_password

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIRMATION_WINDOW_HOURS = 4  # 2 ticks x 2 h/tick
CLOCK_TOLERANCE_SECONDS = 60


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _player(db: Session, username: str) -> Player:
    p = Player(
        username=username,
        email=f"{username}@test.example",
        password_hash=hash_password("pw"),
    )
    db.add(p)
    db.flush()
    return p


def _nation(db: Session, player_id: int, name: str | None = None) -> Nation:
    n = Nation(
        player_id=player_id,
        name=name or f"Nation-{player_id}",
        minerals=500,
        fuel=500,
        currency=0,
    )
    db.add(n)
    db.flush()
    return n


def _territory(
    db: Session,
    node_key: str,
    nation_id: int | None,
    *,
    territory_type: str = "normal",
    mineral_richness: float = 1.0,
    fuel_richness: float = 1.0,
    is_owned: bool = True,
) -> Territory:
    t = Territory(
        node_key=node_key,
        territory_type=territory_type,
        nation_id=nation_id,
        mineral_richness=mineral_richness,
        fuel_richness=fuel_richness,
        distance_from_center=1,
        is_owned=is_owned and nation_id is not None,
        owned_at=datetime.now(timezone.utc) if (is_owned and nation_id) else None,
    )
    db.add(t)
    db.flush()
    return t


def _void_territory(
    db: Session,
    node_key: str,
    nation_id: int | None = None,
) -> Territory:
    """A void territory — mineral_richness=0, fuel_richness=0, territory_type='void'."""
    return _territory(
        db,
        node_key,
        nation_id,
        territory_type="void",
        mineral_richness=0.0,
        fuel_richness=0.0,
        is_owned=True,
    )


def _diplomacy(
    db: Session,
    nation_a: Nation,
    nation_b: Nation,
    status: str,
    *,
    war_starts_at: datetime | None = None,
    declared_by: int | None = None,
) -> Diplomacy:
    a_id = min(nation_a.id, nation_b.id)
    b_id = max(nation_a.id, nation_b.id)
    row = Diplomacy(
        nation_a=a_id,
        nation_b=b_id,
        status=status,
        war_starts_at=war_starts_at,
        declared_by=declared_by,
    )
    db.add(row)
    db.flush()
    return row


def _fleet(
    db: Session,
    nation_id: int,
    origin_id: int,
    *,
    dest_id: int | None = None,
    status: str = "in_transit",
    unit_count: int = 20,
    arrives_at: datetime | None = None,
    standing_order: str = "hold",
) -> Fleet:
    f = Fleet(
        nation_id=nation_id,
        origin_territory=origin_id,
        destination_territory=dest_id,
        unit_count=unit_count,
        status=status,
        standing_order=standing_order,
        arrives_at=arrives_at,
    )
    db.add(f)
    db.flush()
    return f


def _run_tick(db: Session) -> None:
    """Commit so run_tick's own SessionLocal sees all rows, then run synchronously."""
    db.commit()
    from app.tasks.tick import run_tick
    run_tick()


# ---------------------------------------------------------------------------
# Shared nation/territory fixtures used across multiple test cases
# ---------------------------------------------------------------------------


@pytest.fixture()
def two_nations(db: Session):
    """Returns (attacker_nation, defender_nation, attacker_home, defender_planet)."""
    pa = _player(db, "attacker")
    pd = _player(db, "defender")
    na = _nation(db, pa.id, "AttackerNation")
    nd = _nation(db, pd.id, "DefenderNation")
    home = _territory(db, "0,0", na.id)
    planet = _territory(db, "2,0", nd.id)
    return na, nd, home, planet


# ===========================================================================
# Change 1 — Arrival quarantine during war_pending
# ===========================================================================


class TestWarPendingArrivalQuarantine:
    """Fleet arriving at an enemy planet while status is war_pending -> holding, not stationed."""

    def test_arrival_at_enemy_planet_during_war_pending_sets_holding(
        self,
        db: Session,
        two_nations,
    ):
        """Fleet landing on enemy planet during war_pending must become 'holding'."""
        na, nd, home, planet = two_nations
        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) + timedelta(hours=2))

        now = datetime.now(timezone.utc)
        fleet = _fleet(db, na.id, home.id, dest_id=planet.id,
                       arrives_at=now - timedelta(minutes=1))

        _run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet.id)
            assert f is not None, "Fleet must still exist after tick"
            assert f.status == "holding", (
                f"Fleet arriving at enemy planet during war_pending must become 'holding', "
                f"got {f.status!r}"
            )
        finally:
            fresh.close()

    def test_arrival_at_enemy_planet_during_war_pending_clears_arrives_at(
        self,
        db: Session,
        two_nations,
    ):
        """arrives_at must be cleared (NULL) when a fleet enters holding quarantine."""
        na, nd, home, planet = two_nations
        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) + timedelta(hours=2))

        now = datetime.now(timezone.utc)
        fleet = _fleet(db, na.id, home.id, dest_id=planet.id,
                       arrives_at=now - timedelta(minutes=1))

        _run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet.id)
            assert f is not None
            assert f.arrives_at is None, (
                "arrives_at must be cleared when fleet is quarantined to holding"
            )
        finally:
            fresh.close()

    def test_arrival_at_enemy_planet_during_war_pending_clears_departs_at(
        self,
        db: Session,
        two_nations,
    ):
        """departs_at must be cleared (NULL) when a fleet enters holding quarantine."""
        na, nd, home, planet = two_nations
        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) + timedelta(hours=2))

        now = datetime.now(timezone.utc)
        fleet = _fleet(db, na.id, home.id, dest_id=planet.id,
                       arrives_at=now - timedelta(minutes=1))

        _run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet.id)
            assert f is not None
            assert f.departs_at is None, (
                "departs_at must be cleared when fleet is quarantined to holding"
            )
        finally:
            fresh.close()

    def test_arrival_at_enemy_planet_during_war_pending_fires_border_event(
        self,
        db: Session,
        two_nations,
    ):
        """enemy_fleet_holding_at_border event must be fired with correct payload fields."""
        na, nd, home, planet = two_nations
        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) + timedelta(hours=2))

        now = datetime.now(timezone.utc)
        fleet = _fleet(db, na.id, home.id, dest_id=planet.id,
                       arrives_at=now - timedelta(minutes=1), unit_count=30)
        fleet_id = fleet.id

        _run_tick(db)

        fresh = SessionLocal()
        try:
            event = fresh.query(Event).filter(
                Event.type == "enemy_fleet_holding_at_border",
                Event.payload["fleet_id"].as_integer() == fleet_id,
            ).first()
            assert event is not None, (
                "enemy_fleet_holding_at_border event must be fired for war_pending quarantine"
            )
            assert event.payload["attacker_nation_id"] == na.id
            assert event.payload["defender_nation_id"] == nd.id
            assert event.payload["territory_id"] == planet.id
            assert event.payload["unit_count"] == 30
        finally:
            fresh.close()

    def test_arrival_at_enemy_void_during_war_pending_is_not_quarantined(
        self,
        db: Session,
    ):
        """Fleet arriving at an enemy void territory during war_pending lands normally (stationed)."""
        pa = _player(db, "attacker_v")
        pd = _player(db, "defender_v")
        na = _nation(db, pa.id, "AttackerVoid")
        nd = _nation(db, pd.id, "DefenderVoid")
        home = _territory(db, "0,1", na.id)
        void_t = _void_territory(db, "2,1", nd.id)

        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) + timedelta(hours=2))

        now = datetime.now(timezone.utc)
        fleet = _fleet(db, na.id, home.id, dest_id=void_t.id,
                       arrives_at=now - timedelta(minutes=1))
        fleet_id = fleet.id

        _run_tick(db)

        fresh = SessionLocal()
        try:
            # The fleet should have landed normally; look for any fleet for this nation.
            # A merge would delete the arriving fleet, so check all remaining fleets.
            fleets = fresh.query(Fleet).filter(Fleet.nation_id == na.id).all()
            for f in fleets:
                assert f.status == "stationed", (
                    f"Void territory during war_pending must land as stationed, got {f.status!r}"
                )
                assert f.status != "holding", (
                    "Arriving at void territory must NOT quarantine as holding"
                )

            # No border event must have been fired for this void landing
            events = fresh.query(Event).filter(
                Event.type == "enemy_fleet_holding_at_border",
                Event.payload["fleet_id"].as_integer() == fleet_id,
            ).all()
            assert len(events) == 0, (
                "enemy_fleet_holding_at_border must NOT fire for void territory landing"
            )
        finally:
            fresh.close()

    def test_arrival_at_enemy_planet_during_full_war_is_pending_confirmation(
        self,
        db: Session,
        two_nations,
    ):
        """Regression: fleet at enemy planet during active 'war' must become pending_confirmation,
        not holding. The war_pending quarantine code must not affect the full-war path."""
        na, nd, home, planet = two_nations
        _diplomacy(db, na, nd, "war", declared_by=na.id)

        now = datetime.now(timezone.utc)
        fleet = _fleet(db, na.id, home.id, dest_id=planet.id,
                       arrives_at=now - timedelta(minutes=1))
        fleet_id = fleet.id

        _run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.status == "pending_confirmation", (
                f"Fleet at enemy planet during active war must be pending_confirmation, "
                f"got {f.status!r}"
            )
            assert f.confirmation_expires_at is not None, (
                "confirmation_expires_at must be set for pending_confirmation fleet"
            )
        finally:
            fresh.close()

    def test_quarantined_fleet_does_not_fire_confirmation_events(
        self,
        db: Session,
        two_nations,
    ):
        """war_pending quarantine must NOT fire fleet_arrived_at_enemy_territory — that event
        is reserved for full-war (pending_confirmation) arrivals and the war-activation sweep."""
        na, nd, home, planet = two_nations
        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) + timedelta(hours=2))

        now = datetime.now(timezone.utc)
        fleet = _fleet(db, na.id, home.id, dest_id=planet.id,
                       arrives_at=now - timedelta(minutes=1))
        fleet_id = fleet.id

        _run_tick(db)

        fresh = SessionLocal()
        try:
            arrival_events = fresh.query(Event).filter(
                Event.type == "fleet_arrived_at_enemy_territory",
                Event.payload["fleet_id"].as_integer() == fleet_id,
            ).all()
            assert len(arrival_events) == 0, (
                "fleet_arrived_at_enemy_territory must NOT fire during war_pending quarantine; "
                "that event is fired by the war-activation sweep when war actually starts"
            )
        finally:
            fresh.close()


# ===========================================================================
# Change 2 — War-activation sweep
# ===========================================================================


class TestWarActivationSweep:
    """When war_pending promotes to war, pre-staged fleets enter pending_confirmation."""

    # -----------------------------------------------------------------------
    # Case A — stationed fleet on enemy territory
    # -----------------------------------------------------------------------

    def test_sweep_stationed_fleet_becomes_pending_confirmation(
        self,
        db: Session,
        two_nations,
    ):
        """A stationed fleet on an enemy territory when war activates must enter pending_confirmation."""
        na, nd, home, planet = two_nations

        # Staged fleet: stationed on the defender's territory (origin_territory = planet)
        staged = _fleet(db, na.id, planet.id, status="stationed", unit_count=25)

        # war_starts_at is in the past so this tick promotes it
        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) - timedelta(hours=1),
                   declared_by=na.id)

        _run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, staged.id)
            assert f is not None, "Staged fleet must still exist after war activation"
            assert f.status == "pending_confirmation", (
                f"Stationed fleet on enemy territory must enter pending_confirmation on war "
                f"activation, got {f.status!r}"
            )
        finally:
            fresh.close()

    def test_sweep_stationed_fleet_sets_confirmation_expires_at_4h(
        self,
        db: Session,
        two_nations,
    ):
        """confirmation_expires_at must be approximately tick_at + 4 hours."""
        na, nd, home, planet = two_nations
        staged = _fleet(db, na.id, planet.id, status="stationed", unit_count=10)
        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) - timedelta(hours=1),
                   declared_by=na.id)

        before = datetime.now(timezone.utc)
        _run_tick(db)
        after = datetime.now(timezone.utc)

        expected_low = before + timedelta(hours=CONFIRMATION_WINDOW_HOURS)
        expected_high = after + timedelta(hours=CONFIRMATION_WINDOW_HOURS)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, staged.id)
            assert f is not None
            assert f.confirmation_expires_at is not None, (
                "confirmation_expires_at must be set by the war-activation sweep"
            )
            exp = f.confirmation_expires_at.replace(tzinfo=timezone.utc)
            assert (
                expected_low - timedelta(seconds=CLOCK_TOLERANCE_SECONDS)
                <= exp
                <= expected_high + timedelta(seconds=CLOCK_TOLERANCE_SECONDS)
            ), (
                f"confirmation_expires_at {exp} must be approximately tick_at + 4 hours, "
                f"expected window [{expected_low}, {expected_high}]"
            )
        finally:
            fresh.close()

    def test_sweep_stationed_fleet_sets_destination_territory(
        self,
        db: Session,
        two_nations,
    ):
        """Sweep must set destination_territory on the converted stationed fleet."""
        na, nd, home, planet = two_nations
        staged = _fleet(db, na.id, planet.id, status="stationed", unit_count=10)
        # Stationed fleets have origin = parking spot, destination = None
        assert staged.destination_territory is None

        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) - timedelta(hours=1),
                   declared_by=na.id)

        _run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, staged.id)
            assert f is not None
            assert f.destination_territory == planet.id, (
                "Sweep must set destination_territory to the enemy territory where the fleet is parked"
            )
        finally:
            fresh.close()

    def test_sweep_stationed_fleet_fires_attacker_event(
        self,
        db: Session,
        two_nations,
    ):
        """Sweep must fire fleet_arrived_at_enemy_territory with reason=war_activation_sweep."""
        na, nd, home, planet = two_nations
        staged = _fleet(db, na.id, planet.id, status="stationed", unit_count=10)
        staged_id = staged.id

        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) - timedelta(hours=1),
                   declared_by=na.id)

        _run_tick(db)

        fresh = SessionLocal()
        try:
            # Filter by fleet_id first; verify reason field in Python to avoid
            # SQLAlchemy JSONB string cast compatibility concerns.
            events = fresh.query(Event).filter(
                Event.type == "fleet_arrived_at_enemy_territory",
                Event.payload["fleet_id"].as_integer() == staged_id,
            ).all()
            sweep_event = next(
                (e for e in events if e.payload.get("reason") == "war_activation_sweep"),
                None,
            )
            assert sweep_event is not None, (
                "fleet_arrived_at_enemy_territory with reason=war_activation_sweep must be fired "
                "for the attacker when sweep converts a stationed fleet"
            )
            assert sweep_event.payload["attacker_nation_id"] == na.id
            assert sweep_event.payload["defender_nation_id"] == nd.id
            assert sweep_event.payload["territory_id"] == planet.id
        finally:
            fresh.close()

    def test_sweep_stationed_fleet_fires_defender_event(
        self,
        db: Session,
        two_nations,
    ):
        """Sweep must fire enemy_fleet_arrived with reason=war_activation_sweep for the defender."""
        na, nd, home, planet = two_nations
        staged = _fleet(db, na.id, planet.id, status="stationed", unit_count=10)
        staged_id = staged.id

        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) - timedelta(hours=1),
                   declared_by=na.id)

        _run_tick(db)

        fresh = SessionLocal()
        try:
            events = fresh.query(Event).filter(
                Event.type == "enemy_fleet_arrived",
                Event.payload["fleet_id"].as_integer() == staged_id,
            ).all()
            sweep_event = next(
                (e for e in events if e.payload.get("reason") == "war_activation_sweep"),
                None,
            )
            assert sweep_event is not None, (
                "enemy_fleet_arrived with reason=war_activation_sweep must be fired "
                "for the defender when sweep converts a stationed fleet"
            )
            assert sweep_event.payload["attacker_nation_id"] == na.id
            assert sweep_event.payload["defender_nation_id"] == nd.id
        finally:
            fresh.close()

    # -----------------------------------------------------------------------
    # Case B — holding fleet at enemy territory (from prior war_pending quarantine)
    # -----------------------------------------------------------------------

    def test_sweep_holding_fleet_becomes_pending_confirmation(
        self,
        db: Session,
        two_nations,
    ):
        """A holding fleet whose destination_territory is an enemy territory must enter
        pending_confirmation when war activates."""
        na, nd, home, planet = two_nations

        # Simulate a fleet previously quarantined via war_pending arrival:
        # status=holding, destination_territory=enemy planet
        quarantined = _fleet(db, na.id, home.id, dest_id=planet.id,
                             status="holding", unit_count=15)

        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) - timedelta(hours=1),
                   declared_by=na.id)

        _run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, quarantined.id)
            assert f is not None
            assert f.status == "pending_confirmation", (
                f"Holding fleet at enemy territory must enter pending_confirmation on war "
                f"activation, got {f.status!r}"
            )
        finally:
            fresh.close()

    def test_sweep_holding_fleet_sets_confirmation_expires_at_4h(
        self,
        db: Session,
        two_nations,
    ):
        """confirmation_expires_at must be approximately tick_at + 4 hours for holding -> sweep."""
        na, nd, home, planet = two_nations
        quarantined = _fleet(db, na.id, home.id, dest_id=planet.id,
                             status="holding", unit_count=15)

        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) - timedelta(hours=1),
                   declared_by=na.id)

        before = datetime.now(timezone.utc)
        _run_tick(db)
        after = datetime.now(timezone.utc)

        expected_low = before + timedelta(hours=CONFIRMATION_WINDOW_HOURS)
        expected_high = after + timedelta(hours=CONFIRMATION_WINDOW_HOURS)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, quarantined.id)
            assert f is not None
            assert f.confirmation_expires_at is not None
            exp = f.confirmation_expires_at.replace(tzinfo=timezone.utc)
            assert (
                expected_low - timedelta(seconds=CLOCK_TOLERANCE_SECONDS)
                <= exp
                <= expected_high + timedelta(seconds=CLOCK_TOLERANCE_SECONDS)
            ), (
                f"confirmation_expires_at {exp} out of expected window for holding fleet sweep"
            )
        finally:
            fresh.close()

    def test_sweep_holding_fleet_fires_attacker_and_defender_events(
        self,
        db: Session,
        two_nations,
    ):
        """Both fleet_arrived_at_enemy_territory and enemy_fleet_arrived must fire for the
        holding -> pending_confirmation conversion, both with reason=war_activation_sweep."""
        na, nd, home, planet = two_nations
        quarantined = _fleet(db, na.id, home.id, dest_id=planet.id,
                             status="holding", unit_count=15)
        q_id = quarantined.id

        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) - timedelta(hours=1),
                   declared_by=na.id)

        _run_tick(db)

        fresh = SessionLocal()
        try:
            atk_events = fresh.query(Event).filter(
                Event.type == "fleet_arrived_at_enemy_territory",
                Event.payload["fleet_id"].as_integer() == q_id,
            ).all()
            def_events = fresh.query(Event).filter(
                Event.type == "enemy_fleet_arrived",
                Event.payload["fleet_id"].as_integer() == q_id,
            ).all()

            atk_sweep = next(
                (e for e in atk_events if e.payload.get("reason") == "war_activation_sweep"),
                None,
            )
            def_sweep = next(
                (e for e in def_events if e.payload.get("reason") == "war_activation_sweep"),
                None,
            )

            assert atk_sweep is not None, (
                "fleet_arrived_at_enemy_territory (war_activation_sweep) must fire for "
                "holding fleet converted by sweep"
            )
            assert def_sweep is not None, (
                "enemy_fleet_arrived (war_activation_sweep) must fire for "
                "holding fleet converted by sweep"
            )
        finally:
            fresh.close()

    # -----------------------------------------------------------------------
    # No double-sweep
    # -----------------------------------------------------------------------

    def test_sweep_does_not_touch_already_pending_confirmation_fleet(
        self,
        db: Session,
        two_nations,
    ):
        """A fleet already in pending_confirmation must not be modified by the sweep."""
        na, nd, home, planet = two_nations

        now = datetime.now(timezone.utc)
        original_expiry = now + timedelta(hours=3, minutes=30)
        already_pending = _fleet(
            db, na.id, home.id, dest_id=planet.id, status="pending_confirmation", unit_count=10
        )
        already_pending.confirmation_expires_at = original_expiry
        db.flush()
        pending_id = already_pending.id

        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) - timedelta(hours=1),
                   declared_by=na.id)

        _run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, pending_id)
            assert f is not None
            assert f.status == "pending_confirmation", (
                "Already-pending_confirmation fleet must not be touched by the sweep"
            )
            # The expiry must not have been reset to a later tick_at + 4h value.
            if f.confirmation_expires_at is not None:
                exp = f.confirmation_expires_at.replace(tzinfo=timezone.utc)
                assert exp <= original_expiry + timedelta(seconds=CLOCK_TOLERANCE_SECONDS), (
                    "Sweep must not reset/extend confirmation_expires_at on an already-pending fleet"
                )
        finally:
            fresh.close()

    # -----------------------------------------------------------------------
    # Neutral fleets unaffected
    # -----------------------------------------------------------------------

    def test_sweep_does_not_touch_neutral_nation_fleet(
        self,
        db: Session,
    ):
        """A fleet from a third (neutral) nation parked on either warring nation's territory
        must not be converted to pending_confirmation by the war-activation sweep."""
        pa = _player(db, "attk_n")
        pd = _player(db, "defn_n")
        pn = _player(db, "neutral_n")
        na = _nation(db, pa.id, "AttackerN")
        nd = _nation(db, pd.id, "DefenderN")
        nn = _nation(db, pn.id, "NeutralN")

        _territory(db, "0,2", na.id)
        home_d = _territory(db, "2,2", nd.id)
        _territory(db, "4,2", nn.id)

        # Neutral fleet stationed on the defender's territory
        neutral_fleet = _fleet(db, nn.id, home_d.id, status="stationed", unit_count=5)
        neutral_id = neutral_fleet.id

        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) - timedelta(hours=1),
                   declared_by=na.id)

        _run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, neutral_id)
            assert f is not None, "Neutral fleet must still exist"
            assert f.status == "stationed", (
                f"Neutral fleet must remain stationed after war activation, got {f.status!r}"
            )
            assert f.confirmation_expires_at is None, (
                "Neutral fleet must not receive a confirmation_expires_at from the sweep"
            )
        finally:
            fresh.close()

    # -----------------------------------------------------------------------
    # war_pending that has NOT yet expired is not promoted
    # -----------------------------------------------------------------------

    def test_war_pending_not_yet_expired_does_not_promote(
        self,
        db: Session,
        two_nations,
    ):
        """If war_starts_at is still in the future, the row must stay war_pending this tick
        and the sweep must NOT run."""
        na, nd, home, planet = two_nations

        staged = _fleet(db, na.id, planet.id, status="stationed", unit_count=10)

        # war_starts_at is FUTURE — not yet due
        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) + timedelta(hours=3),
                   declared_by=na.id)

        _run_tick(db)

        fresh = SessionLocal()
        try:
            diplo = fresh.query(Diplomacy).filter(
                Diplomacy.nation_a == min(na.id, nd.id),
                Diplomacy.nation_b == max(na.id, nd.id),
            ).first()
            assert diplo is not None
            assert diplo.status == "war_pending", (
                "Diplomacy row with future war_starts_at must NOT be promoted this tick"
            )

            f = fresh.get(Fleet, staged.id)
            assert f is not None
            assert f.status == "stationed", (
                "Staged fleet must not be swept when war has not yet activated"
            )
        finally:
            fresh.close()

    # -----------------------------------------------------------------------
    # Sweep applies to defender's territories regardless of territory_type
    # -----------------------------------------------------------------------

    def test_sweep_applies_to_fleet_on_enemy_void_territory(
        self,
        db: Session,
    ):
        """The war-activation sweep queries Territory.nation_id == defender_id with no
        territory_type filter. A fleet stationed on an enemy void territory must also be swept
        to pending_confirmation when war activates."""
        pa = _player(db, "attk_void2")
        pd = _player(db, "defn_void2")
        na = _nation(db, pa.id, "AttackerVoid2")
        nd = _nation(db, pd.id, "DefenderVoid2")

        _territory(db, "0,3", na.id)
        void_t = _void_territory(db, "2,3", nd.id)

        staged = _fleet(db, na.id, void_t.id, status="stationed", unit_count=10)
        staged_id = staged.id

        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) - timedelta(hours=1),
                   declared_by=na.id)

        _run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, staged_id)
            assert f is not None
            assert f.status == "pending_confirmation", (
                "Sweep must convert stationed fleet at enemy void territory to "
                f"pending_confirmation, got {f.status!r}"
            )
        finally:
            fresh.close()

    # -----------------------------------------------------------------------
    # war_started event is fired on promotion
    # -----------------------------------------------------------------------

    def test_war_activation_fires_war_started_event(
        self,
        db: Session,
        two_nations,
    ):
        """When war_pending promotes to war, a war_started event must be logged."""
        na, nd, home, planet = two_nations
        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) - timedelta(hours=1),
                   declared_by=na.id)

        _run_tick(db)

        fresh = SessionLocal()
        try:
            event = fresh.query(Event).filter(Event.type == "war_started").first()
            assert event is not None, (
                "war_started event must be logged when war_pending is promoted to war"
            )
            pair = {event.payload["nation_a"], event.payload["nation_b"]}
            assert pair == {na.id, nd.id}
        finally:
            fresh.close()

    def test_war_activation_promotes_diplomacy_status_to_war(
        self,
        db: Session,
        two_nations,
    ):
        """Diplomacy row status must change from war_pending to war after promotion."""
        na, nd, home, planet = two_nations
        _diplomacy(db, na, nd, "war_pending",
                   war_starts_at=datetime.now(timezone.utc) - timedelta(hours=1),
                   declared_by=na.id)

        _run_tick(db)

        fresh = SessionLocal()
        try:
            diplo = fresh.query(Diplomacy).filter(
                Diplomacy.nation_a == min(na.id, nd.id),
                Diplomacy.nation_b == max(na.id, nd.id),
            ).first()
            assert diplo is not None
            assert diplo.status == "war", (
                f"Diplomacy row must be promoted to 'war', got {diplo.status!r}"
            )
            assert diplo.war_starts_at is None, (
                "war_starts_at must be cleared after promotion"
            )
            assert diplo.war_started_at is not None, (
                "war_started_at must be set after promotion"
            )
        finally:
            fresh.close()
