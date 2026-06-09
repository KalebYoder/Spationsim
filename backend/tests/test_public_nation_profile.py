"""
Test suite for the Public Nation Profile endpoint.

Covers GET /api/nations/{nation_id} — a read-only public endpoint that any
authenticated player can call to inspect another nation's stats.

Expected response shape (PublicNationResponse):
  id: int
  name: str
  flag_color: str
  currency_name: str
  territory_count: int   — colonized territories only (is_owned=True AND nation_id=<id>)
  military: dict[str, int]   — total unit_count per fleet type across ALL fleet statuses

Authentication: required (401 if no session cookie).
The endpoint is otherwise fully public — any authenticated player may view any nation.

Tests written BEFORE implementation.  All tests are expected to fail until the
endpoint, schema, and router registration are in place.
"""

from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    os.getenv("TEST_DATABASE_URL", "postgresql://spationsim:SpationDev2026@db/spationsim_test"),
)
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

from datetime import datetime, timezone

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
# Helpers
# ---------------------------------------------------------------------------


def _db_override(session: Session):
    def _override():
        yield session
    return _override


def _make_territory(
    db: Session,
    nation_id: int | None,
    node_key: str,
    is_owned: bool = True,
    distance_from_center: int = 1,
) -> Territory:
    """Insert a territory and return it."""
    t = Territory(
        node_key=node_key,
        name=f"Planet {node_key}" if is_owned else None,
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
    nation_id: int,
    origin_id: int,
    unit_count: int,
    status: str = "stationed",
    dest_id: int | None = None,
) -> Fleet:
    """Insert a fleet and return it."""
    fleet = Fleet(
        nation_id=nation_id,
        origin_territory=origin_id,
        destination_territory=dest_id,
        unit_count=unit_count,
        status=status,
        standing_order="hold",
    )
    db.add(fleet)
    db.flush()
    return fleet


# ---------------------------------------------------------------------------
# Local fixtures: second player + nation (the "other" nation)
# ---------------------------------------------------------------------------


@pytest.fixture()
def other_player(db: Session) -> Player:
    player = Player(
        username="otherplayer",
        email="other@example.com",
        password_hash=hash_password("otherpassword123"),
    )
    db.add(player)
    db.flush()
    return player


@pytest.fixture()
def other_nation(db: Session, other_player: Player) -> Nation:
    nation = Nation(
        player_id=other_player.id,
        name="Other Nation",
        flag_color="#FF0000",
        currency_name="Stellarmarks",
        minerals=500,
        fuel=500,
    )
    db.add(nation)
    db.flush()
    return nation


@pytest.fixture()
def other_auth_client(db: Session, other_player: Player) -> TestClient:
    """Authenticated client for other_player (Player B)."""
    token = create_access_token(other_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


# auth_client shadows conftest — wires to the same transactional session
@pytest.fixture()
def auth_client(db: Session, test_player: Player) -> TestClient:
    token = create_access_token(test_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


# ===========================================================================
# 1. AUTHENTICATION ENFORCEMENT
# ===========================================================================


class TestAuthEnforcement:
    """GET /api/nations/{nation_id} must require a valid session."""

    def test_unauthenticated_request_returns_401(
        self,
        client: TestClient,
        test_nation: Nation,
    ):
        """Unauthenticated GET /api/nations/{id} must return 401."""
        resp = client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 401, (
            f"Unauthenticated request must return 401, got {resp.status_code}"
        )

    def test_unauthenticated_request_does_not_return_nation_data(
        self,
        client: TestClient,
        test_nation: Nation,
    ):
        """Unauthenticated response must not leak any nation data."""
        resp = client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 401
        data = resp.json()
        # Should not contain any nation fields
        assert "name" not in data or data.get("name") is None or resp.status_code == 401


# ===========================================================================
# 2. ERROR CASES
# ===========================================================================


class TestErrorCases:
    """Proper error responses for bad inputs."""

    def test_nonexistent_nation_returns_404(
        self,
        auth_client: TestClient,
    ):
        """GET /api/nations/999999 must return 404 when no such nation exists."""
        resp = auth_client.get("/api/nations/999999")
        assert resp.status_code == 404, (
            f"Non-existent nation must return 404, got {resp.status_code}"
        )

    def test_nonexistent_nation_404_detail_message_present(
        self,
        auth_client: TestClient,
    ):
        """404 response must include a detail message."""
        resp = auth_client.get("/api/nations/999999")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body, "404 response must include a 'detail' field"
        assert body["detail"], "404 detail must not be empty"


# ===========================================================================
# 3. HAPPY PATH — RESPONSE SHAPE AND FIELD VALUES
# ===========================================================================


class TestResponseShape:
    """Verify the shape and types of PublicNationResponse."""

    def test_returns_200_for_existing_nation(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """GET /api/nations/{id} must return 200 for an existing nation."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, (
            f"Expected 200 for existing nation, got {resp.status_code}: {resp.text}"
        )

    def test_response_contains_id_field(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """Response must include 'id' field matching the requested nation_id."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "id" in data, "PublicNationResponse must include 'id'"
        assert data["id"] == test_nation.id

    def test_response_contains_name_field(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """Response must include 'name' matching the nation's name."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "name" in data, "PublicNationResponse must include 'name'"
        assert data["name"] == test_nation.name

    def test_response_contains_flag_color_field(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """Response must include 'flag_color' matching the nation's flag_color."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "flag_color" in data, "PublicNationResponse must include 'flag_color'"
        assert data["flag_color"] == test_nation.flag_color

    def test_response_contains_currency_name_field(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """Response must include 'currency_name' matching the nation's currency_name."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "currency_name" in data, "PublicNationResponse must include 'currency_name'"
        assert data["currency_name"] == test_nation.currency_name

    def test_response_contains_territory_count_field(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """Response must include 'territory_count' as an integer."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "territory_count" in data, "PublicNationResponse must include 'territory_count'"
        assert isinstance(data["territory_count"], int), (
            f"territory_count must be an int, got {type(data['territory_count'])}"
        )

    def test_response_contains_military_field(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """Response must include 'military' as a dict."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "military" in data, "PublicNationResponse must include 'military'"
        assert isinstance(data["military"], dict), (
            f"military must be a dict, got {type(data['military'])}"
        )

    def test_response_military_contains_starfighter_key(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """military dict must always contain the 'starfighter' key."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "starfighter" in data["military"], (
            "military dict must always contain 'starfighter' key (even when count is 0)"
        )

    def test_response_does_not_include_private_fields(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """Public profile must NOT expose private fields: minerals, fuel, currency, etc."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        private_fields = ("minerals", "fuel", "currency",
                          "probes_reserve", "aggression_lockout_until", "home_territory_id")
        for field in private_fields:
            assert field not in data, (
                f"PublicNationResponse must NOT expose private field '{field}'"
            )


# ===========================================================================
# 4. TERRITORY COUNT
# ===========================================================================


class TestTerritoryCount:
    """territory_count must reflect only colonized territories owned by the nation."""

    def test_territory_count_is_zero_with_no_territories(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """Nation with no territories at all must return territory_count=0."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["territory_count"] == 0, (
            f"Nation with no territories must have territory_count=0, got {data['territory_count']}"
        )

    def test_territory_count_reflects_one_colonized_territory(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """Nation with exactly 1 colonized territory must return territory_count=1."""
        _make_territory(db, test_nation.id, "0,0", is_owned=True)

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["territory_count"] == 1, (
            f"Nation with 1 colonized territory must have territory_count=1, got {data['territory_count']}"
        )

    def test_territory_count_reflects_multiple_colonized_territories(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """Nation with 3 colonized territories must return territory_count=3."""
        _make_territory(db, test_nation.id, "0,0", is_owned=True, distance_from_center=0)
        _make_territory(db, test_nation.id, "1,0", is_owned=True, distance_from_center=1)
        _make_territory(db, test_nation.id, "2,0", is_owned=True, distance_from_center=2)

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["territory_count"] == 3, (
            f"Nation with 3 colonized territories must have territory_count=3, got {data['territory_count']}"
        )

    def test_uncolonized_territories_not_counted(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """Territories with is_owned=False must NOT be counted in territory_count."""
        _make_territory(db, test_nation.id, "0,0", is_owned=True)
        # Add an uncolonized territory — nation_id is set but is_owned=False
        # (edge case: territory assigned to nation but not yet colonized)
        _make_territory(db, test_nation.id, "1,0", is_owned=False)

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["territory_count"] == 1, (
            "Uncolonized territory (is_owned=False) must NOT be counted. "
            f"Expected 1, got {data['territory_count']}"
        )

    def test_unowned_uncolonized_territory_not_counted(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """Unowned, uncolonized territory must not affect any nation's territory_count."""
        _make_territory(db, test_nation.id, "0,0", is_owned=True)
        # Unowned neutral territory
        _make_territory(db, None, "5,5", is_owned=False, distance_from_center=7)

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["territory_count"] == 1, (
            "Neutral unowned territory must not inflate territory_count. "
            f"Expected 1, got {data['territory_count']}"
        )

    def test_territory_count_only_counts_own_nation_territories(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """test_nation's territory_count must not include other_nation's territories."""
        # Give test_nation 1 territory, other_nation 3 territories
        _make_territory(db, test_nation.id, "0,0", is_owned=True, distance_from_center=0)
        _make_territory(db, other_nation.id, "3,0", is_owned=True, distance_from_center=3)
        _make_territory(db, other_nation.id, "4,0", is_owned=True, distance_from_center=4)
        _make_territory(db, other_nation.id, "5,0", is_owned=True, distance_from_center=5)

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["territory_count"] == 1, (
            "territory_count must only include territories belonging to the requested nation. "
            f"Expected 1 (not 4), got {data['territory_count']}"
        )


# ===========================================================================
# 5. MILITARY — STARFIGHTER COUNTS
# ===========================================================================


class TestMilitaryStarfighterCount:
    """military['starfighter'] must aggregate unit_count across all fleets."""

    def test_military_starfighter_is_zero_with_no_fleets(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """Nation with no fleets must have military={'starfighter': 0}."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["military"]["starfighter"] == 0, (
            "Nation with no fleets must have military['starfighter']=0, "
            f"got {data['military']['starfighter']}"
        )

    def test_military_starfighter_key_always_present_even_when_zero(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """'starfighter' key must be present in military even with 0 units."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        military = resp.json()["military"]
        assert "starfighter" in military, (
            "'starfighter' key must always be present in military dict, even when count is 0"
        )
        assert military["starfighter"] == 0

    def test_military_starfighter_reflects_single_stationed_fleet(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """Single stationed fleet with 10 units → military['starfighter']=10."""
        origin = _make_territory(db, test_nation.id, "0,0", is_owned=True)
        _make_fleet(db, test_nation.id, origin.id, unit_count=10, status="stationed")

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["military"]["starfighter"] == 10, (
            "Stationed fleet with 10 units must give military['starfighter']=10, "
            f"got {data['military']['starfighter']}"
        )

    def test_military_starfighter_sums_multiple_fleets(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """Units from multiple fleets must be summed: 10 + 20 + 5 = 35."""
        origin = _make_territory(db, test_nation.id, "0,0", is_owned=True)
        _make_fleet(db, test_nation.id, origin.id, unit_count=10, status="stationed")
        _make_fleet(db, test_nation.id, origin.id, unit_count=20, status="stationed")
        _make_fleet(db, test_nation.id, origin.id, unit_count=5, status="stationed")

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["military"]["starfighter"] == 35, (
            "military['starfighter'] must sum all fleet unit counts (10+20+5=35), "
            f"got {data['military']['starfighter']}"
        )

    def test_military_counts_in_transit_fleets(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """Fleets with status='in_transit' must be counted in military totals."""
        origin = _make_territory(db, test_nation.id, "0,0", is_owned=True)
        dest = _make_territory(db, other_nation.id, "2,0", is_owned=True, distance_from_center=2)
        _make_fleet(db, test_nation.id, origin.id, unit_count=15, status="in_transit", dest_id=dest.id)

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["military"]["starfighter"] == 15, (
            "in_transit fleet units must be counted in military totals, "
            f"got {data['military']['starfighter']}"
        )

    def test_military_counts_pending_confirmation_fleets(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """Fleets with status='pending_confirmation' must be counted in military totals."""
        origin = _make_territory(db, test_nation.id, "0,0", is_owned=True)
        dest = _make_territory(db, other_nation.id, "2,0", is_owned=True, distance_from_center=2)
        _make_fleet(db, test_nation.id, origin.id, unit_count=8, status="pending_confirmation", dest_id=dest.id)

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["military"]["starfighter"] == 8, (
            "pending_confirmation fleet units must be counted in military totals, "
            f"got {data['military']['starfighter']}"
        )

    def test_military_counts_holding_fleets(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """Fleets with status='holding' must be counted in military totals."""
        dest = _make_territory(db, other_nation.id, "2,0", is_owned=True, distance_from_center=2)
        _make_fleet(db, test_nation.id, dest.id, unit_count=12, status="holding")

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["military"]["starfighter"] == 12, (
            "holding fleet units must be counted in military totals, "
            f"got {data['military']['starfighter']}"
        )

    def test_military_counts_engaged_fleets(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """Fleets with status='engaged' must be counted in military totals."""
        dest = _make_territory(db, other_nation.id, "2,0", is_owned=True, distance_from_center=2)
        _make_fleet(db, test_nation.id, dest.id, unit_count=7, status="engaged")

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["military"]["starfighter"] == 7, (
            "engaged fleet units must be counted in military totals, "
            f"got {data['military']['starfighter']}"
        )

    def test_military_sums_across_all_fleet_statuses(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """Units from all fleet statuses must be summed together."""
        origin = _make_territory(db, test_nation.id, "0,0", is_owned=True, distance_from_center=0)
        dest = _make_territory(db, other_nation.id, "2,0", is_owned=True, distance_from_center=2)

        # One fleet per status type
        _make_fleet(db, test_nation.id, origin.id, unit_count=10, status="stationed")
        _make_fleet(db, test_nation.id, origin.id, unit_count=5, status="in_transit", dest_id=dest.id)
        _make_fleet(db, test_nation.id, origin.id, unit_count=3, status="pending_confirmation", dest_id=dest.id)
        _make_fleet(db, test_nation.id, dest.id, unit_count=4, status="holding")
        _make_fleet(db, test_nation.id, dest.id, unit_count=6, status="engaged")

        # 10 + 5 + 3 + 4 + 6 = 28
        expected_total = 28

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["military"]["starfighter"] == expected_total, (
            f"All fleet statuses must be summed: expected {expected_total}, "
            f"got {data['military']['starfighter']}"
        )

    def test_military_only_counts_own_fleets_not_other_nations(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """other_nation's fleets must NOT be counted in test_nation's military total."""
        origin = _make_territory(db, test_nation.id, "0,0", is_owned=True, distance_from_center=0)
        other_origin = _make_territory(db, other_nation.id, "2,0", is_owned=True, distance_from_center=2)

        _make_fleet(db, test_nation.id, origin.id, unit_count=10, status="stationed")
        _make_fleet(db, other_nation.id, other_origin.id, unit_count=999, status="stationed")

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["military"]["starfighter"] == 10, (
            "military total must only include fleets belonging to the requested nation, "
            f"expected 10, got {data['military']['starfighter']}"
        )

    def test_military_starfighter_value_is_integer_type(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """military['starfighter'] must be serialized as an integer."""
        origin = _make_territory(db, test_nation.id, "0,0", is_owned=True)
        _make_fleet(db, test_nation.id, origin.id, unit_count=5, status="stationed")

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        military = resp.json()["military"]
        assert isinstance(military["starfighter"], int), (
            f"military['starfighter'] must be an int, got {type(military['starfighter'])}"
        )


# ===========================================================================
# 6. ISOLATION — PLAYER A VIEWING PLAYER B'S NATION
# ===========================================================================


class TestIsolation:
    """Player A viewing Player B's public profile must see B's data, not A's."""

    def test_player_a_views_player_b_nation_id_is_correct(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """auth_client (Player A) viewing other_nation must receive other_nation's id."""
        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == other_nation.id, (
            f"Viewing other_nation must return id={other_nation.id}, got {data['id']}"
        )
        assert data["id"] != test_nation.id, (
            "Viewing other_nation must not return test_nation's id"
        )

    def test_player_a_views_player_b_name_is_correct(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """auth_client (Player A) viewing other_nation must receive other_nation's name."""
        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["name"] == other_nation.name, (
            f"Expected name={other_nation.name!r}, got {data['name']!r}"
        )
        assert data["name"] != test_nation.name, (
            "Viewing other_nation must not return test_nation's name"
        )

    def test_player_a_views_player_b_territory_count_is_b_not_a(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """territory_count returned must reflect other_nation's territories, not test_nation's."""
        # Give test_nation 1 territory, other_nation 3 territories
        _make_territory(db, test_nation.id, "0,0", is_owned=True, distance_from_center=0)
        _make_territory(db, other_nation.id, "3,0", is_owned=True, distance_from_center=3)
        _make_territory(db, other_nation.id, "4,0", is_owned=True, distance_from_center=4)
        _make_territory(db, other_nation.id, "5,0", is_owned=True, distance_from_center=5)

        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["territory_count"] == 3, (
            f"Viewing other_nation (3 territories) must return territory_count=3, "
            f"got {data['territory_count']}"
        )

    def test_player_a_views_player_b_military_is_b_not_a(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """military returned must reflect other_nation's fleets, not test_nation's."""
        own_origin = _make_territory(db, test_nation.id, "0,0", is_owned=True, distance_from_center=0)
        other_origin = _make_territory(db, other_nation.id, "2,0", is_owned=True, distance_from_center=2)

        # test_nation has 100 fighters; other_nation has 42
        _make_fleet(db, test_nation.id, own_origin.id, unit_count=100, status="stationed")
        _make_fleet(db, other_nation.id, other_origin.id, unit_count=42, status="stationed")

        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["military"]["starfighter"] == 42, (
            "Viewing other_nation must show other_nation's fighters (42), not test_nation's (100). "
            f"Got {data['military']['starfighter']}"
        )

    def test_player_b_views_player_a_nation_correctly(
        self,
        other_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """Player B authenticated client can also view Player A's nation correctly."""
        origin = _make_territory(db, test_nation.id, "0,0", is_owned=True)
        _make_fleet(db, test_nation.id, origin.id, unit_count=20, status="stationed")

        resp = other_auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == test_nation.id
        assert data["name"] == test_nation.name
        assert data["military"]["starfighter"] == 20

    def test_viewing_own_nation_id_works(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """A player can call the public endpoint with their own nation_id — must return 200."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, (
            f"Player viewing their own nation via public endpoint must return 200, "
            f"got {resp.status_code}"
        )
        data = resp.json()
        assert data["id"] == test_nation.id
        assert data["name"] == test_nation.name

    def test_own_nation_profile_does_not_expose_resources(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """Even when viewing your own nation via the public endpoint, resources must not be exposed."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "minerals" not in data, "Public endpoint must not expose minerals even for own nation"
        assert "fuel" not in data, "Public endpoint must not expose fuel even for own nation"
        assert "currency" not in data, "Public endpoint must not expose currency even for own nation"


# ===========================================================================
# 7. FIELD CORRECTNESS — flag_color and currency_name values
# ===========================================================================


class TestFieldCorrectness:
    """Verify that flag_color and currency_name return the exact stored values."""

    def test_flag_color_matches_stored_value(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """flag_color in response must exactly match the stored value for the requested nation."""
        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["flag_color"] == other_nation.flag_color, (
            f"flag_color must match stored value {other_nation.flag_color!r}, "
            f"got {data['flag_color']!r}"
        )

    def test_currency_name_matches_stored_value(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """currency_name in response must exactly match the stored value for the requested nation."""
        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["currency_name"] == other_nation.currency_name, (
            f"currency_name must match stored value {other_nation.currency_name!r}, "
            f"got {data['currency_name']!r}"
        )

    def test_territory_count_is_correct_integer_not_string(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """territory_count must be serialized as an integer, not a string."""
        _make_territory(db, test_nation.id, "0,0", is_owned=True)
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data["territory_count"], int), (
            f"territory_count must be an int, got {type(data['territory_count'])}"
        )

    def test_military_starfighter_count_not_string(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """military['starfighter'] must be an integer, not a string."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        military = resp.json()["military"]
        assert isinstance(military["starfighter"], int), (
            f"military['starfighter'] must be an int (not string), "
            f"got {type(military['starfighter'])}"
        )
