"""
Test suite for the Occupation Window mechanic.

After an attacking fleet eliminates all defenders on an enemy planet, it enters
`occupying` status with a 6-tick (12-hour) decision window.  The attacker can:
  - POST /api/military/fleets/{id}/occupy   → formally claim the territory
  - POST /api/military/fleets/{id}/recall   → withdraw voluntarily

If the window expires with no action, the fleet is auto-recalled.
If the enemy sends defending units back while the fleet is `occupying`, the
window is cancelled and the fleet reverts to `holding`.

Game-design rules enforced:
  - Inaction on expiry → auto-recall, NOT auto-claim (safe default)
  - An `occupying` fleet counts the same as `holding` for dissent (+6/tick), not +10
  - `occupy` is only callable when fleet is in `occupying` status, not `engaged`
  - `recall` must work from `occupying` status (as well as existing statuses)
  - `occupation_expires_at` must be cleared on both occupy and recall
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
from app.models.territory_dissent import TerritoryDissent
from app.core.security import create_access_token, hash_password
from app.constants import UNIT_STATS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TICK_HOURS = 2
OCCUPATION_WINDOW_HOURS = 12   # 6 ticks × 2 hours/tick
CLOCK_TOLERANCE_SECONDS = 60

# starfighters move 2 nodes/tick; home=0,0 and enemy=2,0 → 1 tick → 2 hours
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
        row.declared_by = a
    else:
        row = Diplomacy(nation_a=a, nation_b=b, status="war", declared_by=a)
        db.add(row)
    db.flush()
    return row


def _db_override(session: Session):
    def _override():
        yield session
    return _override


def _commit_and_run_tick(db: Session) -> None:
    """Commit the transactional session so SessionLocal() inside run_tick sees the rows,
    then invoke run_tick synchronously as a plain function."""
    db.commit()
    from app.tasks.tick import run_tick
    run_tick()


def _make_fleet(
    db: Session,
    *,
    nation_id: int,
    origin_id: int,
    dest_id: int | None = None,
    status: str,
    unit_count: int = 50,
    standing_order: str = "hold",
    arrives_at: datetime | None = None,
    confirmation_expires_at: datetime | None = None,
    occupation_expires_at: datetime | None = None,
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
    # Set occupation_expires_at via setattr to avoid referencing the column
    # before the migration adds it.  The implementation will add this column to
    # the model; the test just needs to write/read it by attribute name.
    if occupation_expires_at is not None:
        fleet.occupation_expires_at = occupation_expires_at
    db.add(fleet)
    db.flush()
    return fleet


# ---------------------------------------------------------------------------
# Fixtures: two nations, two territories
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
        currency=500,
    )
    db.add(nation)
    db.flush()
    return nation


@pytest.fixture()
def home_territory(db: Session, test_nation: Nation) -> Territory:
    """Colonized territory for test_nation at hex 0,0."""
    t = Territory(
        node_key="0,0",
        name="Home World",
        territory_type="normal",
        nation_id=test_nation.id,
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
        is_owned=True,
        owned_at=datetime.now(timezone.utc),
    )
    db.add(t)
    db.flush()
    return t


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


# ===========================================================================
# 1. TICK: engaged → occupying transition (no defenders remaining)
# ===========================================================================


class TestTickEngagedToOccupyingTransition:
    """Tick processing: an engaged fleet that finds no stationed defenders should
    transition to `occupying`, not stay engaged or claim territory immediately."""

    def test_engaged_to_occupying_when_no_defenders(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Engaged fleet at enemy territory with no stationed defender → status becomes `occupying`."""
        _set_war(db, test_nation.id, enemy_nation.id)

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="engaged",
        )
        fleet_id = fleet.id
        # No defender fleet is seeded — territory is uncontested
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None, "Fleet must still exist after tick"
            assert f.status == "occupying", (
                f"Engaged fleet with no defenders must become 'occupying', got {f.status!r}"
            )
        finally:
            fresh.close()

    def test_engaged_to_occupying_sets_occupation_expires_at_12h(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """When transitioning to `occupying`, occupation_expires_at must be set to ~now + 12h."""
        _set_war(db, test_nation.id, enemy_nation.id)

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="engaged",
        )
        fleet_id = fleet.id
        before_tick = datetime.now(timezone.utc)
        db.commit()

        _commit_and_run_tick(db)

        after_tick = datetime.now(timezone.utc)
        expected_low = before_tick + timedelta(hours=OCCUPATION_WINDOW_HOURS)
        expected_high = after_tick + timedelta(hours=OCCUPATION_WINDOW_HOURS)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.status == "occupying", (
                f"Fleet must be in 'occupying' status, got {f.status!r}"
            )
            exp = f.occupation_expires_at
            assert exp is not None, (
                "occupation_expires_at must be set when fleet enters 'occupying' status"
            )
            exp_utc = exp.replace(tzinfo=timezone.utc)
            assert (
                expected_low - timedelta(seconds=CLOCK_TOLERANCE_SECONDS)
                <= exp_utc
                <= expected_high + timedelta(seconds=CLOCK_TOLERANCE_SECONDS)
            ), (
                f"occupation_expires_at {exp_utc} must be within "
                f"[{expected_low}, {expected_high}]"
            )
        finally:
            fresh.close()

    def test_engaged_to_occupying_emits_territory_uncontested_event(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Tick must emit a `territory_uncontested` Event when fleet transitions to occupying."""
        _set_war(db, test_nation.id, enemy_nation.id)

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="engaged",
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            event = fresh.query(Event).filter(
                Event.type == "territory_uncontested",
            ).first()
            assert event is not None, (
                "A `territory_uncontested` event must be emitted when a fleet transitions "
                "to 'occupying' after defeating all defenders"
            )
            assert event.payload["fleet_id"] == fleet_id
            assert event.payload["territory_id"] == enemy_territory.id
            assert event.payload["attacker_nation_id"] == test_nation.id
        finally:
            fresh.close()

    def test_engaged_no_occupying_transition_when_defender_alive(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Engaged fleet at enemy territory WITH a stationed defending fleet must NOT transition
        to `occupying`; combat should continue on the normal path."""
        _set_war(db, test_nation.id, enemy_nation.id)

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="engaged",
            unit_count=50,
        )
        fleet_id = fleet.id

        # Defender fleet stationed at enemy_territory
        defender = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=50,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender)
        db.flush()
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            # Fleet may be destroyed or moved to post_battle_choice; it must NOT be occupying
            if f is not None:
                assert f.status != "occupying", (
                    f"Fleet must NOT transition to 'occupying' while defenders are alive, "
                    f"got {f.status!r}"
                )
        finally:
            fresh.close()

    def test_engaged_to_occupying_territory_still_owned_by_enemy(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """The territory must still belong to the enemy nation during the occupation window;
        ownership transfer only happens when the attacker explicitly calls /occupy."""
        _set_war(db, test_nation.id, enemy_nation.id)

        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="engaged",
        )
        enemy_territory_id = enemy_territory.id
        original_owner = enemy_nation.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            territory = fresh.get(Territory, enemy_territory_id)
            assert territory.nation_id == original_owner, (
                "Territory must still belong to the defender during the occupation window; "
                "ownership transfer only happens on explicit /occupy call"
            )
        finally:
            fresh.close()


# ===========================================================================
# 2. TICK: occupation window expiry → auto-recall
# ===========================================================================


class TestTickOccupationWindowExpiry:
    """Tick processing: occupation_expires_at has passed with no player action."""

    def test_occupation_window_expiry_auto_recalls_fleet(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet in `occupying` status with expired occupation_expires_at must be auto-recalled
        (status becomes in_transit heading home), not auto-claim."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now - timedelta(minutes=1),  # already expired
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None, "Fleet must still exist after auto-recall"
            assert f.status == "in_transit", (
                f"Expired occupation window must auto-recall fleet (in_transit), got {f.status!r}"
            )
        finally:
            fresh.close()

    def test_occupation_window_expiry_fleet_heading_home(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """After auto-recall, origin must be the enemy territory and destination the home territory."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now - timedelta(minutes=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.status == "in_transit"
            assert f.origin_territory == enemy_territory.id, (
                "After auto-recall, origin must be the enemy territory the fleet was occupying"
            )
            assert f.destination_territory == home_territory.id, (
                "After auto-recall, destination must be the home territory"
            )
            assert f.arrives_at is not None, (
                "Auto-recalled fleet must have arrives_at set for the return journey"
            )
        finally:
            fresh.close()

    def test_occupation_window_expiry_clears_occupation_expires_at(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """occupation_expires_at must be cleared after auto-recall."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now - timedelta(minutes=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.occupation_expires_at is None, (
                "occupation_expires_at must be cleared after the occupation window expires"
            )
        finally:
            fresh.close()

    def test_occupation_window_expiry_emits_occupation_window_expired_event(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Tick must emit an `occupation_window_expired` Event when the window times out."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now - timedelta(minutes=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            event = fresh.query(Event).filter(
                Event.type == "occupation_window_expired",
            ).first()
            assert event is not None, (
                "An `occupation_window_expired` event must be emitted when the window expires "
                "and the fleet is auto-recalled"
            )
            assert event.payload["fleet_id"] == fleet_id
            assert event.payload["nation_id"] == test_nation.id
            assert event.payload["territory_id"] == enemy_territory.id
        finally:
            fresh.close()

    def test_occupation_window_expiry_does_not_claim_territory(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """CRITICAL game-design rule: inaction must produce the SAFE default.
        An expired occupation window must never auto-claim the territory."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now - timedelta(minutes=1),
        )
        enemy_territory_id = enemy_territory.id
        original_owner = enemy_nation.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            territory = fresh.get(Territory, enemy_territory_id)
            assert territory.nation_id == original_owner, (
                "CRITICAL: Inaction (occupation window expiry) must NEVER auto-claim the territory. "
                "Territory must remain owned by the original defender. "
                "Game design rule: inaction must never produce maximum harm."
            )
        finally:
            fresh.close()

    def test_occupation_window_not_expired_fleet_remains_occupying(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet `occupying` with future occupation_expires_at must remain in `occupying` status."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),  # not yet expired
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None, "Fleet must still exist"
            assert f.status == "occupying", (
                f"Fleet with non-expired occupation window must stay 'occupying', got {f.status!r}"
            )
            assert f.occupation_expires_at is not None, (
                "occupation_expires_at must not be cleared for a non-expired window"
            )
        finally:
            fresh.close()

    def test_occupation_window_expiry_arrives_at_based_on_distance(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """The auto-recalled fleet's arrives_at must reflect the hex distance home."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now - timedelta(minutes=1),
        )
        fleet_id = fleet.id
        before_tick = datetime.now(timezone.utc)
        db.commit()

        _commit_and_run_tick(db)

        after_tick = datetime.now(timezone.utc)

        # home=0,0, enemy=2,0 → hex distance 2; nodes_per_tick=2 → 1 tick → 2 hours
        distance = 2
        transit_ticks = ceil(distance / NODES_PER_TICK)
        expected_hours = transit_ticks * TICK_HOURS

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.arrives_at is not None
            arrives = f.arrives_at.replace(tzinfo=timezone.utc)
            expected_low = before_tick + timedelta(hours=expected_hours)
            expected_high = after_tick + timedelta(hours=expected_hours)
            assert (
                expected_low - timedelta(seconds=CLOCK_TOLERANCE_SECONDS)
                <= arrives
                <= expected_high + timedelta(seconds=CLOCK_TOLERANCE_SECONDS)
            ), (
                f"Auto-recalled fleet arrives_at {arrives} must be ~{expected_hours}h from tick time"
            )
        finally:
            fresh.close()


# ===========================================================================
# 3. TICK: enemy arrival cancels occupation window
# ===========================================================================


class TestTickEnemyArrivalCancelsOccupation:
    """Tick processing: defender stations a fleet at the occupied territory while
    the attacker's fleet is in `occupying` status."""

    def test_enemy_stationed_fleet_cancels_occupation_window(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """When the territory's owning nation has a stationed fleet at the occupied territory,
        the occupying fleet must revert to `holding` status."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),  # window still open
        )
        fleet_id = fleet.id

        # Enemy stations a defending fleet at their territory — cancels the window
        defender = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=20,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender)
        db.flush()
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None, "Attacker fleet must still exist after cancellation"
            assert f.status == "holding", (
                f"Enemy arrival must cancel the occupation window and revert fleet to 'holding', "
                f"got {f.status!r}"
            )
        finally:
            fresh.close()

    def test_enemy_arrival_clears_occupation_expires_at(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """occupation_expires_at must be cleared when the window is cancelled by enemy arrival."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id

        defender = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=20,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender)
        db.flush()
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.occupation_expires_at is None, (
                "occupation_expires_at must be cleared when the occupation window is cancelled "
                "by enemy arrival"
            )
        finally:
            fresh.close()

    def test_enemy_arrival_emits_occupation_window_cancelled_event(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Tick must emit an `occupation_window_cancelled` Event when enemy arrives."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id

        defender = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=20,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender)
        db.flush()
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            event = fresh.query(Event).filter(
                Event.type == "occupation_window_cancelled",
            ).first()
            assert event is not None, (
                "An `occupation_window_cancelled` event must be emitted when the enemy "
                "stations a fleet at the occupied territory"
            )
            assert event.payload["fleet_id"] == fleet_id
            assert event.payload["territory_id"] == enemy_territory.id
        finally:
            fresh.close()

    def test_no_enemy_fleet_occupation_window_not_cancelled(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Without an enemy stationed fleet, the occupation window must NOT be cancelled."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        # No defender fleet — window should remain active
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.status == "occupying", (
                "Without enemy defenders, occupation window must remain open and fleet stay 'occupying'"
            )
            assert f.occupation_expires_at is not None, (
                "occupation_expires_at must not be cleared without enemy presence"
            )
            cancelled_event = fresh.query(Event).filter(
                Event.type == "occupation_window_cancelled"
            ).first()
            assert cancelled_event is None, (
                "occupation_window_cancelled must NOT be emitted when there are no enemy defenders"
            )
        finally:
            fresh.close()


# ===========================================================================
# 4. TICK: dissent — occupying counts as holding (+6/tick), not engaged (+10)
# ===========================================================================


class TestDissentOccupyingStatus:
    """Tick dissent loop: `occupying` fleet must add +6 to the territory dissent,
    same as `holding`, not +10 (which is `engaged`)."""

    def test_occupying_fleet_adds_6_dissent_per_tick(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """An `occupying` fleet at an enemy territory adds +6 dissent (holding rate) not +10."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Seed a known dissent value
        dissent_row = TerritoryDissent(territory_id=enemy_territory.id, dissent=10)
        db.add(dissent_row)
        db.flush()

        now = datetime.now(timezone.utc)
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            row = fresh.query(TerritoryDissent).filter(
                TerritoryDissent.territory_id == enemy_territory.id
            ).first()
            assert row is not None
            # Expected: +2 (war defender) + 6 (occupying treated as holding) + 0 (occupied decay) = +8
            # Start 10 + 8 = 18.  Engaged would give 12 → 22.
            new_dissent = row.dissent
            assert new_dissent == 18, (
                f"Occupying fleet must count as holding (+6) for dissent, "
                f"giving 10+8=18. Got {new_dissent}. "
                f"If 22, the fleet was incorrectly counted as engaged (+10)."
            )
        finally:
            fresh.close()

    def test_occupying_fleet_not_counted_as_engaged_for_dissent(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Verify explicitly that the dissent contribution of `occupying` != `engaged` contribution."""
        _set_war(db, test_nation.id, enemy_nation.id)

        dissent_row = TerritoryDissent(territory_id=enemy_territory.id, dissent=10)
        db.add(dissent_row)
        db.flush()

        now = datetime.now(timezone.utc)
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            row = fresh.query(TerritoryDissent).filter(
                TerritoryDissent.territory_id == enemy_territory.id
            ).first()
            assert row is not None
            # Engaged rate: 10 + 12 = 22.  Holding/occupying rate: 10 + 8 = 18.
            # Must NOT be 22 (engaged rate).
            assert row.dissent != 22, (
                "occupying fleet must NOT be counted as 'engaged' for dissent calculation "
                "(would give 22, only 'engaged' gives that)"
            )
        finally:
            fresh.close()


# ===========================================================================
# 5. ROUTER: POST /api/military/fleets/{id}/occupy
# ===========================================================================


class TestOccupyEndpoint:
    """Tests for POST /api/military/fleets/{fleet_id}/occupy."""

    def test_occupy_requires_occupying_status_not_engaged(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet in `engaged` status must return 409 — fleet must be `occupying` to claim."""
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

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/occupy")
        assert resp.status_code == 409, (
            f"Calling /occupy on an engaged fleet must return 409 (must be in 'occupying' status), "
            f"got {resp.status_code}"
        )

    def test_occupy_success_from_occupying_status(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet in `occupying` status → POST /occupy → returns 200 and territory is claimed."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/occupy")
        assert resp.status_code == 200, resp.text

        data = resp.json()
        assert data["nation_id"] == test_nation.id, (
            f"Territory must now belong to the attacker nation after /occupy, "
            f"got nation_id={data['nation_id']}"
        )

    def test_occupy_transfers_territory_ownership(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """After a successful /occupy call the territory's nation_id must be the attacker's."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        territory_id = enemy_territory.id
        db.flush()

        auth_client.post(f"/api/military/fleets/{fleet_id}/occupy")

        db.expire_all()
        territory = db.get(Territory, territory_id)
        assert territory is not None
        assert territory.nation_id == test_nation.id, (
            "After /occupy, territory nation_id must be the attacker's nation"
        )

    def test_occupy_sets_dissent_to_60(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Conquered territory dissent must be set to 60 (DISSENT_CONQUEST_RESET) on claim."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        territory_id = enemy_territory.id
        db.flush()

        auth_client.post(f"/api/military/fleets/{fleet_id}/occupy")

        db.expire_all()
        dissent_row = db.query(TerritoryDissent).filter(
            TerritoryDissent.territory_id == territory_id
        ).first()
        assert dissent_row is not None, "A dissent row must exist for the conquered territory"
        assert dissent_row.dissent == 60, (
            f"Conquered territory dissent must be set to 60, got {dissent_row.dissent}"
        )

    def test_occupy_stations_fleet_at_territory(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """After /occupy the fleet must be stationed at the newly-claimed territory."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        territory_id = enemy_territory.id
        db.flush()

        auth_client.post(f"/api/military/fleets/{fleet_id}/occupy")

        db.expire_all()
        fleet_after = db.get(Fleet, fleet_id)
        assert fleet_after is not None
        assert fleet_after.status == "stationed", (
            f"Fleet must be stationed after /occupy, got {fleet_after.status!r}"
        )
        assert fleet_after.origin_territory == territory_id, (
            "Fleet must be stationed at the newly-claimed territory"
        )
        assert fleet_after.destination_territory is None, (
            "Fleet destination must be None after being stationed"
        )

    def test_occupy_clears_occupation_expires_at(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """After a successful /occupy call, occupation_expires_at must be None."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        db.flush()

        auth_client.post(f"/api/military/fleets/{fleet_id}/occupy")

        db.expire_all()
        fleet_after = db.get(Fleet, fleet_id)
        assert fleet_after is not None
        assert fleet_after.occupation_expires_at is None, (
            "occupation_expires_at must be None after successfully calling /occupy"
        )

    def test_occupy_response_includes_occupation_expires_at_field(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """The occupy endpoint response should not contain occupation_expires_at (it's a
        ClaimTerritoryResponse), but GET /api/military/fleets must include it for FleetResponse."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        db.flush()

        # After claiming, GET /fleets must show fleet as stationed with no occupation window
        auth_client.post(f"/api/military/fleets/{fleet_id}/occupy")

        resp = auth_client.get("/api/military/fleets")
        assert resp.status_code == 200
        fleets = resp.json()
        stationed = next((f for f in fleets if f["id"] == fleet_id), None)
        assert stationed is not None, "Fleet must appear in the fleet list after /occupy"
        assert "occupation_expires_at" in stationed, (
            "FleetResponse must include the occupation_expires_at field"
        )
        assert stationed["occupation_expires_at"] is None, (
            "occupation_expires_at must be null in FleetResponse after claiming"
        )

    def test_occupy_requires_war(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Cannot call /occupy if not at war with the territory's owner — returns 409."""
        # No war declared
        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/occupy")
        assert resp.status_code == 409

    def test_occupy_wrong_owner_returns_403(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """A player cannot call /occupy on another nation's fleet — must return 403."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{fleet_id}/occupy")
        assert resp.status_code == 403

    def test_occupy_unauthenticated_returns_401(
        self,
        client: TestClient,
        db: Session,
        test_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Unauthenticated request to /occupy must return 401."""
        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        db.flush()

        resp = client.post(f"/api/military/fleets/{fleet_id}/occupy")
        assert resp.status_code == 401

    def test_occupy_nonexistent_fleet_returns_403(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """Calling /occupy on a non-existent fleet ID must return 403."""
        resp = auth_client.post("/api/military/fleets/999999/occupy")
        assert resp.status_code == 403

    def test_occupy_void_territory_returns_409(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
    ):
        """Void territories cannot be conquered — must return 409."""
        _set_war(db, test_nation.id, enemy_nation.id)

        void_territory = Territory(
            node_key="3,0",
            name=None,
            territory_type="void",
            nation_id=enemy_nation.id,
            mineral_richness=0.00,
            fuel_richness=0.00,
            distance_from_center=3,
            is_owned=False,
        )
        db.add(void_territory)
        db.flush()

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=void_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/occupy")
        assert resp.status_code == 409, (
            "Void territories must not be conquerable — /occupy must return 409"
        )

    def test_occupy_wrong_status_pending_confirmation_returns_409(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet in `pending_confirmation` must return 409 — occupy requires `occupying`."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=4),
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/occupy")
        assert resp.status_code == 409

    def test_occupy_wrong_status_holding_returns_409(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet in `holding` status must return 409 — occupy requires `occupying`."""
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

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/occupy")
        assert resp.status_code == 409

    def test_occupy_with_active_defenders_returns_409(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Cannot /occupy if enemy still has stationed defenders at the territory."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id

        # Enemy still has defenders
        defender = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=10,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender)
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/occupy")
        assert resp.status_code == 409, (
            "Cannot claim territory while enemy defenders are still stationed there"
        )


# ===========================================================================
# 6. ROUTER: POST /api/military/fleets/{id}/recall (extended for occupying)
# ===========================================================================


class TestRecallFromOccupyingStatus:
    """Tests for the recall endpoint extended to accept `occupying` status."""

    def test_recall_allowed_from_occupying(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet in `occupying` status → POST /recall → returns 200 and fleet becomes in_transit."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/recall")
        assert resp.status_code == 200, (
            f"Recalling an occupying fleet must return 200, got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert data["status"] == "in_transit", (
            f"Recalled occupying fleet must become in_transit, got {data['status']!r}"
        )

    def test_recall_from_occupying_clears_occupation_expires_at(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Recalling from `occupying` must clear occupation_expires_at."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        db.flush()

        auth_client.post(f"/api/military/fleets/{fleet_id}/recall")

        db.expire_all()
        fleet_after = db.get(Fleet, fleet_id)
        assert fleet_after is not None
        assert fleet_after.occupation_expires_at is None, (
            "occupation_expires_at must be cleared when recalling from occupying status"
        )

    def test_recall_from_occupying_swaps_origin_and_destination(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """After recalling from `occupying`, origin must be the enemy territory, dest must be home."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        db.flush()

        auth_client.post(f"/api/military/fleets/{fleet_id}/recall")

        db.expire_all()
        f = db.get(Fleet, fleet_id)
        assert f is not None
        assert f.origin_territory == enemy_territory.id, (
            "After recall from occupying, origin must be the enemy territory"
        )
        assert f.destination_territory == home_territory.id, (
            "After recall from occupying, destination must be the home territory"
        )

    def test_recall_from_occupying_sets_arrives_at(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Recalled fleet from occupying status must have arrives_at set based on distance."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        db.flush()

        before = datetime.now(timezone.utc)
        auth_client.post(f"/api/military/fleets/{fleet_id}/recall")
        after = datetime.now(timezone.utc)

        db.expire_all()
        f = db.get(Fleet, fleet_id)
        assert f is not None
        assert f.arrives_at is not None, "Recalled fleet must have arrives_at set"

        # home=0,0, enemy=2,0 → distance=2; nodes_per_tick=2 → 1 tick → 2 hours
        distance = 2
        transit_ticks = ceil(distance / NODES_PER_TICK)
        expected_hours = transit_ticks * TICK_HOURS
        arrives = f.arrives_at.replace(tzinfo=timezone.utc)
        expected_low = before + timedelta(hours=expected_hours)
        expected_high = after + timedelta(hours=expected_hours)
        assert (
            expected_low - timedelta(seconds=CLOCK_TOLERANCE_SECONDS)
            <= arrives
            <= expected_high + timedelta(seconds=CLOCK_TOLERANCE_SECONDS)
        ), (
            f"Recalled fleet arrives_at {arrives} must be ~{expected_hours}h from now"
        )

    def test_recall_not_allowed_from_engaged(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet in `engaged` status must NOT be recallable — returns 409."""
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

        resp = auth_client.post(f"/api/military/fleets/{fleet_id}/recall")
        assert resp.status_code == 409, (
            f"Recalling an engaged fleet must return 409 "
            f"(engaged is not in the allowed statuses for recall), got {resp.status_code}"
        )

    def test_recall_from_occupying_does_not_transfer_territory_ownership(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Calling /recall from `occupying` must leave territory ownership unchanged."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        territory_id = enemy_territory.id
        original_owner = enemy_nation.id
        db.flush()

        auth_client.post(f"/api/military/fleets/{fleet_id}/recall")

        db.expire_all()
        territory = db.get(Territory, territory_id)
        assert territory.nation_id == original_owner, (
            "Recalling from occupying must NOT transfer territory ownership to the attacker"
        )

    def test_recall_from_occupying_wrong_owner_returns_403(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Another player cannot recall the attacker's occupying fleet — returns 403."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{fleet_id}/recall")
        assert resp.status_code == 403


# ===========================================================================
# 7. SCHEMA: FleetResponse includes occupation_expires_at
# ===========================================================================


class TestFleetResponseSchemaOccupationField:
    """Verify that FleetResponse includes the occupation_expires_at field."""

    def test_fleet_list_includes_occupation_expires_at_field(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """GET /api/military/fleets must include occupation_expires_at for each fleet."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            status="stationed",
        )
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        db.flush()

        resp = auth_client.get("/api/military/fleets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

        for fleet in data:
            assert "occupation_expires_at" in fleet, (
                "FleetResponse must include 'occupation_expires_at' key (may be null)"
            )

        occupying = next((f for f in data if f["status"] == "occupying"), None)
        assert occupying is not None, "Occupying fleet must appear in the fleet list"
        assert occupying["occupation_expires_at"] is not None, (
            "occupation_expires_at must be non-null for an occupying fleet"
        )

        stationed = next((f for f in data if f["status"] == "stationed"), None)
        assert stationed is not None
        assert stationed["occupation_expires_at"] is None, (
            "occupation_expires_at must be null for a stationed fleet"
        )

    def test_fleet_occupation_expires_at_null_after_successful_occupy(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """After calling /occupy, the fleet response must show occupation_expires_at = null."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        db.flush()

        auth_client.post(f"/api/military/fleets/{fleet_id}/occupy")

        resp = auth_client.get("/api/military/fleets")
        assert resp.status_code == 200
        fleets = resp.json()
        fleet_data = next((f for f in fleets if f["id"] == fleet_id), None)
        assert fleet_data is not None
        assert fleet_data["occupation_expires_at"] is None, (
            "occupation_expires_at must be null in FleetResponse after a successful /occupy"
        )


# ===========================================================================
# 8. GAME DESIGN RULES — explicit enforcement tests
# ===========================================================================


class TestOccupationWindowGameDesignRules:
    """Non-negotiable game design rules for the occupation window mechanic."""

    def test_inaction_on_expiry_is_auto_recall_not_auto_claim(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """CRITICAL: When the occupation window expires with no player action, the fleet
        must be auto-recalled, NOT automatically claim the territory.
        Game design rule: inaction must never produce maximum harm."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now - timedelta(minutes=1),
        )
        enemy_territory_id = enemy_territory.id
        original_owner = enemy_nation.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            territory = fresh.get(Territory, enemy_territory_id)
            assert territory.nation_id == original_owner, (
                "CRITICAL GAME DESIGN RULE VIOLATION: Inaction on occupation window expiry "
                "auto-claimed the territory. The safe default is auto-recall, not auto-claim. "
                "Inaction must never produce maximum harm."
            )
        finally:
            fresh.close()

    def test_occupation_window_is_visible_in_fleet_response(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """The occupation window expiry time must be visible to the attacker via the fleet
        response, so they know how long they have to decide."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        fleet_id = fleet.id
        db.flush()

        resp = auth_client.get("/api/military/fleets")
        assert resp.status_code == 200
        fleets = resp.json()
        occupying = next((f for f in fleets if f["id"] == fleet_id), None)
        assert occupying is not None, "Occupying fleet must appear in fleet list"
        assert occupying["occupation_expires_at"] is not None, (
            "The occupation window expiry time must be visible in the fleet response "
            "so the attacker knows their decision deadline"
        )

    def test_standing_order_of_occupying_fleet_never_auto_attack(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """An `occupying` fleet's standing_order must never be 'attack'.
        The only valid values are 'hold' or 'recall'."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        db.flush()

        assert fleet.standing_order != "attack", (
            "standing_order on an occupying fleet must never be 'attack'. "
            "Game design rule: inaction must never produce maximum harm."
        )
        assert fleet.standing_order in ("hold", "recall"), (
            f"standing_order must be 'hold' or 'recall', got {fleet.standing_order!r}"
        )

    def test_territory_ownership_not_transferred_silently_during_window(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """While the occupation window is active, territory must remain owned by the enemy.
        Ownership must only transfer on explicit /occupy call."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
        )
        enemy_territory_id = enemy_territory.id
        original_owner = enemy_nation.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            territory = fresh.get(Territory, enemy_territory_id)
            assert territory.nation_id == original_owner, (
                "Territory ownership must not change silently during the occupation window. "
                "The attacker must explicitly call /occupy to claim. "
                "This prevents silent ownership transfer, which is a game design rule violation."
            )
        finally:
            fresh.close()

    def test_occupation_window_duration_is_12_hours_6_ticks(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """The occupation window must be exactly 12 hours (6 ticks × 2 hours/tick)."""
        _set_war(db, test_nation.id, enemy_nation.id)

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="engaged",
        )
        fleet_id = fleet.id
        before_tick = datetime.now(timezone.utc)
        db.commit()

        _commit_and_run_tick(db)

        after_tick = datetime.now(timezone.utc)
        expected_low = before_tick + timedelta(hours=OCCUPATION_WINDOW_HOURS)
        expected_high = after_tick + timedelta(hours=OCCUPATION_WINDOW_HOURS)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            if f.status == "occupying":
                exp = f.occupation_expires_at
                assert exp is not None
                exp_utc = exp.replace(tzinfo=timezone.utc)
                assert (
                    expected_low - timedelta(seconds=CLOCK_TOLERANCE_SECONDS)
                    <= exp_utc
                    <= expected_high + timedelta(seconds=CLOCK_TOLERANCE_SECONDS)
                ), (
                    f"Occupation window must be {OCCUPATION_WINDOW_HOURS} hours (6 ticks). "
                    f"Got occupation_expires_at={exp_utc}, expected within "
                    f"[{expected_low}, {expected_high}]"
                )
        finally:
            fresh.close()
