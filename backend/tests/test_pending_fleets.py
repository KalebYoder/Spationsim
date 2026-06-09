"""
Test suite for two new features:

Feature 1: GET /api/military/fleets/pending-at-mine
  Returns all fleets in `pending_confirmation` status whose destination_territory
  is owned by the authenticated player's nation.  This is the defender's view of
  incoming fleets that are sitting in their confirmation window.

Feature 2: GET /api/notifications now includes `threat_count`
  The existing endpoint gains a `threat_count` field counting fleets in
  `pending_confirmation` at territories owned by the authenticated player's nation.

All tests in this file FAIL until both features are implemented.

Game design rules enforced:
  - Defender visibility: the endpoint exists specifically so the defender can see
    the fleet during its confirmation window (non-negotiable design requirement).
  - Inaction safety: threat_count lets the defender know they need to act —
    this supports the "visible to defender during window" contract.
  - Standing order default: any fleet created here uses standing_order='hold',
    never 'attack'.
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
from app.models.fleet import Fleet
from app.models.nation import Nation
from app.models.player import Player
from app.models.territory import Territory
from app.core.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Confirmation window is 2 ticks × 2 hours = 4 hours
CONFIRMATION_WINDOW_HOURS = 4

# All non-self statuses that the endpoint must NOT return
OTHER_STATUSES = ("stationed", "in_transit", "holding", "engaged", "post_battle_choice")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _db_override(session: Session):
    def _inner():
        yield session
    return _inner


def _make_territory(
    db: Session,
    *,
    node_key: str,
    nation_id: int | None = None,
    is_owned: bool = True,
    distance_from_center: int = 1,
) -> Territory:
    t = Territory(
        node_key=node_key,
        name=f"Territory {node_key}",
        territory_type="normal",
        nation_id=nation_id,
        mineral_richness=1.00,
        fuel_richness=1.00,
        distance_from_center=distance_from_center,
        is_owned=is_owned,
        owned_at=datetime.now(timezone.utc) if is_owned else None,
    )
    db.add(t)
    db.flush()
    return t


def _make_fleet(
    db: Session,
    *,
    nation_id: int,
    origin_id: int,
    dest_id: int | None = None,
    status: str,
    unit_count: int = 10,
    standing_order: str = "hold",
    confirmation_expires_at: datetime | None = None,
) -> Fleet:
    fleet = Fleet(
        nation_id=nation_id,
        origin_territory=origin_id,
        destination_territory=dest_id,
        unit_count=unit_count,
        status=status,
        standing_order=standing_order,
        confirmation_expires_at=confirmation_expires_at,
    )
    db.add(fleet)
    db.flush()
    return fleet


def _pending_expiry() -> datetime:
    """A valid confirmation window expiry: NOW + 4 hours."""
    return datetime.now(timezone.utc) + timedelta(hours=CONFIRMATION_WINDOW_HOURS)


# ---------------------------------------------------------------------------
# Module-level fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def defender_player(db: Session) -> Player:
    player = Player(
        username="defenderplayer",
        email="defender@example.com",
        password_hash=hash_password("defenderpassword123"),
    )
    db.add(player)
    db.flush()
    return player


@pytest.fixture()
def defender_nation(db: Session, defender_player: Player) -> Nation:
    nation = Nation(
        player_id=defender_player.id,
        name="Defender Nation",
        minerals=1000.00,
        fuel=1000.00,
        currency=500.00,
    )
    db.add(nation)
    db.flush()
    return nation


@pytest.fixture()
def attacker_player(db: Session) -> Player:
    player = Player(
        username="attackerplayer",
        email="attacker@example.com",
        password_hash=hash_password("attackerpassword456"),
    )
    db.add(player)
    db.flush()
    return player


@pytest.fixture()
def attacker_nation(db: Session, attacker_player: Player) -> Nation:
    nation = Nation(
        player_id=attacker_player.id,
        name="Attacker Nation",
        minerals=1000.00,
        fuel=1000.00,
        currency=500.00,
    )
    db.add(nation)
    db.flush()
    return nation


@pytest.fixture()
def third_player(db: Session) -> Player:
    player = Player(
        username="thirdplayer",
        email="third@example.com",
        password_hash=hash_password("thirdpassword789"),
    )
    db.add(player)
    db.flush()
    return player


@pytest.fixture()
def third_nation(db: Session, third_player: Player) -> Nation:
    nation = Nation(
        player_id=third_player.id,
        name="Third Nation",
        minerals=500.00,
        fuel=500.00,
        currency=200.00,
    )
    db.add(nation)
    db.flush()
    return nation


@pytest.fixture()
def defender_territory(db: Session, defender_nation: Nation) -> Territory:
    return _make_territory(db, node_key="2,0", nation_id=defender_nation.id)


@pytest.fixture()
def attacker_home(db: Session, attacker_nation: Nation) -> Territory:
    return _make_territory(db, node_key="0,0", nation_id=attacker_nation.id, distance_from_center=0)


@pytest.fixture()
def third_territory(db: Session, third_nation: Nation) -> Territory:
    return _make_territory(db, node_key="4,0", nation_id=third_nation.id, distance_from_center=4)


# Authenticated clients for each player role
@pytest.fixture()
def defender_client(db: Session, defender_player: Player, defender_nation: Nation) -> TestClient:
    token = create_access_token(defender_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def attacker_client(db: Session, attacker_player: Player, attacker_nation: Nation) -> TestClient:
    token = create_access_token(attacker_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def unauthenticated_client(db: Session) -> TestClient:
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


# ===========================================================================
# Feature 1: GET /api/military/fleets/pending-at-mine
# ===========================================================================


class TestPendingFleetsAtMine:
    """
    Tests for GET /api/military/fleets/pending-at-mine.

    This endpoint is the defender's threat-assessment view.  It returns all
    fleets in `pending_confirmation` status whose destination_territory belongs
    to the authenticated player's nation.

    Game design contract: during the confirmation window the fleet MUST be
    visible to the defender.  This endpoint fulfils that contract.
    """

    # -----------------------------------------------------------------------
    # Happy path
    # -----------------------------------------------------------------------

    def test_empty_list_when_no_pending_fleets(
        self,
        defender_client: TestClient,
        db: Session,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        When no fleet is in pending_confirmation at any owned territory, the
        endpoint must return an empty list with HTTP 200.
        """
        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list), "Response must be a JSON array"
        assert data == [], (
            f"Expected empty list when no pending fleets exist, got {data}"
        )

    def test_returns_fleet_pending_at_own_territory(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        A fleet in pending_confirmation whose destination is an owned territory
        must appear in the response.

        Game design rule: fleet must be visible to the defender during the
        confirmation window.
        """
        fleet = _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) == 1, f"Expected 1 fleet, got {len(data)}: {data}"
        assert data[0]["id"] == fleet.id

    def test_response_includes_required_fields(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        Each fleet object in the response must include the fields documented
        in the feature spec: id, unit_count, nation_id (attacker),
        destination_territory_id, confirmation_expires_at, and status.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            unit_count=25,
            confirmation_expires_at=_pending_expiry(),
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) == 1
        fleet_obj = data[0]

        assert "id" in fleet_obj, "Response must include 'id'"
        assert "unit_count" in fleet_obj, "Response must include 'unit_count'"
        assert "nation_id" in fleet_obj, "Response must include 'nation_id' (attacker nation)"
        assert "destination_territory_id" in fleet_obj, "Response must include 'destination_territory_id'"
        assert "confirmation_expires_at" in fleet_obj, "Response must include 'confirmation_expires_at'"
        assert "status" in fleet_obj, "Response must include 'status'"

    def test_status_field_is_pending_confirmation(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        Every fleet returned by this endpoint must have status='pending_confirmation'.
        The endpoint is exclusively for fleets inside the confirmation window.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200
        for fleet_obj in resp.json():
            assert fleet_obj["status"] == "pending_confirmation", (
                f"All returned fleets must have status='pending_confirmation', "
                f"got {fleet_obj['status']!r}"
            )

    def test_nation_id_field_is_attacker_not_defender(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        The nation_id field in each response object must be the attacking
        nation's ID, not the defender's.
        """
        fleet = _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["nation_id"] == attacker_nation.id, (
            f"nation_id must be the attacker's nation id ({attacker_nation.id}), "
            f"got {data[0]['nation_id']}"
        )
        assert data[0]["nation_id"] != defender_nation.id

    def test_confirmation_expires_at_is_iso_string(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        confirmation_expires_at must be a non-null ISO 8601 string for every
        fleet in this list (by definition: only pending_confirmation fleets
        with an active window are returned).
        """
        expiry = _pending_expiry()
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=expiry,
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        raw = data[0]["confirmation_expires_at"]
        assert raw is not None, "confirmation_expires_at must not be null for a pending fleet"
        # Must be parseable as an ISO datetime
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        assert parsed > datetime.now(timezone.utc), (
            "confirmation_expires_at must be in the future for an active window"
        )

    def test_unit_count_matches_seeded_fleet(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """The unit_count field must match the actual fleet size."""
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            unit_count=42,
            confirmation_expires_at=_pending_expiry(),
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200
        assert resp.json()[0]["unit_count"] == 42

    def test_destination_territory_id_matches_seeded_fleet(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """destination_territory_id in the response must match the fleet's destination."""
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200
        assert resp.json()[0]["destination_territory_id"] == defender_territory.id

    # -----------------------------------------------------------------------
    # Multiple fleet scenarios
    # -----------------------------------------------------------------------

    def test_returns_multiple_pending_fleets_at_own_territories(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        When multiple fleets are pending at owned territories, all of them
        must be returned.
        """
        # Second owned territory for the defender
        second_territory = _make_territory(
            db,
            node_key="3,0",
            nation_id=defender_nation.id,
            distance_from_center=3,
        )

        fleet1 = _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            unit_count=10,
            confirmation_expires_at=_pending_expiry(),
        )
        fleet2 = _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=second_territory.id,
            status="pending_confirmation",
            unit_count=20,
            confirmation_expires_at=_pending_expiry(),
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200
        data = resp.json()
        returned_ids = {f["id"] for f in data}
        assert len(data) == 2, (
            f"Expected 2 pending fleets, got {len(data)}: {data}"
        )
        assert fleet1.id in returned_ids
        assert fleet2.id in returned_ids

    # -----------------------------------------------------------------------
    # Filtering: other nations' territories must be excluded
    # -----------------------------------------------------------------------

    def test_does_not_return_fleets_at_other_nations_territories(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        third_nation: Nation,
        third_territory: Territory,
        defender_nation: Nation,
    ):
        """
        A fleet in pending_confirmation at a third nation's territory must NOT
        appear in the defender's response.  The defender can only see fleets
        targeting their own territories.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=third_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data == [], (
            "Fleets pending at other nations' territories must not appear in this response"
        )

    def test_mixed_territories_only_own_returned(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
        third_nation: Nation,
        third_territory: Territory,
    ):
        """
        Given two pending fleets — one at the defender's territory and one at a
        third party's territory — only the fleet at the defender's territory is
        returned.
        """
        own_fleet = _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=third_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1, (
            f"Only the fleet at the own territory should be returned, got {len(data)}"
        )
        assert data[0]["id"] == own_fleet.id

    # -----------------------------------------------------------------------
    # Filtering: wrong status must be excluded
    # -----------------------------------------------------------------------

    def test_does_not_return_stationed_fleet_at_own_territory(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        A fleet with status='stationed' at an owned territory must NOT be
        returned; only pending_confirmation fleets qualify.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=defender_territory.id,
            status="stationed",
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200
        assert resp.json() == [], (
            "stationed fleet must not appear in pending-at-mine results"
        )

    def test_does_not_return_in_transit_fleet_destined_for_own_territory(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        A fleet in_transit towards an owned territory must NOT be returned;
        the confirmation window has not yet opened.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="in_transit",
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200
        assert resp.json() == [], (
            "in_transit fleet must not appear in pending-at-mine results"
        )

    def test_does_not_return_holding_fleet_at_own_territory(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        A fleet in 'holding' status (confirmation window has expired, attacker
        chose hold) at an owned territory must NOT be returned — the window is closed.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=defender_territory.id,
            dest_id=defender_territory.id,
            status="holding",
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200
        assert resp.json() == [], (
            "holding fleet must not appear in pending-at-mine results"
        )

    def test_does_not_return_engaged_fleet_at_own_territory(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        A fleet in 'engaged' status at an owned territory must NOT be returned;
        the confirmation window phase is over.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="engaged",
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200
        assert resp.json() == [], (
            "engaged fleet must not appear in pending-at-mine results"
        )

    @pytest.mark.parametrize("bad_status", list(OTHER_STATUSES))
    def test_does_not_return_non_pending_status(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
        bad_status: str,
    ):
        """
        Parametrized: none of the non-pending_confirmation statuses should
        cause a fleet to appear in this endpoint's results, even if its
        destination is an owned territory.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status=bad_status,
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200
        data = resp.json()
        assert data == [], (
            f"Fleet with status={bad_status!r} must not appear in pending-at-mine results"
        )

    # -----------------------------------------------------------------------
    # Isolation between players
    # -----------------------------------------------------------------------

    def test_attacker_does_not_see_fleets_pending_at_defender_territory(
        self,
        attacker_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        The attacker's own fleet pending at the defender's territory must NOT
        appear in the attacker's pending-at-mine response (it's not their territory).
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )

        resp = attacker_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200
        assert resp.json() == [], (
            "The attacker should not see their own fleet in pending-at-mine; "
            "that territory belongs to the defender"
        )

    def test_only_fleets_targeting_own_territories_returned_not_own_fleets(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        The defender's own fleet in pending_confirmation (e.g. it sent a fleet
        somewhere and it's in the window) at a non-owned territory must NOT
        appear.  The filter is strictly by destination ownership, not by whether
        the fleet belongs to the authenticated nation.
        """
        # Seed an extra territory owned by attacker as a destination
        attacker_second = _make_territory(
            db,
            node_key="5,0",
            nation_id=attacker_nation.id,
            distance_from_center=5,
        )
        # Defender's own fleet pending at the attacker's territory
        _make_fleet(
            db,
            nation_id=defender_nation.id,
            origin_id=defender_territory.id,
            dest_id=attacker_second.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200
        assert resp.json() == [], (
            "Defender's own fleet in pending_confirmation at an enemy territory "
            "must not appear in pending-at-mine (wrong destination ownership)"
        )

    # -----------------------------------------------------------------------
    # Authentication enforcement
    # -----------------------------------------------------------------------

    def test_unauthenticated_request_returns_401(
        self,
        unauthenticated_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        Unauthenticated requests to GET /api/military/fleets/pending-at-mine
        must return HTTP 401.
        """
        # Seed a fleet so the endpoint has data to return if it forgets to check auth
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )

        resp = unauthenticated_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 401, (
            f"Unauthenticated request must return 401, got {resp.status_code}"
        )

    # -----------------------------------------------------------------------
    # Game design rule: standing_order default enforcement
    # -----------------------------------------------------------------------

    def test_pending_fleet_standing_order_is_not_attack(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        CRITICAL game design rule: standing_order for any fleet in the
        pending_confirmation state must NEVER be 'attack'.
        Inaction must never produce maximum harm.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            standing_order="hold",  # must be hold or recall
            confirmation_expires_at=_pending_expiry(),
        )

        resp = defender_client.get("/api/military/fleets/pending-at-mine")
        assert resp.status_code == 200
        for fleet_obj in resp.json():
            so = fleet_obj.get("standing_order")
            assert so != "attack", (
                f"standing_order must never be 'attack' for a pending fleet. Got {so!r}. "
                "Game design rule: inaction must never produce maximum harm."
            )


# ===========================================================================
# Feature 2: GET /api/notifications — threat_count field
# ===========================================================================


class TestNotificationsThreatCount:
    """
    Tests for the `threat_count` field added to GET /api/notifications.

    threat_count = number of fleets in pending_confirmation status whose
    destination_territory is owned by the authenticated player's nation.

    This field directly supports the game design requirement that the defender
    has visibility into incoming fleets during the confirmation window.
    """

    # -----------------------------------------------------------------------
    # Field presence
    # -----------------------------------------------------------------------

    def test_threat_count_field_present_in_response(
        self,
        defender_client: TestClient,
        db: Session,
        defender_nation: Nation,
    ):
        """
        threat_count must be present in the notifications response regardless
        of whether any pending fleets exist.
        """
        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "threat_count" in data, (
            "GET /api/notifications must include 'threat_count' field. "
            "This field does not exist yet — test will fail until implemented."
        )

    # -----------------------------------------------------------------------
    # Existing fields must still be present (regression guard)
    # -----------------------------------------------------------------------

    def test_existing_fields_still_present(
        self,
        defender_client: TestClient,
        db: Session,
        defender_nation: Nation,
    ):
        """
        The addition of threat_count must not remove any existing fields from
        the notifications response.
        """
        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert "mail_unread" in data, "mail_unread must still be present"
        assert "friend_pending" in data, "friend_pending must still be present"
        assert "trade_incoming" in data, "trade_incoming must still be present"

    # -----------------------------------------------------------------------
    # Zero threat count
    # -----------------------------------------------------------------------

    def test_threat_count_zero_when_no_pending_fleets(
        self,
        defender_client: TestClient,
        db: Session,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        When no fleet is in pending_confirmation at any owned territory,
        threat_count must be 0.
        """
        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200
        assert resp.json()["threat_count"] == 0

    def test_threat_count_zero_when_nation_has_no_territories(
        self,
        defender_client: TestClient,
        db: Session,
        defender_nation: Nation,
    ):
        """
        When the nation has no territories at all, threat_count must be 0
        (no territory can be targeted).
        """
        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200
        assert resp.json()["threat_count"] == 0

    # -----------------------------------------------------------------------
    # Non-zero threat count
    # -----------------------------------------------------------------------

    def test_threat_count_one_when_one_pending_fleet(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        When exactly one fleet is in pending_confirmation at an owned territory,
        threat_count must be 1.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )

        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200
        assert resp.json()["threat_count"] == 1

    def test_threat_count_multiple_pending_fleets(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        When multiple fleets are pending at owned territories, threat_count
        must equal the exact count of such fleets.
        """
        second_territory = _make_territory(
            db,
            node_key="3,0",
            nation_id=defender_nation.id,
            distance_from_center=3,
        )

        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=second_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )

        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200
        assert resp.json()["threat_count"] == 2, (
            f"Expected threat_count=2 for two pending fleets, "
            f"got {resp.json()['threat_count']}"
        )

    def test_threat_count_three_pending_fleets(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """Verify threat_count increments correctly with three pending fleets."""
        second = _make_territory(db, node_key="3,0", nation_id=defender_nation.id, distance_from_center=3)
        third = _make_territory(db, node_key="5,0", nation_id=defender_nation.id, distance_from_center=5)

        for dest in (defender_territory, second, third):
            _make_fleet(
                db,
                nation_id=attacker_nation.id,
                origin_id=attacker_home.id,
                dest_id=dest.id,
                status="pending_confirmation",
                confirmation_expires_at=_pending_expiry(),
            )

        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200
        assert resp.json()["threat_count"] == 3

    # -----------------------------------------------------------------------
    # Filtering: fleets at other nations' territories must not count
    # -----------------------------------------------------------------------

    def test_threat_count_excludes_fleets_at_other_nations_territories(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        third_nation: Nation,
        third_territory: Territory,
        defender_nation: Nation,
    ):
        """
        A fleet pending at a third party's territory must NOT increment
        the defender's threat_count.
        """
        # Fleet pending at third party's territory — should not count for defender
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=third_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )

        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200
        assert resp.json()["threat_count"] == 0, (
            "Fleet pending at another nation's territory must not count toward "
            "the defender's threat_count"
        )

    def test_threat_count_mixed_ownership_counts_only_own(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
        third_nation: Nation,
        third_territory: Territory,
    ):
        """
        Given one fleet pending at an owned territory and one pending at a
        third party's territory, threat_count must be 1.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=third_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )

        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200
        assert resp.json()["threat_count"] == 1

    # -----------------------------------------------------------------------
    # Filtering: non-pending_confirmation statuses must not count
    # -----------------------------------------------------------------------

    def test_threat_count_excludes_stationed_fleet_at_own_territory(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        A stationed fleet at an owned territory must not increment threat_count;
        only pending_confirmation counts.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=defender_territory.id,
            status="stationed",
        )

        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200
        assert resp.json()["threat_count"] == 0, (
            "stationed fleet must not increment threat_count"
        )

    def test_threat_count_excludes_in_transit_fleet(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        A fleet in_transit destined for an owned territory must not increment
        threat_count; the confirmation window has not yet opened.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="in_transit",
        )

        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200
        assert resp.json()["threat_count"] == 0, (
            "in_transit fleet must not increment threat_count"
        )

    def test_threat_count_excludes_holding_fleet_at_own_territory(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        A fleet in 'holding' status (window has expired, attacker chose hold)
        must not increment threat_count.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=defender_territory.id,
            dest_id=defender_territory.id,
            status="holding",
        )

        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200
        assert resp.json()["threat_count"] == 0, (
            "holding fleet must not increment threat_count"
        )

    def test_threat_count_excludes_engaged_fleet(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        A fleet in 'engaged' status at an owned territory must not increment
        threat_count; the confirmation window phase is already over.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="engaged",
        )

        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200
        assert resp.json()["threat_count"] == 0, (
            "engaged fleet must not increment threat_count"
        )

    @pytest.mark.parametrize("bad_status", list(OTHER_STATUSES))
    def test_threat_count_zero_for_all_non_pending_statuses(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
        bad_status: str,
    ):
        """
        Parametrized: for every status that is NOT pending_confirmation,
        a fleet at an owned territory must not increment threat_count.
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status=bad_status,
        )

        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200
        assert resp.json()["threat_count"] == 0, (
            f"Fleet with status={bad_status!r} must not contribute to threat_count"
        )

    # -----------------------------------------------------------------------
    # Authentication enforcement
    # -----------------------------------------------------------------------

    def test_notifications_unauthenticated_returns_401(
        self,
        unauthenticated_client: TestClient,
    ):
        """
        Unauthenticated requests to GET /api/notifications must return 401.
        (Regression guard — this should already be true, but must remain true
        after adding threat_count.)
        """
        resp = unauthenticated_client.get("/api/notifications")
        assert resp.status_code == 401, (
            f"Unauthenticated /api/notifications must return 401, got {resp.status_code}"
        )

    # -----------------------------------------------------------------------
    # Correctness when pending + non-pending fleets both exist at own territory
    # -----------------------------------------------------------------------

    def test_threat_count_only_counts_pending_not_all_fleets(
        self,
        defender_client: TestClient,
        db: Session,
        attacker_nation: Nation,
        attacker_home: Territory,
        defender_nation: Nation,
        defender_territory: Territory,
    ):
        """
        When both a pending_confirmation fleet and an in_transit fleet target
        the same owned territory, threat_count must be 1 (only the pending one
        counts).
        """
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=_pending_expiry(),
        )
        _make_fleet(
            db,
            nation_id=attacker_nation.id,
            origin_id=attacker_home.id,
            dest_id=defender_territory.id,
            status="in_transit",
        )

        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200
        assert resp.json()["threat_count"] == 1, (
            "Only pending_confirmation fleets should be counted; "
            f"in_transit fleet must be excluded. Got: {resp.json()['threat_count']}"
        )

    # -----------------------------------------------------------------------
    # threat_count is an integer type
    # -----------------------------------------------------------------------

    def test_threat_count_is_integer(
        self,
        defender_client: TestClient,
        db: Session,
        defender_nation: Nation,
    ):
        """threat_count must be a JSON integer, not a string or float."""
        resp = defender_client.get("/api/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert "threat_count" in data
        assert isinstance(data["threat_count"], int), (
            f"threat_count must be an integer, got {type(data['threat_count'])!r}: "
            f"{data['threat_count']}"
        )
