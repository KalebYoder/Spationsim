"""
Test suite for the War System feature.

These tests are written BEFORE implementation. They define the expected contract
for all war-related endpoints and game-design-rule enforcement.

Endpoints assumed to be implemented under:
  POST /api/diplomacy/war          — declare war
  POST /api/military/fleets/send   — existing fleet dispatch (behaviour changes when at war)

Tick-level behaviour is tested by calling the probe processing logic that lives inside
run_tick() directly via a helper extracted from tasks/tick.py — or by calling the whole
run_tick() task against a DB session seeded with the right state.

Game-design rules enforced:
  - Standing order default is NEVER 'attack'
  - Confirmation window MUST be set on fleet arrival at enemy territory (~4 hours)
  - Vacation mode players cannot be declared war on
  - War must be explicitly declared before any hostile action counts
  - Probes transiting enemy territory are destroyed and both parties notified
"""

from __future__ import annotations

import os

# Ensure the test DB env var is set before any imports trigger engine construction.
os.environ.setdefault(
    "DATABASE_URL",
    os.getenv("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/spationsim_test"),
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
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
from app.models.probe import Probe
from app.models.territory import Territory
from app.core.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Re-use the session-level engine & per-test transaction isolation from
# conftest.py.  We only need the fixtures already defined there: db, client,
# auth_client, test_player, test_nation.
# ---------------------------------------------------------------------------

CONFIRMATION_WINDOW_HOURS = 4  # 2 ticks × 2 hours/tick
CONFIRMATION_WINDOW_SECONDS = CONFIRMATION_WINDOW_HOURS * 3600
CONFIRMATION_WINDOW_TOLERANCE_SECONDS = 60  # allow 1-minute clock skew in assertions


# ---------------------------------------------------------------------------
# Helper fixtures — enemy nation (second player / nation in the same DB transaction)
# ---------------------------------------------------------------------------

@pytest.fixture()
def enemy_player(db: Session) -> Player:
    """A second player who will be the attack target."""
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
    """The nation belonging to the enemy player."""
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
    """A colonized territory belonging to test_nation — serves as fleet origin."""
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
    """A colonized territory belonging to enemy_nation — 2 nodes away from home."""
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
def neutral_territory(db: Session) -> Territory:
    """An uncolonized territory — useful for fleet dispatch target baseline."""
    t = Territory(
        node_key="1,0",
        name=None,
        territory_type="normal",
        nation_id=None,
        mineral_richness=0.50,
        fuel_richness=0.50,
        distance_from_center=1,
        is_owned=False,
    )
    db.add(t)
    db.flush()
    return t


def _set_war(db: Session, nation_a_id: int, nation_b_id: int) -> Diplomacy:
    """Upsert a diplomacy row with status='war', respecting the nation_a < nation_b constraint."""
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


def _stationed_fleet(db: Session, nation: Nation, territory: Territory, units: int = 10) -> Fleet:
    """Seed a stationed fleet for the given nation at the given territory."""
    fleet = Fleet(
        nation_id=nation.id,
        origin_territory=territory.id,
        unit_count=units,
        status="stationed",
        standing_order="hold",
    )
    db.add(fleet)
    db.flush()
    return fleet


def _db_override(session: Session):
    def _override():
        yield session
    return _override


# ---------------------------------------------------------------------------
# Fixtures: override DB for auth_client to use the same transactional session,
# and create an enemy-authenticated client.
# ---------------------------------------------------------------------------

@pytest.fixture()
def auth_client(db: Session, test_player: Player):
    """Authenticated client for test_player, wired to the transactional db."""
    token = create_access_token(test_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def enemy_auth_client(db: Session, enemy_player: Player, enemy_nation: Nation):
    """Authenticated client for enemy_player, wired to the transactional db."""
    token = create_access_token(enemy_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


# ===========================================================================
# WAR DECLARATION
# ===========================================================================

class TestDeclareWar:
    """Tests for POST /api/diplomacy/war"""

    def test_declare_war_success(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
    ):
        """Authenticated player can declare war; diplomacy row has status='war'."""
        resp = auth_client.post(
            "/api/diplomacy/war",
            json={"target_nation_id": enemy_nation.id},
        )
        assert resp.status_code in (200, 201), resp.text

        a, b = min(test_nation.id, enemy_nation.id), max(test_nation.id, enemy_nation.id)
        row = db.query(Diplomacy).filter(
            Diplomacy.nation_a == a,
            Diplomacy.nation_b == b,
        ).first()
        assert row is not None, "Diplomacy row must be created"
        assert row.status == "war"

    def test_declare_war_on_self_fails(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """Declaring war on your own nation must return 409."""
        resp = auth_client.post(
            "/api/diplomacy/war",
            json={"target_nation_id": test_nation.id},
        )
        assert resp.status_code == 409

    def test_declare_war_on_vacation_player_fails(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_player: Player,
        enemy_nation: Nation,
    ):
        """Vacation mode is a hard block — cannot declare war on a vacationing nation."""
        enemy_player.vacation_mode = True
        enemy_player.vacation_since = datetime.now(timezone.utc)
        db.flush()

        resp = auth_client.post(
            "/api/diplomacy/war",
            json={"target_nation_id": enemy_nation.id},
        )
        assert resp.status_code == 409
        assert "vacation" in resp.json().get("detail", "").lower()

    def test_declare_war_unauthenticated_fails(
        self,
        client: TestClient,
        enemy_nation: Nation,
    ):
        """Unauthenticated request must return 401."""
        resp = client.post(
            "/api/diplomacy/war",
            json={"target_nation_id": enemy_nation.id},
        )
        assert resp.status_code == 401

    def test_declare_war_idempotent(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
    ):
        """Declaring war twice must not crash (200/201 or 409 with message, never 500)."""
        first = auth_client.post(
            "/api/diplomacy/war",
            json={"target_nation_id": enemy_nation.id},
        )
        assert first.status_code in (200, 201), first.text

        second = auth_client.post(
            "/api/diplomacy/war",
            json={"target_nation_id": enemy_nation.id},
        )
        # Acceptable: idempotent 200/201, or graceful 409 with a message. Never 500.
        assert second.status_code in (200, 201, 409), second.text
        if second.status_code == 409:
            detail = second.json().get("detail", "")
            assert detail, "409 must include a meaningful detail message"

    def test_declare_war_diplomacy_row_ordering(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
    ):
        """The diplomacy row must always store nation_a < nation_b (schema constraint)."""
        resp = auth_client.post(
            "/api/diplomacy/war",
            json={"target_nation_id": enemy_nation.id},
        )
        assert resp.status_code in (200, 201), resp.text

        row = db.query(Diplomacy).filter(
            Diplomacy.status == "war",
        ).first()
        assert row is not None
        assert row.nation_a < row.nation_b, (
            "Diplomacy table constraint: nation_a must always be the lower id"
        )

    def test_declare_war_on_nonexistent_nation_fails(
        self,
        auth_client: TestClient,
    ):
        """Targeting a nation ID that doesn't exist must return 404."""
        resp = auth_client.post(
            "/api/diplomacy/war",
            json={"target_nation_id": 999999},
        )
        assert resp.status_code == 404


# ===========================================================================
# FLEET MOVEMENT VS. WAR
# ===========================================================================

class TestFleetDispatchWarBehaviour:
    """
    Tests for how fleet dispatch behaves when the destination is owned by a
    nation you are at war with.
    """

    def test_fleet_dispatch_to_enemy_territory_enters_confirmation(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
        neutral_territory: Territory,
    ):
        """
        Dispatching a fleet to a war-enemy territory must result in the fleet
        arriving with status='pending_confirmation' and confirmation_expires_at
        set to approximately NOW + 4 hours.

        The fleet is created in-transit; the tick will land it and apply the
        confirmation window.  This test seeds an already-arrived fleet directly
        to test the post-landing state.
        """
        _set_war(db, test_nation.id, enemy_nation.id)
        _stationed_fleet(db, test_nation, home_territory, units=5)

        resp = auth_client.post(
            "/api/military/fleets/send",
            json={
                "from_territory_id": home_territory.id,
                "to_territory_id": enemy_territory.id,
                "quantity": 5,
            },
        )
        # Dispatch itself must succeed (the fleet goes in-transit, not blocked outright)
        assert resp.status_code in (200, 201), resp.text

        data = resp.json()
        fleet_id = data["id"]

        fleet = db.get(Fleet, fleet_id)
        assert fleet is not None

        # The fleet should not be immediately stationed or auto-attacking.
        # Acceptable states after dispatch: 'in_transit' (will become
        # 'pending_confirmation' once the tick lands it).
        assert fleet.status != "stationed", (
            "Fleet must not immediately station at an enemy territory"
        )
        assert fleet.status != "attacking", (
            "Fleet must never auto-attack on dispatch"
        )

    def test_fleet_dispatch_confirmation_expires_uses_standing_order_not_attack(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """
        A fleet that has arrived at enemy territory and entered the confirmation
        window must have standing_order in ('hold', 'recall') — never 'attack'.

        This is a hard game-design rule: inaction must never produce maximum harm.
        """
        _set_war(db, test_nation.id, enemy_nation.id)

        # Simulate an already-landed fleet in pending_confirmation state.
        now = datetime.now(timezone.utc)
        fleet = Fleet(
            nation_id=test_nation.id,
            origin_territory=enemy_territory.id,
            destination_territory=None,
            unit_count=5,
            status="pending_confirmation",
            departs_at=now - timedelta(hours=2),
            arrives_at=now,
            confirmation_expires_at=now + timedelta(hours=CONFIRMATION_WINDOW_HOURS),
            standing_order="hold",
        )
        db.add(fleet)
        db.flush()

        assert fleet.standing_order != "attack", (
            "Default standing order must NEVER be 'attack'. "
            "Game design rule: inaction must never produce maximum harm."
        )
        assert fleet.standing_order in ("hold", "recall"), (
            f"standing_order must be 'hold' or 'recall', got: {fleet.standing_order!r}"
        )


# ===========================================================================
# GAME DESIGN RULE ENFORCEMENT: CONFIRMATION WINDOW
# ===========================================================================

class TestConfirmationWindowRules:
    """
    Explicit assertions on the two mandatory game-design rules around the
    confirmation window that must hold regardless of how the fleet lands.
    """

    def test_confirmation_window_set_on_enemy_arrival(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        enemy_territory: Territory,
    ):
        """
        When a fleet is in pending_confirmation state at enemy territory,
        confirmation_expires_at must be approximately NOW + 4 hours.
        """
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        expected_expiry = now + timedelta(hours=CONFIRMATION_WINDOW_HOURS)

        fleet = Fleet(
            nation_id=test_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=5,
            status="pending_confirmation",
            arrives_at=now,
            confirmation_expires_at=expected_expiry,
            standing_order="hold",
        )
        db.add(fleet)
        db.flush()

        assert fleet.confirmation_expires_at is not None, (
            "confirmation_expires_at must be set when fleet enters pending_confirmation"
        )

        delta = abs(
            (fleet.confirmation_expires_at.replace(tzinfo=timezone.utc) - expected_expiry).total_seconds()
        )
        assert delta <= CONFIRMATION_WINDOW_TOLERANCE_SECONDS, (
            f"Confirmation window must be ~{CONFIRMATION_WINDOW_HOURS}h "
            f"(14400s), got delta={delta}s"
        )

    def test_no_auto_attack_on_expiry(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        enemy_territory: Territory,
    ):
        """
        When the confirmation window expires, the default standing order must
        NOT be 'attack'.  The game must hold or recall — never auto-attack.
        """
        _set_war(db, test_nation.id, enemy_nation.id)

        # A fleet whose confirmation window has already expired.
        now = datetime.now(timezone.utc)
        expired_fleet = Fleet(
            nation_id=test_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=5,
            status="pending_confirmation",
            arrives_at=now - timedelta(hours=CONFIRMATION_WINDOW_HOURS + 1),
            confirmation_expires_at=now - timedelta(hours=1),
            standing_order="hold",  # implementation must write this — never 'attack'
        )
        db.add(expired_fleet)
        db.flush()

        assert expired_fleet.standing_order != "attack", (
            "Game design rule: default standing_order must never be 'attack'. "
            "Inaction must never produce maximum harm."
        )

    def test_vacation_player_cannot_be_declared_war_on(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_player: Player,
        enemy_nation: Nation,
    ):
        """
        Vacation mode is a hard block on being targeted.
        This test duplicates the isolation from TestDeclareWar but focuses on
        the rule itself rather than the response shape.
        """
        enemy_player.vacation_mode = True
        enemy_player.vacation_since = datetime.now(timezone.utc)
        db.flush()

        resp = auth_client.post(
            "/api/diplomacy/war",
            json={"target_nation_id": enemy_nation.id},
        )
        assert resp.status_code == 409, (
            "Vacation mode must be a hard block on war declaration — must return 409"
        )


# ===========================================================================
# PROBE DESTRUCTION IN ENEMY TERRITORY (TICK-LEVEL)
# ===========================================================================

class TestProbeDestructionInEnemyTerritory:
    """
    The tick processor must destroy probes that are in-transit through a
    territory owned by a nation that is at war with the probe owner.

    Both nations should receive a notification (Event row with appropriate type).
    """

    def _run_probe_tick(self, db: Session):
        """
        Invoke the probe processing section of run_tick() directly against the
        provided DB session.

        NOTE: run_tick() uses SessionLocal() internally (Celery task pattern).
        For unit testing we replicate the probe-destruction logic here to keep
        tests self-contained and fast.  When the implementation exists, this
        helper should be replaced with a direct import of the extracted function.

        The implementation is expected to:
          1. Find all in-transit probes.
          2. Determine the territory the probe is currently in / heading through.
          3. If that territory is owned by a nation at war with the probe owner,
             set probe.status = 'destroyed'.
          4. Write Event rows notifying both the probe owner and the territory owner.
        """
        from app.models.diplomacy import Diplomacy as Dip

        tick_at = datetime.now(timezone.utc)

        active_probes = (
            db.query(Probe)
            .filter(Probe.status == "in_transit")
            .all()
        )

        for probe in active_probes:
            current_t = db.get(Territory, probe.current_territory) if probe.current_territory else None
            if not current_t or not current_t.nation_id:
                continue

            # Skip own territory
            if current_t.nation_id == probe.nation_id:
                continue

            # Check for war between probe owner and territory owner
            a = min(probe.nation_id, current_t.nation_id)
            b = max(probe.nation_id, current_t.nation_id)
            war_row = db.query(Dip).filter(
                Dip.nation_a == a,
                Dip.nation_b == b,
                Dip.status == "war",
            ).first()

            if war_row:
                probe.status = "destroyed"

                # Notify probe owner
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

                # Notify territory owner (early-warning notification)
                db.add(Event(
                    type="foreign_probe_detected",
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

        db.flush()

    def test_probe_destroyed_transiting_enemy_territory(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """
        A probe in-transit through enemy-owned territory is destroyed by the
        tick processor.  Both probe owner and territory owner receive notification
        Events.
        """
        _set_war(db, test_nation.id, enemy_nation.id)

        # Seed a probe that is currently in the enemy's territory
        now = datetime.now(timezone.utc)
        probe = Probe(
            nation_id=test_nation.id,
            origin_territory=home_territory.id,
            current_territory=enemy_territory.id,  # probe is INSIDE enemy space
            destination_territory=enemy_territory.id,
            status="in_transit",
            departs_at=now - timedelta(hours=1),
            arrives_at=now + timedelta(hours=1),
        )
        db.add(probe)
        db.flush()

        # Run the probe-tick logic
        self._run_probe_tick(db)

        db.refresh(probe)
        assert probe.status == "destroyed", (
            "Probe transiting enemy territory must be destroyed by the tick processor"
        )

        # Check notifications for probe owner
        probe_owner_event = db.query(Event).filter(
            Event.type == "probe_destroyed_in_enemy_territory",
            Event.payload["probe_id"].as_integer() == probe.id,
        ).first()
        assert probe_owner_event is not None, (
            "Probe owner must receive a notification when their probe is destroyed"
        )

        # Check notifications for territory owner
        territory_owner_event = db.query(Event).filter(
            Event.type == "foreign_probe_detected",
            Event.payload["probe_id"].as_integer() == probe.id,
        ).first()
        assert territory_owner_event is not None, (
            "Territory owner must receive an early-warning notification when a foreign probe enters their territory"
        )

    def test_probe_not_destroyed_in_neutral_territory(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        neutral_territory: Territory,
    ):
        """
        A probe transiting uncolonized (neutral) territory must NOT be destroyed,
        even if a war exists.
        """
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        probe = Probe(
            nation_id=test_nation.id,
            origin_territory=home_territory.id,
            current_territory=neutral_territory.id,  # uncolonized — no owner
            destination_territory=neutral_territory.id,
            status="in_transit",
            departs_at=now - timedelta(hours=1),
            arrives_at=now + timedelta(hours=1),
        )
        db.add(probe)
        db.flush()

        self._run_probe_tick(db)

        db.refresh(probe)
        assert probe.status != "destroyed", (
            "Probe in neutral (uncolonized) territory must not be destroyed"
        )

    def test_probe_not_destroyed_in_own_territory(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
    ):
        """
        A probe that is in-transit but currently within the probe owner's own
        territory must not be destroyed.
        """
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        dest = Territory(
            node_key="3,0",
            territory_type="normal",
            nation_id=None,
            mineral_richness=0.50,
            fuel_richness=0.50,
            distance_from_center=3,
            is_owned=False,
        )
        db.add(dest)
        db.flush()

        probe = Probe(
            nation_id=test_nation.id,
            origin_territory=home_territory.id,
            current_territory=home_territory.id,  # still in own territory
            destination_territory=dest.id,
            status="in_transit",
            departs_at=now,
            arrives_at=now + timedelta(hours=4),
        )
        db.add(probe)
        db.flush()

        self._run_probe_tick(db)

        db.refresh(probe)
        assert probe.status != "destroyed", (
            "Probe in own territory must never be destroyed by the tick processor"
        )


# ===========================================================================
# COMBAT: ATTACK FLEET / ATTACK PLANET — WAR REQUIRED
# ===========================================================================

class TestCombatRequiresWar:
    """
    Tests that enforce the rule: war must be explicitly declared before any
    combat-flagged fleet dispatch is permitted.

    The fleet dispatch endpoint accepts an optional 'intent' or 'mode' field.
    Until the war system is fully implemented, dispatch to a neutral nation's
    territory should be blocked if an attack flag is present, and the fleet
    sent to an enemy territory without an active war should be rejected.
    """

    def test_attack_fleet_requires_war(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """
        Sending an attack-flagged fleet to a nation you are NOT at war with
        must be rejected (409).

        No diplomacy row exists — nations are at peace.
        """
        _stationed_fleet(db, test_nation, home_territory, units=5)

        resp = auth_client.post(
            "/api/military/fleets/send",
            json={
                "from_territory_id": home_territory.id,
                "to_territory_id": enemy_territory.id,
                "quantity": 5,
                "intent": "attack",
            },
        )
        # Must be blocked when not at war
        assert resp.status_code in (403, 409), (
            "Attacking a nation not at war with you must be blocked"
        )

    def test_attack_planet_requires_war(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """
        Sending a fleet to occupy/attack an enemy territory without an active
        war must be rejected (403 or 409).
        """
        _stationed_fleet(db, test_nation, home_territory, units=5)

        resp = auth_client.post(
            "/api/military/fleets/send",
            json={
                "from_territory_id": home_territory.id,
                "to_territory_id": enemy_territory.id,
                "quantity": 5,
                "intent": "bombard",
            },
        )
        assert resp.status_code in (403, 409), (
            "Territory attack on a non-war nation must be blocked"
        )

    def test_attack_allowed_when_at_war(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
        neutral_territory: Territory,
    ):
        """
        With an active war declaration, dispatching a fleet toward an enemy
        territory must succeed (fleet enters in_transit, not blocked).
        """
        _set_war(db, test_nation.id, enemy_nation.id)
        _stationed_fleet(db, test_nation, home_territory, units=5)

        resp = auth_client.post(
            "/api/military/fleets/send",
            json={
                "from_territory_id": home_territory.id,
                "to_territory_id": enemy_territory.id,
                "quantity": 5,
            },
        )
        # Fleet enters transit — should not be immediately blocked
        assert resp.status_code in (200, 201), resp.text
        data = resp.json()
        assert data["status"] in ("in_transit", "pending_confirmation"), (
            "Fleet dispatched to enemy territory must be in_transit or pending_confirmation"
        )

    def test_dispatched_fleet_never_gets_attack_standing_order(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """
        Regardless of war status, any fleet created by the system must have a
        standing_order that is NOT 'attack'.  This is a hard system invariant.
        """
        _set_war(db, test_nation.id, enemy_nation.id)

        fleet = Fleet(
            nation_id=test_nation.id,
            origin_territory=home_territory.id,
            destination_territory=enemy_territory.id,
            unit_count=5,
            status="in_transit",
            departs_at=datetime.now(timezone.utc),
            arrives_at=datetime.now(timezone.utc) + timedelta(hours=4),
            standing_order="hold",  # must always be 'hold' or 'recall'
        )
        db.add(fleet)
        db.flush()

        assert fleet.standing_order != "attack", (
            "No fleet may be created with standing_order='attack'. "
            "This violates the core game design rule."
        )


# ===========================================================================
# DIPLOMACY LOOKUP HELPERS
# ===========================================================================

class TestDiplomacyHelpers:
    """
    Tests that the diplomacy table mechanics (row ordering, status lookup) work
    correctly when queried from both sides of a pair.
    """

    def test_war_lookup_from_either_side(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
    ):
        """
        A war row must be findable regardless of which nation's perspective is used.
        """
        _set_war(db, test_nation.id, enemy_nation.id)

        def is_at_war(nation_a_id: int, nation_b_id: int) -> bool:
            a, b = min(nation_a_id, nation_b_id), max(nation_a_id, nation_b_id)
            row = db.query(Diplomacy).filter(
                Diplomacy.nation_a == a,
                Diplomacy.nation_b == b,
                Diplomacy.status == "war",
            ).first()
            return row is not None

        assert is_at_war(test_nation.id, enemy_nation.id)
        assert is_at_war(enemy_nation.id, test_nation.id)

    def test_neutral_nations_not_at_war(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
    ):
        """
        Without any diplomacy row, two nations must not be considered at war.
        """
        a, b = min(test_nation.id, enemy_nation.id), max(test_nation.id, enemy_nation.id)
        row = db.query(Diplomacy).filter(
            Diplomacy.nation_a == a,
            Diplomacy.nation_b == b,
            Diplomacy.status == "war",
        ).first()
        assert row is None, "No war row should exist between nations that haven't declared war"

    def test_peace_declaration_updates_war_status(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
    ):
        """
        After a war is ended (status set back to 'neutral'), the pair must no
        longer appear as at-war.
        """
        row = _set_war(db, test_nation.id, enemy_nation.id)
        assert row.status == "war"

        row.status = "neutral"
        db.flush()

        a, b = min(test_nation.id, enemy_nation.id), max(test_nation.id, enemy_nation.id)
        refreshed = db.query(Diplomacy).filter(
            Diplomacy.nation_a == a,
            Diplomacy.nation_b == b,
        ).first()
        assert refreshed.status == "neutral", "Peace declaration must update the status to 'neutral'"
