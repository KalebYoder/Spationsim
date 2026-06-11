"""
Test suite for the raid_fleet ResourceLog bug fix.

Bug: POST /api/military/fleets/{fleet_id}/raid transfers resources between nations
and writes a raid_applied Event, but writes no ResourceLog rows.

Fix under test: after a successful raid, exactly two ResourceLog rows must be
inserted —
  1. A NEGATIVE row for the defender (minerals/fuel/currency_delta all <= 0)
  2. A POSITIVE row for the attacker (minerals/fuel/currency_delta all >= 0)

Both rows must have tick_at set to approximately NOW at the moment the raid fires.

These tests will FAIL until the fix is implemented.  They act as a regression
guard against the missing-audit-trail bug.
"""

from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://spationsim:SpationDev2026@db/spationsim_test",
    ),
)
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.db.database import get_db
from app.models.diplomacy import Diplomacy
from app.models.event import Event
from app.models.fleet import Fleet
from app.models.nation import Nation
from app.models.player import Player
from app.models.resource_log import ResourceLog
from app.models.infrastructure import Infrastructure
from app.models.territory import Territory
from app.core.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Tolerance constants
# ---------------------------------------------------------------------------

# ResourceLog.tick_at must be within this many seconds of "now" when the
# endpoint executes — tight enough to catch wrong timestamps, loose enough
# not to flap in slow CI.
TICK_AT_TOLERANCE_SECONDS = 10

# A unit count large enough that random.uniform(0.5 * fp, 1.5 * fp) * units
# will always produce non-zero theft even with no seeded stockpile padding.
# UNIT_STATS["starfighter"]["firepower"] == 2, so firepower = 10 * 2 = 20.
# With defender having 500 of each resource, min steal is 0.5 * 20 = 10.
FLEET_UNITS = 10


# ---------------------------------------------------------------------------
# Helpers — shared fixture construction utilities
# ---------------------------------------------------------------------------

def _db_override(session: Session):
    def _inner():
        yield session
    return _inner


def _set_war(db: Session, nation_a_id: int, nation_b_id: int) -> Diplomacy:
    """Upsert a diplomacy row with status='war', respecting nation_a < nation_b."""
    a, b = min(nation_a_id, nation_b_id), max(nation_a_id, nation_b_id)
    row = (
        db.query(Diplomacy)
        .filter(Diplomacy.nation_a == a, Diplomacy.nation_b == b)
        .first()
    )
    if row:
        row.status = "war"
    else:
        row = Diplomacy(nation_a=a, nation_b=b, status="war")
        db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Module-level fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def attacker_player(db: Session) -> Player:
    player = Player(
        username="attacker",
        email="attacker@example.com",
        password_hash=hash_password("password123"),
    )
    db.add(player)
    db.flush()
    return player


@pytest.fixture()
def attacker_nation(db: Session, attacker_player: Player) -> Nation:
    nation = Nation(
        player_id=attacker_player.id,
        name="Attacker Nation",
        minerals=100.00,
        fuel=100.00,
        currency=100.00,
    )
    db.add(nation)
    db.flush()
    return nation


@pytest.fixture()
def defender_player(db: Session) -> Player:
    player = Player(
        username="defender",
        email="defender@example.com",
        password_hash=hash_password("password456"),
    )
    db.add(player)
    db.flush()
    return player


@pytest.fixture()
def defender_nation(db: Session, defender_player: Player) -> Nation:
    # Seed large stockpiles so min theft (0.5 * firepower * units = 0.5 * 2 * 10 = 10)
    # is guaranteed to produce non-zero deltas regardless of random.uniform outcome.
    nation = Nation(
        player_id=defender_player.id,
        name="Defender Nation",
        minerals=500.00,
        fuel=500.00,
        currency=500.00,
    )
    db.add(nation)
    db.flush()
    return nation


@pytest.fixture()
def attacker_territory(db: Session, attacker_nation: Nation) -> Territory:
    t = Territory(
        node_key="0,0",
        name="Attacker Home",
        territory_type="normal",
        nation_id=attacker_nation.id,
        mineral_richness=1.00,
        fuel_richness=1.00,
        distance_from_center=0,
        is_owned=True,
        owned_at=datetime.now(timezone.utc),
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture()
def defender_territory(db: Session, defender_nation: Nation) -> Territory:
    t = Territory(
        node_key="2,0",
        name="Defender Home",
        territory_type="normal",
        nation_id=defender_nation.id,
        mineral_richness=1.00,
        fuel_richness=1.00,
        distance_from_center=2,
        is_owned=True,
        owned_at=datetime.now(timezone.utc),
    )
    db.add(t)
    db.flush()
    # Active mine and refinery so the production-based raid cap is non-zero.
    # richness=1.0 → mine=5 minerals/tick, refinery=5 fuel/tick, 60 currency/tick.
    # Cap = RAID_PRODUCTION_TICKS_CAP(3) × production = 15 / 15 / 180 per raid.
    db.add(Infrastructure(territory_id=t.id, type="mine", level=1, status="active"))
    db.add(Infrastructure(territory_id=t.id, type="refinery", level=1, status="active"))
    db.flush()
    return t


@pytest.fixture()
def raid_ready_fleet(
    db: Session,
    attacker_nation: Nation,
    attacker_territory: Territory,
    defender_territory: Territory,
) -> Fleet:
    """
    A fleet in 'post_battle_choice' state sitting at the defender's territory,
    which is the required precondition for the raid endpoint.
    """
    fleet = Fleet(
        nation_id=attacker_nation.id,
        origin_territory=attacker_territory.id,
        destination_territory=defender_territory.id,
        unit_count=FLEET_UNITS,
        status="post_battle_choice",
        standing_order="hold",
        departs_at=datetime.now(timezone.utc) - timedelta(hours=4),
        arrives_at=datetime.now(timezone.utc) - timedelta(hours=2),
        confirmation_expires_at=None,
    )
    db.add(fleet)
    db.flush()
    return fleet


@pytest.fixture()
def auth_client(db: Session, attacker_player: Player, attacker_nation: Nation):
    """Authenticated client for the attacker, wired to the same transactional session."""
    token = create_access_token(attacker_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def unauthenticated_client(db: Session):
    """Client with no session cookie."""
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper: execute a raid and return the response, asserting it succeeded.
# ---------------------------------------------------------------------------

def _do_raid(auth_client: TestClient, fleet_id: int):
    resp = auth_client.post(f"/api/military/fleets/{fleet_id}/raid")
    assert resp.status_code == 200, (
        f"Expected 200 from raid endpoint, got {resp.status_code}: {resp.text}"
    )
    return resp


# ===========================================================================
# Test 1 — Defender ResourceLog row: negative deltas
# ===========================================================================

class TestDefenderResourceLogNegative:
    """
    After a successful raid, the defender's nation must have a ResourceLog row
    with negative minerals_delta, fuel_delta, and currency_delta equal to the
    amounts stolen.
    """

    def test_defender_resource_log_row_exists(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """A ResourceLog row must be created for the defender after a raid."""
        _set_war(db, attacker_nation.id, defender_nation.id)
        before = datetime.now(timezone.utc) - timedelta(seconds=1)

        _do_raid(auth_client, raid_ready_fleet.id)

        rows = (
            db.query(ResourceLog)
            .filter(ResourceLog.nation_id == defender_nation.id)
            .all()
        )
        assert len(rows) >= 1, (
            "Defender must have at least one ResourceLog row after a raid. "
            "The raid_fleet endpoint is missing ResourceLog insertion for the defender."
        )

    def test_defender_resource_log_minerals_delta_is_negative(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """Defender's ResourceLog minerals_delta must be negative (resources were stolen)."""
        _set_war(db, attacker_nation.id, defender_nation.id)
        _do_raid(auth_client, raid_ready_fleet.id)

        row = (
            db.query(ResourceLog)
            .filter(ResourceLog.nation_id == defender_nation.id)
            .order_by(ResourceLog.id.desc())
            .first()
        )
        assert row is not None, "Defender ResourceLog row is missing"
        assert float(row.minerals_delta) < 0, (
            f"Defender minerals_delta must be negative; got {row.minerals_delta}"
        )

    def test_defender_resource_log_fuel_delta_is_negative(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """Defender's ResourceLog fuel_delta must be negative."""
        _set_war(db, attacker_nation.id, defender_nation.id)
        _do_raid(auth_client, raid_ready_fleet.id)

        row = (
            db.query(ResourceLog)
            .filter(ResourceLog.nation_id == defender_nation.id)
            .order_by(ResourceLog.id.desc())
            .first()
        )
        assert row is not None, "Defender ResourceLog row is missing"
        assert float(row.fuel_delta) < 0, (
            f"Defender fuel_delta must be negative; got {row.fuel_delta}"
        )

    def test_defender_resource_log_currency_delta_is_negative(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """Defender's ResourceLog currency_delta must be negative."""
        _set_war(db, attacker_nation.id, defender_nation.id)
        _do_raid(auth_client, raid_ready_fleet.id)

        row = (
            db.query(ResourceLog)
            .filter(ResourceLog.nation_id == defender_nation.id)
            .order_by(ResourceLog.id.desc())
            .first()
        )
        assert row is not None, "Defender ResourceLog row is missing"
        assert float(row.currency_delta) < 0, (
            f"Defender currency_delta must be negative; got {row.currency_delta}"
        )

    def test_defender_resource_log_deltas_match_stolen_amounts(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """
        The absolute value of the defender's deltas must match the amounts
        actually stolen (i.e., the reduction in the defender's stockpiles).
        """
        _set_war(db, attacker_nation.id, defender_nation.id)

        minerals_before = float(defender_nation.minerals)
        fuel_before = float(defender_nation.fuel)
        currency_before = float(defender_nation.currency)

        _do_raid(auth_client, raid_ready_fleet.id)

        db.refresh(defender_nation)
        minerals_stolen = minerals_before - float(defender_nation.minerals)
        fuel_stolen = fuel_before - float(defender_nation.fuel)
        currency_stolen = currency_before - float(defender_nation.currency)

        row = (
            db.query(ResourceLog)
            .filter(ResourceLog.nation_id == defender_nation.id)
            .order_by(ResourceLog.id.desc())
            .first()
        )
        assert row is not None, "Defender ResourceLog row is missing"

        assert abs(float(row.minerals_delta)) == pytest.approx(minerals_stolen, abs=0.01), (
            f"Defender minerals_delta magnitude {abs(float(row.minerals_delta))} "
            f"does not match actual theft {minerals_stolen}"
        )
        assert abs(float(row.fuel_delta)) == pytest.approx(fuel_stolen, abs=0.01), (
            f"Defender fuel_delta magnitude {abs(float(row.fuel_delta))} "
            f"does not match actual theft {fuel_stolen}"
        )
        assert abs(float(row.currency_delta)) == pytest.approx(currency_stolen, abs=0.01), (
            f"Defender currency_delta magnitude {abs(float(row.currency_delta))} "
            f"does not match actual theft {currency_stolen}"
        )

    def test_defender_resource_log_tick_at_is_now(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """
        Defender's ResourceLog tick_at must be approximately the current UTC
        time at the moment the raid executes (within TICK_AT_TOLERANCE_SECONDS).
        """
        _set_war(db, attacker_nation.id, defender_nation.id)
        before = datetime.now(timezone.utc)
        _do_raid(auth_client, raid_ready_fleet.id)
        after = datetime.now(timezone.utc)

        row = (
            db.query(ResourceLog)
            .filter(ResourceLog.nation_id == defender_nation.id)
            .order_by(ResourceLog.id.desc())
            .first()
        )
        assert row is not None, "Defender ResourceLog row is missing"

        tick_at = row.tick_at
        if tick_at.tzinfo is None:
            tick_at = tick_at.replace(tzinfo=timezone.utc)

        assert before - timedelta(seconds=TICK_AT_TOLERANCE_SECONDS) <= tick_at <= after + timedelta(seconds=TICK_AT_TOLERANCE_SECONDS), (
            f"Defender ResourceLog tick_at={tick_at} is not within {TICK_AT_TOLERANCE_SECONDS}s of now"
        )


# ===========================================================================
# Test 2 — Attacker ResourceLog row: positive deltas
# ===========================================================================

class TestAttackerResourceLogPositive:
    """
    After a successful raid, the attacker's nation must have a ResourceLog row
    with positive minerals_delta, fuel_delta, and currency_delta equal to the
    amounts gained.
    """

    def test_attacker_resource_log_row_exists(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """A ResourceLog row must be created for the attacker after a raid."""
        _set_war(db, attacker_nation.id, defender_nation.id)
        _do_raid(auth_client, raid_ready_fleet.id)

        rows = (
            db.query(ResourceLog)
            .filter(ResourceLog.nation_id == attacker_nation.id)
            .all()
        )
        assert len(rows) >= 1, (
            "Attacker must have at least one ResourceLog row after a raid. "
            "The raid_fleet endpoint is missing ResourceLog insertion for the attacker."
        )

    def test_attacker_resource_log_minerals_delta_is_positive(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """Attacker's ResourceLog minerals_delta must be positive (resources were gained)."""
        _set_war(db, attacker_nation.id, defender_nation.id)
        _do_raid(auth_client, raid_ready_fleet.id)

        row = (
            db.query(ResourceLog)
            .filter(ResourceLog.nation_id == attacker_nation.id)
            .order_by(ResourceLog.id.desc())
            .first()
        )
        assert row is not None, "Attacker ResourceLog row is missing"
        assert float(row.minerals_delta) > 0, (
            f"Attacker minerals_delta must be positive; got {row.minerals_delta}"
        )

    def test_attacker_resource_log_fuel_delta_is_positive(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """Attacker's ResourceLog fuel_delta must be positive."""
        _set_war(db, attacker_nation.id, defender_nation.id)
        _do_raid(auth_client, raid_ready_fleet.id)

        row = (
            db.query(ResourceLog)
            .filter(ResourceLog.nation_id == attacker_nation.id)
            .order_by(ResourceLog.id.desc())
            .first()
        )
        assert row is not None, "Attacker ResourceLog row is missing"
        assert float(row.fuel_delta) > 0, (
            f"Attacker fuel_delta must be positive; got {row.fuel_delta}"
        )

    def test_attacker_resource_log_currency_delta_is_positive(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """Attacker's ResourceLog currency_delta must be positive."""
        _set_war(db, attacker_nation.id, defender_nation.id)
        _do_raid(auth_client, raid_ready_fleet.id)

        row = (
            db.query(ResourceLog)
            .filter(ResourceLog.nation_id == attacker_nation.id)
            .order_by(ResourceLog.id.desc())
            .first()
        )
        assert row is not None, "Attacker ResourceLog row is missing"
        assert float(row.currency_delta) > 0, (
            f"Attacker currency_delta must be positive; got {row.currency_delta}"
        )

    def test_attacker_resource_log_deltas_match_gained_amounts(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """
        The attacker's positive deltas must match the amounts actually added to
        the attacker's stockpile.
        """
        _set_war(db, attacker_nation.id, defender_nation.id)

        minerals_before = float(attacker_nation.minerals)
        fuel_before = float(attacker_nation.fuel)
        currency_before = float(attacker_nation.currency)

        _do_raid(auth_client, raid_ready_fleet.id)

        db.refresh(attacker_nation)
        minerals_gained = float(attacker_nation.minerals) - minerals_before
        fuel_gained = float(attacker_nation.fuel) - fuel_before
        currency_gained = float(attacker_nation.currency) - currency_before

        row = (
            db.query(ResourceLog)
            .filter(ResourceLog.nation_id == attacker_nation.id)
            .order_by(ResourceLog.id.desc())
            .first()
        )
        assert row is not None, "Attacker ResourceLog row is missing"

        assert float(row.minerals_delta) == pytest.approx(minerals_gained, abs=0.01), (
            f"Attacker minerals_delta {row.minerals_delta} does not match actual gain {minerals_gained}"
        )
        assert float(row.fuel_delta) == pytest.approx(fuel_gained, abs=0.01), (
            f"Attacker fuel_delta {row.fuel_delta} does not match actual gain {fuel_gained}"
        )
        assert float(row.currency_delta) == pytest.approx(currency_gained, abs=0.01), (
            f"Attacker currency_delta {row.currency_delta} does not match actual gain {currency_gained}"
        )

    def test_attacker_resource_log_tick_at_is_now(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """
        Attacker's ResourceLog tick_at must be approximately NOW at the moment
        the raid executes (within TICK_AT_TOLERANCE_SECONDS).
        """
        _set_war(db, attacker_nation.id, defender_nation.id)
        before = datetime.now(timezone.utc)
        _do_raid(auth_client, raid_ready_fleet.id)
        after = datetime.now(timezone.utc)

        row = (
            db.query(ResourceLog)
            .filter(ResourceLog.nation_id == attacker_nation.id)
            .order_by(ResourceLog.id.desc())
            .first()
        )
        assert row is not None, "Attacker ResourceLog row is missing"

        tick_at = row.tick_at
        if tick_at.tzinfo is None:
            tick_at = tick_at.replace(tzinfo=timezone.utc)

        assert before - timedelta(seconds=TICK_AT_TOLERANCE_SECONDS) <= tick_at <= after + timedelta(seconds=TICK_AT_TOLERANCE_SECONDS), (
            f"Attacker ResourceLog tick_at={tick_at} is not within {TICK_AT_TOLERANCE_SECONDS}s of now"
        )


# ===========================================================================
# Test 3 — Nation stockpile sanity check
# ===========================================================================

class TestNationStockpilesAfterRaid:
    """
    Sanity-check that the nation stockpiles are correctly updated by the raid
    (this was already working before the bug, but serves as a regression guard
    against the fix accidentally breaking it).
    """

    def test_defender_stockpiles_decrease_after_raid(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """Defender's minerals, fuel, and currency must all decrease after a raid."""
        _set_war(db, attacker_nation.id, defender_nation.id)

        minerals_before = float(defender_nation.minerals)
        fuel_before = float(defender_nation.fuel)
        currency_before = float(defender_nation.currency)

        _do_raid(auth_client, raid_ready_fleet.id)

        db.refresh(defender_nation)
        assert float(defender_nation.minerals) < minerals_before, (
            "Defender minerals must decrease after a raid"
        )
        assert float(defender_nation.fuel) < fuel_before, (
            "Defender fuel must decrease after a raid"
        )
        assert float(defender_nation.currency) < currency_before, (
            "Defender currency must decrease after a raid"
        )

    def test_attacker_stockpiles_increase_after_raid(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """Attacker's minerals, fuel, and currency must all increase after a raid."""
        _set_war(db, attacker_nation.id, defender_nation.id)

        minerals_before = float(attacker_nation.minerals)
        fuel_before = float(attacker_nation.fuel)
        currency_before = float(attacker_nation.currency)

        _do_raid(auth_client, raid_ready_fleet.id)

        db.refresh(attacker_nation)
        assert float(attacker_nation.minerals) > minerals_before, (
            "Attacker minerals must increase after a raid"
        )
        assert float(attacker_nation.fuel) > fuel_before, (
            "Attacker fuel must increase after a raid"
        )
        assert float(attacker_nation.currency) > currency_before, (
            "Attacker currency must increase after a raid"
        )

    def test_stolen_amount_equals_gained_amount(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """
        The amounts lost by the defender must exactly equal the amounts gained
        by the attacker (resources are transferred, not created or destroyed).
        """
        _set_war(db, attacker_nation.id, defender_nation.id)

        atk_minerals_before = float(attacker_nation.minerals)
        atk_fuel_before = float(attacker_nation.fuel)
        atk_currency_before = float(attacker_nation.currency)

        def_minerals_before = float(defender_nation.minerals)
        def_fuel_before = float(defender_nation.fuel)
        def_currency_before = float(defender_nation.currency)

        _do_raid(auth_client, raid_ready_fleet.id)

        db.refresh(attacker_nation)
        db.refresh(defender_nation)

        minerals_gained = float(attacker_nation.minerals) - atk_minerals_before
        minerals_lost = def_minerals_before - float(defender_nation.minerals)
        assert minerals_gained == pytest.approx(minerals_lost, abs=0.01), (
            f"Minerals gained by attacker ({minerals_gained}) != minerals lost by defender ({minerals_lost})"
        )

        fuel_gained = float(attacker_nation.fuel) - atk_fuel_before
        fuel_lost = def_fuel_before - float(defender_nation.fuel)
        assert fuel_gained == pytest.approx(fuel_lost, abs=0.01), (
            f"Fuel gained by attacker ({fuel_gained}) != fuel lost by defender ({fuel_lost})"
        )

        currency_gained = float(attacker_nation.currency) - atk_currency_before
        currency_lost = def_currency_before - float(defender_nation.currency)
        assert currency_gained == pytest.approx(currency_lost, abs=0.01), (
            f"Currency gained by attacker ({currency_gained}) != currency lost by defender ({currency_lost})"
        )

    def test_defender_stockpiles_never_go_below_zero(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """
        The raid uses min(stolen, available), so the defender's stockpiles must
        never be driven below zero.
        """
        _set_war(db, attacker_nation.id, defender_nation.id)
        _do_raid(auth_client, raid_ready_fleet.id)

        db.refresh(defender_nation)
        assert float(defender_nation.minerals) >= 0.0, "Defender minerals went below zero"
        assert float(defender_nation.fuel) >= 0.0, "Defender fuel went below zero"
        assert float(defender_nation.currency) >= 0.0, "Defender currency went below zero"


# ===========================================================================
# Test 4 — raid_applied Event regression guard
# ===========================================================================

class TestRaidAppliedEventRegression:
    """
    Ensure the existing raid_applied Event write is not broken by the fix.
    """

    def test_raid_applied_event_is_written(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """A raid_applied Event must exist in the events table after a raid."""
        _set_war(db, attacker_nation.id, defender_nation.id)
        _do_raid(auth_client, raid_ready_fleet.id)

        event = (
            db.query(Event)
            .filter(Event.type == "raid_applied")
            .first()
        )
        assert event is not None, (
            "raid_applied Event must be written after a raid. "
            "This is a regression guard — if this fails, the fix broke the existing event write."
        )

    def test_raid_applied_event_payload_contains_fleet_id(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """The raid_applied Event payload must contain the fleet_id."""
        _set_war(db, attacker_nation.id, defender_nation.id)
        _do_raid(auth_client, raid_ready_fleet.id)

        event = (
            db.query(Event)
            .filter(Event.type == "raid_applied")
            .first()
        )
        assert event is not None
        assert event.payload is not None
        assert "fleet_id" in event.payload, (
            "raid_applied Event payload must contain fleet_id"
        )
        assert event.payload["fleet_id"] == raid_ready_fleet.id

    def test_raid_applied_event_payload_contains_stolen_amounts(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """The raid_applied Event payload must record the stolen amounts."""
        _set_war(db, attacker_nation.id, defender_nation.id)
        _do_raid(auth_client, raid_ready_fleet.id)

        event = (
            db.query(Event)
            .filter(Event.type == "raid_applied")
            .first()
        )
        assert event is not None
        payload = event.payload
        assert "minerals_stolen" in payload, "raid_applied payload must have minerals_stolen"
        assert "fuel_stolen" in payload, "raid_applied payload must have fuel_stolen"
        assert "currency_stolen" in payload, "raid_applied payload must have currency_stolen"
        assert float(payload["minerals_stolen"]) >= 0
        assert float(payload["fuel_stolen"]) >= 0
        assert float(payload["currency_stolen"]) >= 0

    def test_raid_applied_event_payload_nation_ids(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """The raid_applied Event payload must identify both nations correctly."""
        _set_war(db, attacker_nation.id, defender_nation.id)
        _do_raid(auth_client, raid_ready_fleet.id)

        event = (
            db.query(Event)
            .filter(Event.type == "raid_applied")
            .first()
        )
        assert event is not None
        payload = event.payload
        assert payload.get("attacker_nation_id") == attacker_nation.id
        assert payload.get("defender_nation_id") == defender_nation.id

    def test_exactly_two_resource_log_rows_are_written(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """
        Exactly two ResourceLog rows must be created by a single raid —
        one for the attacker and one for the defender.  No duplicates.
        """
        _set_war(db, attacker_nation.id, defender_nation.id)
        _do_raid(auth_client, raid_ready_fleet.id)

        attacker_rows = (
            db.query(ResourceLog)
            .filter(ResourceLog.nation_id == attacker_nation.id)
            .all()
        )
        defender_rows = (
            db.query(ResourceLog)
            .filter(ResourceLog.nation_id == defender_nation.id)
            .all()
        )

        assert len(attacker_rows) == 1, (
            f"Expected exactly 1 attacker ResourceLog row, found {len(attacker_rows)}"
        )
        assert len(defender_rows) == 1, (
            f"Expected exactly 1 defender ResourceLog row, found {len(defender_rows)}"
        )


# ===========================================================================
# Auth and precondition enforcement (guard against regressions from the fix)
# ===========================================================================

class TestRaidEndpointGuards:
    """
    These tests cover the existing precondition checks on the raid endpoint to
    ensure the fix does not accidentally relax them.
    """

    def test_unauthenticated_raid_returns_401(
        self,
        unauthenticated_client: TestClient,
        attacker_nation: Nation,
        defender_nation: Nation,
        raid_ready_fleet: Fleet,
    ):
        """Unauthenticated request to the raid endpoint must return 401."""
        resp = unauthenticated_client.post(
            f"/api/military/fleets/{raid_ready_fleet.id}/raid"
        )
        assert resp.status_code == 401, (
            f"Expected 401 for unauthenticated raid, got {resp.status_code}"
        )

    def test_raid_wrong_fleet_status_returns_409(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        attacker_territory: Territory,
        defender_territory: Territory,
    ):
        """Fleet must be in post_battle_choice status; any other status returns 409."""
        _set_war(db, attacker_nation.id, defender_nation.id)

        # Fleet in wrong state — stationed, not post_battle_choice
        wrong_fleet = Fleet(
            nation_id=attacker_nation.id,
            origin_territory=attacker_territory.id,
            destination_territory=defender_territory.id,
            unit_count=FLEET_UNITS,
            status="stationed",
            standing_order="hold",
        )
        db.add(wrong_fleet)
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{wrong_fleet.id}/raid")
        assert resp.status_code == 409, (
            f"Expected 409 for fleet not in post_battle_choice, got {resp.status_code}"
        )

    def test_raid_on_nonexistent_fleet_returns_403(
        self,
        auth_client: TestClient,
        attacker_nation: Nation,
        defender_nation: Nation,
    ):
        """Raiding a fleet ID that does not exist must return 403."""
        resp = auth_client.post("/api/military/fleets/999999/raid")
        assert resp.status_code == 403

    def test_raid_on_own_territory_returns_409(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_territory: Territory,
    ):
        """
        Raiding your own territory must be blocked — the raid endpoint requires
        an enemy territory at the destination.
        """
        own_fleet = Fleet(
            nation_id=attacker_nation.id,
            origin_territory=attacker_territory.id,
            destination_territory=attacker_territory.id,  # own territory
            unit_count=FLEET_UNITS,
            status="post_battle_choice",
            standing_order="hold",
        )
        db.add(own_fleet)
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{own_fleet.id}/raid")
        assert resp.status_code == 409

    def test_raid_fleet_status_changes_to_engaged(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """After a successful raid the fleet status must transition to 'engaged'."""
        _set_war(db, attacker_nation.id, defender_nation.id)
        _do_raid(auth_client, raid_ready_fleet.id)

        db.refresh(raid_ready_fleet)
        assert raid_ready_fleet.status == "engaged", (
            f"Fleet status must be 'engaged' after raid, got {raid_ready_fleet.status!r}"
        )

    def test_raid_no_resource_log_without_prior_war_check(
        self,
        auth_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
        raid_ready_fleet: Fleet,
    ):
        """
        When the raid fails (e.g. bad fleet status), no ResourceLog rows must be
        written.  This verifies atomic behaviour — logs only appear on success.
        """
        # Do NOT set war; fleet is already in post_battle_choice but no war exists.
        # The endpoint may or may not block on that condition — what matters is
        # that if it returns a non-200, no ResourceLog rows appear.
        resp = auth_client.post(f"/api/military/fleets/{raid_ready_fleet.id}/raid")

        if resp.status_code != 200:
            # If the endpoint rejected the request, no ResourceLog rows should exist
            total_log_rows = db.query(ResourceLog).count()
            assert total_log_rows == 0, (
                f"No ResourceLog rows should be written on a failed raid, "
                f"found {total_log_rows}"
            )
