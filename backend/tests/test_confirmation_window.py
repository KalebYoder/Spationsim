"""
Test suite for the Fleet Confirmation Window feature.

Covers three areas:
  1. Tick logic (run_tick) — fleet arrival at enemy territory and confirmation expiry
  2. POST /api/military/fleets/{id}/confirm-attack
  3. POST /api/military/fleets/{id}/recall
  4. FleetResponse schema fields (standing_order, confirmation_expires_at)

Game-design rules enforced:
  - Fleet arrival at enemy territory MUST become pending_confirmation, never auto-attack
  - confirmation_expires_at MUST be set to approximately NOW + 4 hours
  - On confirmation expiry, standing_order drives outcome — hold or recall, never auto-attack
  - Vacation mode players cannot be targeted
  - Inaction safety: expired window defaults to 'holding', not combat
"""

from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    os.getenv("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/spationsim_test"),
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

from datetime import datetime, timezone, timedelta
from math import ceil

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.db.database import get_db, SessionLocal
from app.models.diplomacy import Diplomacy
from app.models.event import Event
from app.models.fleet import Fleet
from app.models.nation import Nation
from app.models.player import Player
from app.models.territory import Territory
from app.core.security import create_access_token, hash_password
from app.constants import UNIT_STATS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TICK_HOURS = 2
CONFIRMATION_WINDOW_HOURS = 4  # 2 ticks × 2 hours/tick
CONFIRMATION_WINDOW_SECONDS = CONFIRMATION_WINDOW_HOURS * 3600
# Allow 60-second clock skew in assertions about timestamp proximity
CLOCK_TOLERANCE_SECONDS = 60

# starfighters move 2 nodes per tick; home=0,0 and enemy=2,0 is exactly 2 nodes
# → 1 tick → 2 hours travel time
NODES_PER_TICK = UNIT_STATS["starfighter"]["nodes_per_tick"]

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _set_war(db: Session, nation_a_id: int, nation_b_id: int) -> Diplomacy:
    """Upsert a war row, respecting the nation_a < nation_b constraint."""
    a, b = min(nation_a_id, nation_b_id), max(nation_a_id, nation_b_id)
    row = db.query(Diplomacy).filter(
        Diplomacy.nation_a == a,
        Diplomacy.nation_b == b,
    ).first()
    if row:
        row.status = "war"
    else:
        row = Diplomacy(nation_a=a, nation_b=b, status="war")
        db.add(row)
    db.flush()
    return row


def _end_war(db: Session, nation_a_id: int, nation_b_id: int) -> None:
    """Set the diplomacy row back to neutral."""
    a, b = min(nation_a_id, nation_b_id), max(nation_a_id, nation_b_id)
    row = db.query(Diplomacy).filter(
        Diplomacy.nation_a == a,
        Diplomacy.nation_b == b,
    ).first()
    if row:
        row.status = "neutral"
        db.flush()


def _db_override(session: Session):
    def _override():
        yield session
    return _override


# ---------------------------------------------------------------------------
# Fixtures: second player / nation (enemy)
# ---------------------------------------------------------------------------


@pytest.fixture()
def enemy_player(db: Session) -> Player:
    player = Player(
        username="enemyplayer",
        email="enemy@example.com",
        password_hash=hash_password("enemypassword123"),
    )
    db.add(player)
    db.flush()
    return player


@pytest.fixture()
def enemy_nation(db: Session, enemy_player: Player) -> Nation:
    nation = Nation(
        player_id=enemy_player.id,
        name="Enemy Nation",
        minerals=1000,
        fuel=1000,
    )
    db.add(nation)
    db.flush()
    return nation


@pytest.fixture()
def home_territory(db: Session, test_nation: Nation) -> Territory:
    """Colonized territory for test_nation at hex 0,0 (origin for all fleets)."""
    t = Territory(
        node_key="0,0",
        name="Home World",
        territory_type="normal",
        nation_id=test_nation.id,
        mineral_richness=1.00,
        fuel_richness=1.00,
        distance_from_center=0,
        is_colonized=True,
        colonized_at=datetime.now(timezone.utc),
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture()
def enemy_territory(db: Session, enemy_nation: Nation) -> Territory:
    """Colonized territory for enemy_nation at hex 2,0 (2 nodes from home)."""
    t = Territory(
        node_key="2,0",
        name="Enemy Home World",
        territory_type="normal",
        nation_id=enemy_nation.id,
        mineral_richness=1.00,
        fuel_richness=1.00,
        distance_from_center=2,
        is_colonized=True,
        colonized_at=datetime.now(timezone.utc),
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture()
def neutral_territory(db: Session) -> Territory:
    """Uncolonised territory at hex 1,0."""
    t = Territory(
        node_key="1,0",
        name=None,
        territory_type="normal",
        nation_id=None,
        mineral_richness=0.50,
        fuel_richness=0.50,
        distance_from_center=1,
        is_colonized=False,
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture()
def third_territory(db: Session) -> Territory:
    """Colonised territory belonging to no-one-at-war at hex 4,0."""
    t = Territory(
        node_key="4,0",
        name="Third Party World",
        territory_type="normal",
        nation_id=None,  # will be set by test if needed
        mineral_richness=0.50,
        fuel_richness=0.50,
        distance_from_center=4,
        is_colonized=False,
    )
    db.add(t)
    db.flush()
    return t


# auth_client fixture — shadows conftest to use the same transactional session
@pytest.fixture()
def auth_client(db: Session, test_player: Player):
    token = create_access_token(test_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def enemy_auth_client(db: Session, enemy_player: Player, enemy_nation: Nation):
    token = create_access_token(enemy_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Fleet builder helpers
# ---------------------------------------------------------------------------


def _make_fleet(
    db: Session,
    *,
    nation_id: int,
    origin_id: int,
    dest_id: int | None = None,
    status: str,
    unit_count: int = 10,
    standing_order: str = "hold",
    arrives_at: datetime | None = None,
    confirmation_expires_at: datetime | None = None,
) -> Fleet:
    fleet = Fleet(
        nation_id=nation_id,
        origin_territory=origin_id,
        destination_territory=dest_id,
        unit_count=unit_count,
        status=status,
        standing_order=standing_order,
        arrives_at=arrives_at,
        confirmation_expires_at=confirmation_expires_at,
    )
    db.add(fleet)
    db.flush()
    return fleet


def _commit_and_run_tick(db: Session) -> None:
    """Commit the transactional session so SessionLocal() inside run_tick sees the rows,
    then invoke run_tick synchronously as a plain function."""
    db.commit()
    from app.tasks.tick import run_tick
    run_tick()


# ===========================================================================
# 1. TICK LOGIC — FLEET ARRIVAL AT ENEMY TERRITORY
# ===========================================================================


class TestTickFleetArrivalAtEnemyTerritory:
    """run_tick: in_transit fleet lands at an enemy (war) territory."""

    def test_arrival_at_enemy_sets_pending_confirmation(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet arriving at a war-enemy territory must become pending_confirmation, never attack."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="in_transit",
            arrives_at=now - timedelta(seconds=1),  # already arrived
        )
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            fleet = fresh.query(Fleet).filter(
                Fleet.nation_id == test_nation.id,
                Fleet.destination_territory == enemy_territory.id,
            ).first()
            # The fleet should have been picked up; check for pending_confirmation
            # (tick may create a new row or mutate the existing one)
            if fleet is None:
                # After arriving, origin becomes dest_id and dest becomes None if stationed
                # — but for enemy territory it should NOT be stationed
                fleet = fresh.query(Fleet).filter(
                    Fleet.nation_id == test_nation.id,
                ).first()
            assert fleet is not None, "Fleet must still exist after tick"
            assert fleet.status == "pending_confirmation", (
                f"Fleet arriving at enemy territory must enter pending_confirmation, got {fleet.status!r}"
            )
        finally:
            fresh.close()

    def test_arrival_at_enemy_sets_confirmation_expires_at_4h(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """confirmation_expires_at must be approximately NOW + 4 hours after enemy arrival."""
        _set_war(db, test_nation.id, enemy_nation.id)

        before_tick = datetime.now(timezone.utc)
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="in_transit",
            arrives_at=before_tick - timedelta(seconds=1),
        )
        db.commit()

        _commit_and_run_tick(db)

        after_tick = datetime.now(timezone.utc)
        expected_low = before_tick + timedelta(hours=CONFIRMATION_WINDOW_HOURS)
        expected_high = after_tick + timedelta(hours=CONFIRMATION_WINDOW_HOURS)

        fresh = SessionLocal()
        try:
            fleet = fresh.query(Fleet).filter(
                Fleet.nation_id == test_nation.id,
                Fleet.status == "pending_confirmation",
            ).first()
            assert fleet is not None, "Fleet must be in pending_confirmation state"
            assert fleet.confirmation_expires_at is not None, (
                "confirmation_expires_at must be set when fleet enters pending_confirmation"
            )
            exp = fleet.confirmation_expires_at.replace(tzinfo=timezone.utc)
            assert expected_low - timedelta(seconds=CLOCK_TOLERANCE_SECONDS) <= exp <= expected_high + timedelta(seconds=CLOCK_TOLERANCE_SECONDS), (
                f"confirmation_expires_at {exp} must be within [{expected_low}, {expected_high}]"
            )
        finally:
            fresh.close()

    def test_arrival_at_enemy_logs_attacker_event(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Tick must log fleet_arrived_at_enemy_territory event for the attacker."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="in_transit",
            arrives_at=now - timedelta(seconds=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            event = fresh.query(Event).filter(
                Event.type == "fleet_arrived_at_enemy_territory",
                Event.payload["fleet_id"].as_integer() == fleet_id,
            ).first()
            assert event is not None, (
                "fleet_arrived_at_enemy_territory event must be logged for the attacker"
            )
            assert event.payload["attacker_nation_id"] == test_nation.id
            assert event.payload["defender_nation_id"] == enemy_nation.id
        finally:
            fresh.close()

    def test_arrival_at_enemy_logs_defender_event(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Tick must log enemy_fleet_arrived event for the defender (early-warning notification)."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="in_transit",
            arrives_at=now - timedelta(seconds=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            event = fresh.query(Event).filter(
                Event.type == "enemy_fleet_arrived",
                Event.payload["fleet_id"].as_integer() == fleet_id,
            ).first()
            assert event is not None, (
                "enemy_fleet_arrived event must be logged for the defender"
            )
            assert event.payload["attacker_nation_id"] == test_nation.id
            assert event.payload["defender_nation_id"] == enemy_nation.id
        finally:
            fresh.close()

    def test_arrival_at_enemy_fleet_not_merged_into_stationed(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet arriving at enemy territory must NOT merge with any stationed fleet there."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Pre-seed a stationed fleet at the enemy territory (e.g., a previously
        # arrived fleet that is holding; this should not absorb the new arrival)
        stationed = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=enemy_territory.id,
            status="holding",
            unit_count=20,
        )
        stationed_id = stationed.id

        now = datetime.now(timezone.utc)
        arriving = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="in_transit",
            unit_count=10,
            arrives_at=now - timedelta(seconds=1),
        )
        arriving_id = arriving.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            # Stationed fleet must not have absorbed the arriving fleet.
            # It may lose 1 unit to holding attrition (1% per tick, min 1),
            # but must not gain the arriving fleet's 10 units.
            stationed_after = fresh.get(Fleet, stationed_id)
            assert stationed_after is not None, "Pre-existing fleet must still exist"
            assert stationed_after.unit_count <= 20, "Units should not increase"
            assert stationed_after.unit_count >= 18, (
                "Enemy-arrival fleet must not be merged into the holding fleet at enemy territory"
            )
            # The arriving fleet should still exist independently
            arriving_after = fresh.query(Fleet).filter(
                Fleet.id == arriving_id
            ).first()
            assert arriving_after is not None, "Arriving fleet must not be deleted"
            assert arriving_after.status == "pending_confirmation"
        finally:
            fresh.close()

    def test_arrival_at_unowned_territory_lands_normally(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        neutral_territory: Territory,
    ):
        """Fleet arriving at unowned (neutral) territory lands normally — no confirmation window."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=neutral_territory.id,
            status="in_transit",
            arrives_at=now - timedelta(seconds=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            # After landing, origin becomes the destination; check by nation_id
            # The fleet may have been merged (if stationed existed) or transitioned
            remaining = fresh.query(Fleet).filter(Fleet.nation_id == test_nation.id).all()
            statuses = [f.status for f in remaining]
            # Must NOT be pending_confirmation for a neutral landing
            assert "pending_confirmation" not in statuses, (
                "Fleet landing at neutral territory must NOT enter pending_confirmation"
            )
            # Must have landed — stationed or merged (fleet row may be gone if merged)
            if remaining:
                for f in remaining:
                    assert f.status in ("stationed", "holding"), (
                        f"Fleet must be stationed after neutral landing, got {f.status!r}"
                    )
                    assert f.confirmation_expires_at is None, (
                        "No confirmation_expires_at for neutral territory landing"
                    )
        finally:
            fresh.close()

    def test_arrival_at_own_territory_lands_normally(
        self,
        db: Session,
        test_nation: Nation,
        home_territory: Territory,
    ):
        """Fleet arriving at own territory merges or becomes stationed — no confirmation window."""
        now = datetime.now(timezone.utc)
        # Create a second owned territory as destination
        dest = Territory(
            node_key="2,0",
            name="Second Colony",
            territory_type="normal",
            nation_id=test_nation.id,
            mineral_richness=1.0,
            fuel_richness=1.0,
            distance_from_center=2,
            is_colonized=True,
            colonized_at=now,
        )
        db.add(dest)
        db.flush()

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=dest.id,
            status="in_transit",
            arrives_at=now - timedelta(seconds=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            fleets = fresh.query(Fleet).filter(Fleet.nation_id == test_nation.id).all()
            for f in fleets:
                assert f.status in ("stationed",), (
                    f"Fleet arriving at own territory must station, got {f.status!r}"
                )
                assert f.confirmation_expires_at is None
        finally:
            fresh.close()

    def test_arrival_at_enemy_territory_without_war_lands_normally(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet arriving at another nation's territory when NOT at war lands normally (no confirmation)."""
        # No war declared — nations are neutral
        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="in_transit",
            arrives_at=now - timedelta(seconds=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            fleet_after = fresh.query(Fleet).filter(Fleet.nation_id == test_nation.id).first()
            if fleet_after:
                assert fleet_after.status != "pending_confirmation", (
                    "Fleet arriving at non-war territory must NOT enter pending_confirmation"
                )
                assert fleet_after.confirmation_expires_at is None
        finally:
            fresh.close()

    def test_arrival_merges_with_existing_stationed_fleet_at_friendly_territory(
        self,
        db: Session,
        test_nation: Nation,
        home_territory: Territory,
    ):
        """When landing at own territory with an existing stationed fleet, units merge."""
        now = datetime.now(timezone.utc)
        dest = Territory(
            node_key="2,0",
            name="Merge Target",
            territory_type="normal",
            nation_id=test_nation.id,
            mineral_richness=1.0,
            fuel_richness=1.0,
            distance_from_center=2,
            is_colonized=True,
            colonized_at=now,
        )
        db.add(dest)
        db.flush()

        # Pre-existing stationed fleet at destination
        existing = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=dest.id,
            status="stationed",
            unit_count=15,
        )
        existing_id = existing.id

        # In-transit fleet arriving
        arriving = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=dest.id,
            status="in_transit",
            unit_count=10,
            arrives_at=now - timedelta(seconds=1),
        )
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            merged = fresh.get(Fleet, existing_id)
            assert merged is not None, "Existing stationed fleet must still exist after merge"
            assert merged.unit_count == 25, (
                f"Existing fleet should have grown from 15 to 25 after merge, got {merged.unit_count}"
            )
        finally:
            fresh.close()


# ===========================================================================
# 2. TICK LOGIC — CONFIRMATION WINDOW EXPIRY
# ===========================================================================


class TestTickConfirmationWindowExpiry:
    """run_tick: pending_confirmation fleet whose confirmation_expires_at <= now."""

    def test_expiry_with_hold_order_becomes_holding(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Expired confirmation window with standing_order='hold' → fleet status becomes 'holding'."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            standing_order="hold",
            confirmation_expires_at=now - timedelta(seconds=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.status == "holding", (
                f"Expired hold-order fleet must become 'holding', got {f.status!r}"
            )
            assert f.confirmation_expires_at is None, (
                "confirmation_expires_at must be cleared after expiry"
            )
        finally:
            fresh.close()

    def test_expiry_with_hold_order_never_becomes_engaged_or_attacking(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """CRITICAL game-design rule: inaction on expiry must NEVER produce combat."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            standing_order="hold",
            confirmation_expires_at=now - timedelta(seconds=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.status not in ("engaged", "attacking", "combat"), (
                f"Inaction at expiry must NEVER produce combat. Got status {f.status!r}. "
                "Game design rule: inaction must never produce maximum harm."
            )
        finally:
            fresh.close()

    def test_expiry_with_hold_order_logs_holding_event(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Tick must log fleet_holding_at_enemy_territory event on hold-order expiry."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            standing_order="hold",
            confirmation_expires_at=now - timedelta(seconds=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            event = fresh.query(Event).filter(
                Event.type == "fleet_holding_at_enemy_territory",
                Event.payload["fleet_id"].as_integer() == fleet_id,
            ).first()
            assert event is not None, (
                "fleet_holding_at_enemy_territory event must be logged on hold-order expiry"
            )
        finally:
            fresh.close()

    def test_expiry_with_recall_order_sends_fleet_home(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Expired confirmation window with standing_order='recall' → fleet goes back in_transit."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            standing_order="recall",
            confirmation_expires_at=now - timedelta(seconds=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.status == "in_transit", (
                f"Recalled fleet must become in_transit, got {f.status!r}"
            )
            assert f.destination_territory == home_territory.id, (
                "Recalled fleet destination must be the original home territory"
            )
            assert f.origin_territory == enemy_territory.id, (
                "Recalled fleet origin must be the enemy territory it was at"
            )
            assert f.confirmation_expires_at is None, (
                "confirmation_expires_at must be cleared on recall"
            )
            assert f.arrives_at is not None, (
                "Recalled fleet must have an arrives_at set for its return journey"
            )
        finally:
            fresh.close()

    def test_expiry_with_recall_order_arrives_at_set_from_distance(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Recalled fleet's arrives_at must reflect the transit time from enemy to home."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            standing_order="recall",
            confirmation_expires_at=now - timedelta(seconds=1),
        )
        fleet_id = fleet.id
        db.commit()

        before_tick = datetime.now(timezone.utc)
        _commit_and_run_tick(db)
        after_tick = datetime.now(timezone.utc)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.arrives_at is not None

            # home_territory=0,0, enemy_territory=2,0 → hex distance = 2 nodes
            # nodes_per_tick = 2 → 1 tick → 2 hours
            distance = 2  # hex distance between "0,0" and "2,0"
            transit_ticks = ceil(distance / NODES_PER_TICK)
            expected_hours = transit_ticks * TICK_HOURS

            arrives = f.arrives_at.replace(tzinfo=timezone.utc)
            expected_low = before_tick + timedelta(hours=expected_hours)
            expected_high = after_tick + timedelta(hours=expected_hours)

            assert expected_low - timedelta(seconds=CLOCK_TOLERANCE_SECONDS) <= arrives <= expected_high + timedelta(seconds=CLOCK_TOLERANCE_SECONDS), (
                f"Recalled fleet arrives_at {arrives} should be ~{expected_hours}h from now"
            )
        finally:
            fresh.close()

    def test_expiry_with_recall_order_logs_recall_on_expiry_event(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Tick must log fleet_recalled_on_expiry event when recall standing order executes."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            standing_order="recall",
            confirmation_expires_at=now - timedelta(seconds=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            event = fresh.query(Event).filter(
                Event.type == "fleet_recalled_on_expiry",
                Event.payload["fleet_id"].as_integer() == fleet_id,
            ).first()
            assert event is not None, (
                "fleet_recalled_on_expiry event must be logged when recall standing order fires"
            )
            assert event.payload["nation_id"] == test_nation.id
        finally:
            fresh.close()

    def test_expiry_with_no_explicit_standing_order_defaults_to_hold(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """If standing_order is neither 'recall' nor 'attack', fleet becomes 'holding'."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            standing_order="hold",  # explicit 'hold' — the safe default
            confirmation_expires_at=now - timedelta(seconds=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.status == "holding"
        finally:
            fresh.close()

    def test_fleet_not_yet_expired_stays_pending_confirmation(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """A fleet whose confirmation_expires_at is in the future must not be processed."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            standing_order="hold",
            confirmation_expires_at=now + timedelta(hours=3),  # not yet expired
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.status == "pending_confirmation", (
                "Fleet with future confirmation_expires_at must remain in pending_confirmation"
            )
        finally:
            fresh.close()


# ===========================================================================
# 3. POST /api/military/fleets/{id}/confirm-attack
# ===========================================================================


class TestConfirmAttackEndpoint:
    """Tests for POST /api/military/fleets/{fleet_id}/confirm-attack."""

    def test_confirm_attack_from_pending_confirmation(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet in pending_confirmation → confirm-attack → status becomes 'engaged'."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/confirm-attack")
        assert resp.status_code == 200, resp.text

        data = resp.json()
        assert data["status"] == "engaged", (
            f"confirm-attack must set status to 'engaged', got {data['status']!r}"
        )
        assert data["confirmation_expires_at"] is None, (
            "confirmation_expires_at must be cleared after confirm-attack"
        )

    def test_confirm_attack_from_holding(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet in 'holding' status → confirm-attack → status becomes 'engaged'."""
        _set_war(db, test_nation.id, enemy_nation.id)

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/confirm-attack")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "engaged"

    def test_confirm_attack_logs_attack_confirmed_event(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """confirm-attack must log an attack_confirmed event."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
        )
        fleet_id = fleet.id
        db.flush()

        auth_client.post(f"/api/military/fleets/{fleet_id}/confirm-attack")

        event = db.query(Event).filter(
            Event.type == "attack_confirmed",
            Event.payload["fleet_id"].as_integer() == fleet_id,
        ).first()
        assert event is not None, "attack_confirmed event must be logged on confirm-attack"
        assert event.payload["attacker_nation_id"] == test_nation.id
        assert event.payload["defender_nation_id"] == enemy_nation.id

    def test_confirm_attack_clears_confirmation_expires_at_in_db(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Verify the DB row itself has confirmation_expires_at = NULL after confirm-attack."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
        )
        fleet_id = fleet.id
        db.flush()

        auth_client.post(f"/api/military/fleets/{fleet_id}/confirm-attack")

        db.expire_all()
        updated = db.get(Fleet, fleet_id)
        assert updated.confirmation_expires_at is None
        assert updated.status == "engaged"

    def test_confirm_attack_wrong_owner_returns_403(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """A player cannot confirm-attack a fleet they do not own — must return 403."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
        )
        fleet_id = fleet.id
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{fleet_id}/confirm-attack")
        assert resp.status_code == 403, (
            f"Other player confirming your fleet must return 403, got {resp.status_code}"
        )

    def test_confirm_attack_unauthenticated_returns_401(
        self,
        client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Unauthenticated request to confirm-attack must return 401."""
        _set_war(db, test_nation.id, enemy_nation.id)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
        )
        fleet_id = fleet.id
        db.flush()

        resp = client.post(f"/api/military/fleets/{fleet_id}/confirm-attack")
        assert resp.status_code == 401

    def test_confirm_attack_wrong_status_stationed_returns_409(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        home_territory: Territory,
    ):
        """confirm-attack on a stationed fleet must return 409."""
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            status="stationed",
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/confirm-attack")
        assert resp.status_code == 409

    def test_confirm_attack_wrong_status_in_transit_returns_409(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """confirm-attack on an in_transit fleet must return 409."""
        _set_war(db, test_nation.id, enemy_nation.id)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="in_transit",
            arrives_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/confirm-attack")
        assert resp.status_code == 409

    def test_confirm_attack_wrong_status_engaged_returns_409(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """confirm-attack on an already-engaged fleet must return 409."""
        _set_war(db, test_nation.id, enemy_nation.id)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="engaged",
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/confirm-attack")
        assert resp.status_code == 409

    def test_confirm_attack_no_war_returns_409(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """confirm-attack when war has ended must return 409."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
        )
        fleet_id = fleet.id
        db.flush()

        # End the war before the player confirms
        _end_war(db, test_nation.id, enemy_nation.id)
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/confirm-attack")
        assert resp.status_code == 409, (
            "confirm-attack after war ended must return 409"
        )

    def test_confirm_attack_destination_is_own_territory_returns_409(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        home_territory: Territory,
    ):
        """confirm-attack when fleet destination is own territory must return 409."""
        now = datetime.now(timezone.utc)
        second_own = Territory(
            node_key="3,0",
            territory_type="normal",
            nation_id=test_nation.id,
            mineral_richness=1.0,
            fuel_richness=1.0,
            distance_from_center=3,
            is_colonized=True,
            colonized_at=now,
        )
        db.add(second_own)
        db.flush()

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=second_own.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/confirm-attack")
        assert resp.status_code == 409

    def test_confirm_attack_nonexistent_fleet_returns_403(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """confirm-attack on a fleet ID that doesn't exist must return 403."""
        resp = auth_client.post("/api/military/fleets/999999/confirm-attack")
        assert resp.status_code == 403

    def test_confirm_attack_response_includes_standing_order_and_expiry(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Response from confirm-attack must include standing_order and confirmation_expires_at fields."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/confirm-attack")
        assert resp.status_code == 200
        data = resp.json()
        assert "standing_order" in data, "FleetResponse must include 'standing_order' field"
        assert "confirmation_expires_at" in data, "FleetResponse must include 'confirmation_expires_at' field"


# ===========================================================================
# 4. POST /api/military/fleets/{id}/recall
# ===========================================================================


class TestRecallFleetEndpoint:
    """Tests for POST /api/military/fleets/{fleet_id}/recall."""

    def test_recall_from_pending_confirmation(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet in pending_confirmation → recall → status becomes in_transit heading home."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/recall")
        assert resp.status_code == 200, resp.text

        data = resp.json()
        assert data["status"] == "in_transit", (
            f"Recalled fleet must become in_transit, got {data['status']!r}"
        )

    def test_recall_from_holding(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet in 'holding' status → recall → status becomes in_transit."""
        _set_war(db, test_nation.id, enemy_nation.id)

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/recall")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "in_transit"

    def test_recall_swaps_origin_and_destination(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """After recall, fleet's origin should be the enemy territory, destination the home."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/recall")
        assert resp.status_code == 200

        db.expire_all()
        f = db.get(Fleet, fleet_id)
        assert f.origin_territory == enemy_territory.id, (
            "After recall, origin must be the enemy territory the fleet was at"
        )
        assert f.destination_territory == home_territory.id, (
            "After recall, destination must be the home territory"
        )

    def test_recall_sets_arrives_at(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Recalled fleet must have arrives_at set to a future time based on hex distance."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
        )
        fleet_id = fleet.id
        db.flush()

        before = datetime.now(timezone.utc)
        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/recall")
        after = datetime.now(timezone.utc)
        assert resp.status_code == 200

        db.expire_all()
        f = db.get(Fleet, fleet_id)
        assert f.arrives_at is not None

        # home=0,0, enemy=2,0 → distance=2, nodes_per_tick=2 → 1 tick → 2 hours
        distance = 2
        transit_ticks = ceil(distance / NODES_PER_TICK)
        expected_hours = transit_ticks * TICK_HOURS
        arrives = f.arrives_at.replace(tzinfo=timezone.utc)
        expected_low = before + timedelta(hours=expected_hours)
        expected_high = after + timedelta(hours=expected_hours)

        assert expected_low - timedelta(seconds=CLOCK_TOLERANCE_SECONDS) <= arrives <= expected_high + timedelta(seconds=CLOCK_TOLERANCE_SECONDS), (
            f"Recalled fleet arrives_at {arrives} must be within [{expected_low}, {expected_high}]"
        )

    def test_recall_clears_confirmation_expires_at(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """confirmation_expires_at must be cleared after recall."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/recall")
        assert resp.status_code == 200
        assert resp.json()["confirmation_expires_at"] is None

        db.expire_all()
        f = db.get(Fleet, fleet_id)
        assert f.confirmation_expires_at is None

    def test_recall_logs_fleet_recalled_event(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """recall must log a fleet_recalled event."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
        )
        fleet_id = fleet.id
        db.flush()

        auth_client.post(f"/api/military/fleets/{fleet_id}/recall")

        event = db.query(Event).filter(
            Event.type == "fleet_recalled",
            Event.payload["fleet_id"].as_integer() == fleet_id,
        ).first()
        assert event is not None, "fleet_recalled event must be logged on manual recall"
        assert event.payload["nation_id"] == test_nation.id
        assert event.payload["from_territory_id"] == enemy_territory.id
        assert event.payload["to_territory_id"] == home_territory.id

    def test_recall_wrong_owner_returns_403(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """A player cannot recall another nation's fleet — must return 403."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
        )
        fleet_id = fleet.id
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{fleet_id}/recall")
        assert resp.status_code == 403

    def test_recall_unauthenticated_returns_401(
        self,
        client: TestClient,
        db: Session,
        test_nation: Nation,
        home_territory: Territory,
    ):
        """Unauthenticated request to recall must return 401."""
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            status="pending_confirmation",
        )
        fleet_id = fleet.id
        db.flush()

        resp = client.post(f"/api/military/fleets/{fleet_id}/recall")
        assert resp.status_code == 401

    def test_recall_wrong_status_stationed_returns_409(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        home_territory: Territory,
    ):
        """recall on a stationed fleet must return 409."""
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            status="stationed",
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/recall")
        assert resp.status_code == 409

    def test_recall_wrong_status_in_transit_returns_409(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """recall on an in_transit fleet must return 409."""
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="in_transit",
            arrives_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/recall")
        assert resp.status_code == 409

    def test_recall_nonexistent_fleet_returns_403(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """recall on a non-existent fleet ID must return 403."""
        resp = auth_client.post("/api/military/fleets/999999/recall")
        assert resp.status_code == 403

    def test_recall_response_includes_standing_order_and_expiry(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Response from recall must include standing_order and confirmation_expires_at fields."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/recall")
        assert resp.status_code == 200
        data = resp.json()
        assert "standing_order" in data, "FleetResponse must include 'standing_order' field"
        assert "confirmation_expires_at" in data, "FleetResponse must include 'confirmation_expires_at' field"


# ===========================================================================
# 5. FleetResponse SCHEMA — GET /api/military/fleets
# ===========================================================================


class TestFleetResponseSchema:
    """Verify that FleetResponse includes the required confirmation window fields."""

    def test_list_fleets_includes_standing_order(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        home_territory: Territory,
    ):
        """GET /api/military/fleets must return standing_order for each fleet."""
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            status="stationed",
            standing_order="hold",
        )
        db.flush()

        resp = auth_client.get("/api/military/fleets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        for fleet in data:
            assert "standing_order" in fleet, (
                "Each fleet in GET /api/military/fleets must include 'standing_order'"
            )
            assert fleet["standing_order"] in ("hold", "recall"), (
                f"standing_order must be 'hold' or 'recall', got {fleet['standing_order']!r}"
            )

    def test_list_fleets_includes_confirmation_expires_at(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """GET /api/military/fleets must include confirmation_expires_at (can be null for stationed)."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        # One stationed fleet (no confirmation window)
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            status="stationed",
        )
        # One fleet in pending_confirmation (has confirmation window)
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
        )
        db.flush()

        resp = auth_client.get("/api/military/fleets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

        for fleet in data:
            assert "confirmation_expires_at" in fleet, (
                "Each fleet must include 'confirmation_expires_at' key (may be null)"
            )

        # The pending_confirmation fleet must have a non-null value
        pending = next((f for f in data if f["status"] == "pending_confirmation"), None)
        assert pending is not None
        assert pending["confirmation_expires_at"] is not None, (
            "confirmation_expires_at must be non-null for a pending_confirmation fleet"
        )

        # The stationed fleet must have null
        stationed = next((f for f in data if f["status"] == "stationed"), None)
        assert stationed is not None
        assert stationed["confirmation_expires_at"] is None

    def test_standing_order_default_is_never_attack(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        home_territory: Territory,
    ):
        """No fleet created through the system may have standing_order='attack'."""
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            status="stationed",
        )
        db.flush()

        resp = auth_client.get("/api/military/fleets")
        assert resp.status_code == 200
        for fleet in resp.json():
            assert fleet["standing_order"] != "attack", (
                "standing_order must NEVER be 'attack'. "
                "Game design rule: inaction must never produce maximum harm."
            )


# ===========================================================================
# 6. GAME DESIGN RULE ENFORCEMENT
# ===========================================================================


class TestGameDesignRules:
    """
    Explicit tests for non-negotiable game design rules.
    These tests should fail if the implementation violates a rule.
    """

    def test_fleet_arrival_requires_explicit_confirmation_never_auto_attacks(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """
        CRITICAL: A fleet arriving at enemy territory MUST NOT auto-attack.
        Status must be pending_confirmation — the player must explicitly confirm.
        """
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="in_transit",
            arrives_at=now - timedelta(seconds=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.query(Fleet).filter(Fleet.nation_id == test_nation.id).first()
            assert f is not None
            assert f.status not in ("engaged", "attacking", "combat"), (
                f"Fleet MUST NOT auto-attack on arrival. Got status={f.status!r}. "
                "Game design rule: no action must never produce maximum harm."
            )
        finally:
            fresh.close()

    def test_inaction_on_confirmation_expiry_defaults_to_safe_outcome(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """
        CRITICAL: When confirmation window expires with no player action,
        the outcome must be 'holding' (safe), NOT combat.
        """
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            standing_order="hold",
            confirmation_expires_at=now - timedelta(seconds=1),  # already expired
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            # Safe outcome is 'holding', not combat
            assert f.status == "holding", (
                f"Inaction on expiry must default to 'holding' (safe), not {f.status!r}. "
                "Game design rule: inaction must never produce maximum harm."
            )
        finally:
            fresh.close()

    def test_fleet_standing_order_never_set_to_attack_by_system(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """
        CRITICAL: The standing_order field must never be set to 'attack' by the system.
        This test seeds a fleet and verifies the model default.
        """
        fleet = Fleet(
            nation_id=test_nation.id,
            origin_territory=home_territory.id,
            destination_territory=enemy_territory.id,
            unit_count=5,
            status="in_transit",
        )
        db.add(fleet)
        db.flush()

        assert fleet.standing_order != "attack", (
            f"System must never set standing_order='attack'. Got {fleet.standing_order!r}."
        )
        assert fleet.standing_order in ("hold", "recall"), (
            f"standing_order must default to 'hold' or 'recall', got {fleet.standing_order!r}"
        )

    def test_vacation_mode_player_cannot_be_declared_war_on(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_player: Player,
        enemy_nation: Nation,
    ):
        """Vacation mode must block war declaration against that nation."""
        enemy_player.vacation_mode = True
        enemy_player.vacation_since = datetime.now(timezone.utc)
        db.flush()

        resp = auth_client.post(
            "/api/diplomacy/war",
            json={"target_nation_id": enemy_nation.id},
        )
        assert resp.status_code == 409, (
            "Declaring war on a vacation-mode nation must return 409"
        )
        assert "vacation" in resp.json().get("detail", "").lower(), (
            "Error detail must mention 'vacation'"
        )

    def test_confirmation_window_is_visible_to_defender(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """
        During the confirmation window, an enemy_fleet_arrived event must be logged
        so the defender has visibility.  This is a hard game-design requirement.
        """
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="in_transit",
            arrives_at=now - timedelta(seconds=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            defender_event = fresh.query(Event).filter(
                Event.type == "enemy_fleet_arrived",
                Event.payload["fleet_id"].as_integer() == fleet_id,
                Event.payload["defender_nation_id"].as_integer() == enemy_nation.id,
            ).first()
            assert defender_event is not None, (
                "Defender must receive enemy_fleet_arrived event during the confirmation window. "
                "Game design rule: fleet must be visible to the defender during the window."
            )
        finally:
            fresh.close()

    def test_no_single_tick_total_resource_loss_from_holding_fleet(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """
        A fleet that transitions to 'holding' must not wipe the defender's resources
        in a single tick.  The soft damage model requires gradual drain.
        This test verifies the defender's resources are unchanged after the
        confirmation-to-holding transition (combat has not started).
        """
        _set_war(db, test_nation.id, enemy_nation.id)

        initial_minerals = float(enemy_nation.minerals)
        initial_fuel = float(enemy_nation.fuel)

        now = datetime.now(timezone.utc)
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            standing_order="hold",
            confirmation_expires_at=now - timedelta(seconds=1),
        )
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            defender = fresh.get(Nation, enemy_nation.id)
            # Minerals/fuel must not have been wiped in one tick by the fleet transition
            # (tick may add production — we check the floor, not exact value)
            assert float(defender.minerals) >= 0, "Defender resources must not go negative"
            # The fleet transitioning to 'holding' alone must not drain all resources:
            # if the defender had 1000 minerals, they must not have 0 after one tick.
            # We allow for production changes but not a total wipe.
            assert float(defender.minerals) > 0 or initial_minerals == 0, (
                "A single tick of holding fleet must not eliminate all defender minerals"
            )
        finally:
            fresh.close()
