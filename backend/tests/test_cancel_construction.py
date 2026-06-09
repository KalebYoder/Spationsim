"""
Test suite for POST /api/facilities/{facility_id}/cancel

Cancels a facility that is `under_construction` and immediately refunds 100% of the
build cost (minerals, fuel, currency) to the owning nation. The Infrastructure row
is deleted entirely.

Build costs under test (from constants.py FACILITY_COSTS):
    mine:      minerals=60,  fuel=30,  currency=500
    refinery:  minerals=30,  fuel=60,  currency=500
    shipyard:  minerals=150, fuel=60,  currency=2000
    propaganda_office: minerals=500, fuel=250, currency=6000
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
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.db.database import get_db
from app.models.infrastructure import Infrastructure
from app.models.nation import Nation
from app.models.player import Player
from app.models.territory import Territory
from app.models.territory_population import TerritoryPopulation
from app.core.security import create_access_token, hash_password
from app.constants import FACILITY_COSTS, POPULATION_START


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_override(session: Session):
    def _override():
        yield session
    return _override


def _make_player(db: Session, username: str = "cancelplayer", email: str = "cancel@example.com") -> Player:
    player = Player(
        username=username,
        email=email,
        password_hash=hash_password("testpassword123"),
    )
    db.add(player)
    db.flush()
    return player


def _make_nation(
    db: Session,
    player: Player,
    minerals: float = 1000.0,
    fuel: float = 1000.0,
    currency: float = 5000.0,
) -> Nation:
    nation = Nation(
        player_id=player.id,
        name=f"Nation of {player.username}",
        minerals=minerals,
        fuel=fuel,
        currency=currency,
    )
    db.add(nation)
    db.flush()
    return nation


def _make_territory(
    db: Session,
    node_key: str,
    nation_id: int | None = None,
    is_owned: bool = True,
) -> Territory:
    t = Territory(
        node_key=node_key,
        name=f"Planet {node_key}",
        territory_type="normal",
        nation_id=nation_id,
        mineral_richness=2,
        fuel_richness=2,
        distance_from_center=1,
        is_owned=is_owned,
        owned_at=datetime.now(timezone.utc) if is_owned else None,
    )
    db.add(t)
    db.flush()
    db.add(TerritoryPopulation(territory_id=t.id, current=POPULATION_START * 10))
    db.flush()
    return t


def _make_facility(
    db: Session,
    territory_id: int,
    facility_type: str = "mine",
    status: str = "under_construction",
) -> Infrastructure:
    infra = Infrastructure(
        territory_id=territory_id,
        type=facility_type,
        status=status,
        completes_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    db.add(infra)
    db.flush()
    return infra


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def auth_client(db: Session, test_player: Player):
    """Authenticated client wired to the shared test DB session."""
    token = create_access_token(test_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def nation_and_territory(db: Session, test_player: Player):
    """
    Provides a nation with ample resources and one colonized territory.
    Minerals/fuel/currency are set high enough that any full refund is
    measurable as a clean delta.
    """
    nation = _make_nation(db, test_player, minerals=500.0, fuel=500.0, currency=3000.0)
    territory = _make_territory(db, "cancel-home-001", nation_id=nation.id)
    nation.home_territory_id = territory.id
    db.flush()
    return nation, territory


@pytest.fixture()
def other_player_setup(db: Session):
    """A second player with their own nation and territory (for ownership tests)."""
    other_player = _make_player(db, username="otherplayer", email="other@example.com")
    other_nation = _make_nation(db, other_player)
    other_territory = _make_territory(db, "cancel-other-001", nation_id=other_nation.id)
    other_nation.home_territory_id = other_territory.id
    db.flush()
    return other_player, other_nation, other_territory


# ===========================================================================
# 1. Happy path — 200 OK
# ===========================================================================


class TestCancelUnderConstruction:
    """Cancel succeeds for a facility whose status is `under_construction`."""

    def test_cancel_under_construction_returns_200(
        self, db: Session, auth_client, nation_and_territory
    ):
        nation, territory = nation_and_territory
        facility = _make_facility(db, territory.id, "mine", "under_construction")
        db.commit()

        resp = auth_client.post(f"/api/facilities/{facility.id}/cancel")

        assert resp.status_code == 200, resp.text


# ===========================================================================
# 2-4. Full resource refund
# ===========================================================================


class TestCancelRefunds:
    """After a successful cancel the nation receives 100% of each cost back."""

    def test_cancel_refunds_minerals(
        self, db: Session, auth_client, nation_and_territory
    ):
        nation, territory = nation_and_territory
        mine_cost = FACILITY_COSTS["mine"]
        initial_minerals = float(nation.minerals)
        facility = _make_facility(db, territory.id, "mine", "under_construction")
        db.commit()

        resp = auth_client.post(f"/api/facilities/{facility.id}/cancel")
        assert resp.status_code == 200, resp.text

        db.expire(nation)
        nation = db.get(Nation, nation.id)
        assert float(nation.minerals) == initial_minerals + mine_cost["minerals"], (
            f"Expected minerals {initial_minerals + mine_cost['minerals']}, "
            f"got {nation.minerals}"
        )

    def test_cancel_refunds_fuel(
        self, db: Session, auth_client, nation_and_territory
    ):
        nation, territory = nation_and_territory
        mine_cost = FACILITY_COSTS["mine"]
        initial_fuel = float(nation.fuel)
        facility = _make_facility(db, territory.id, "mine", "under_construction")
        db.commit()

        resp = auth_client.post(f"/api/facilities/{facility.id}/cancel")
        assert resp.status_code == 200, resp.text

        db.expire(nation)
        nation = db.get(Nation, nation.id)
        assert float(nation.fuel) == initial_fuel + mine_cost["fuel"], (
            f"Expected fuel {initial_fuel + mine_cost['fuel']}, "
            f"got {nation.fuel}"
        )

    def test_cancel_refunds_currency(
        self, db: Session, auth_client, nation_and_territory
    ):
        nation, territory = nation_and_territory
        mine_cost = FACILITY_COSTS["mine"]
        initial_currency = float(nation.currency)
        facility = _make_facility(db, territory.id, "mine", "under_construction")
        db.commit()

        resp = auth_client.post(f"/api/facilities/{facility.id}/cancel")
        assert resp.status_code == 200, resp.text

        db.expire(nation)
        nation = db.get(Nation, nation.id)
        assert float(nation.currency) == initial_currency + mine_cost["currency"], (
            f"Expected currency {initial_currency + mine_cost['currency']}, "
            f"got {nation.currency}"
        )


# ===========================================================================
# 5. Facility record is deleted
# ===========================================================================


class TestCancelDeletesFacility:
    """The Infrastructure row must be gone after a successful cancel."""

    def test_cancel_deletes_facility(
        self, db: Session, auth_client, nation_and_territory
    ):
        nation, territory = nation_and_territory
        facility = _make_facility(db, territory.id, "mine", "under_construction")
        facility_id = facility.id
        db.commit()

        resp = auth_client.post(f"/api/facilities/{facility_id}/cancel")
        assert resp.status_code == 200, resp.text

        db.expire_all()
        remaining = db.get(Infrastructure, facility_id)
        assert remaining is None, (
            f"Expected facility {facility_id} to be deleted, but it still exists "
            f"with status={remaining.status if remaining else 'N/A'}"
        )


# ===========================================================================
# 6-7. Wrong status → 409
# ===========================================================================


class TestCancelWrongStatus:
    """Cancelling a facility that is not `under_construction` must return 409."""

    def test_cancel_active_facility_returns_409(
        self, db: Session, auth_client, nation_and_territory
    ):
        nation, territory = nation_and_territory
        facility = _make_facility(db, territory.id, "mine", "active")
        db.commit()

        resp = auth_client.post(f"/api/facilities/{facility.id}/cancel")

        assert resp.status_code == 409, (
            f"Expected 409 for active facility, got {resp.status_code}: {resp.text}"
        )

    def test_cancel_demolishing_facility_returns_409(
        self, db: Session, auth_client, nation_and_territory
    ):
        nation, territory = nation_and_territory
        facility = _make_facility(db, territory.id, "mine", "demolishing")
        db.commit()

        resp = auth_client.post(f"/api/facilities/{facility.id}/cancel")

        assert resp.status_code == 409, (
            f"Expected 409 for demolishing facility, got {resp.status_code}: {resp.text}"
        )

    def test_cancel_active_facility_does_not_delete_it(
        self, db: Session, auth_client, nation_and_territory
    ):
        """When a 409 is returned the facility record must remain intact."""
        nation, territory = nation_and_territory
        facility = _make_facility(db, territory.id, "mine", "active")
        facility_id = facility.id
        db.commit()

        auth_client.post(f"/api/facilities/{facility_id}/cancel")

        db.expire_all()
        remaining = db.get(Infrastructure, facility_id)
        assert remaining is not None, "Active facility must not be deleted on a rejected cancel"
        assert remaining.status == "active"


# ===========================================================================
# 8. Ownership enforcement → 403
# ===========================================================================


class TestCancelOwnership:
    """A player must not be able to cancel another player's facility."""

    def test_cancel_wrong_owner_returns_403(
        self, db: Session, auth_client, other_player_setup
    ):
        _, other_nation, other_territory = other_player_setup
        facility = _make_facility(db, other_territory.id, "mine", "under_construction")
        db.commit()

        resp = auth_client.post(f"/api/facilities/{facility.id}/cancel")

        assert resp.status_code == 403, (
            f"Expected 403 for facility owned by another nation, got {resp.status_code}"
        )

    def test_cancel_wrong_owner_does_not_refund_attacker(
        self, db: Session, auth_client, test_player, other_player_setup
    ):
        """No resources must be credited to the requesting nation on a rejected 403."""
        _, other_nation, other_territory = other_player_setup
        # Give test player a nation so we can check its resources
        my_nation = _make_nation(db, test_player, minerals=100.0, fuel=100.0, currency=1000.0)
        facility = _make_facility(db, other_territory.id, "mine", "under_construction")
        db.commit()

        auth_client.post(f"/api/facilities/{facility.id}/cancel")

        db.expire(my_nation)
        my_nation = db.get(Nation, my_nation.id)
        assert float(my_nation.minerals) == 100.0
        assert float(my_nation.fuel) == 100.0
        assert float(my_nation.currency) == 1000.0


# ===========================================================================
# 9. Non-existent facility → 404
# ===========================================================================


class TestCancelNotFound:
    """Requesting cancellation of a non-existent facility ID must return 404."""

    def test_cancel_nonexistent_returns_404(
        self, db: Session, auth_client, nation_and_territory
    ):
        nation, territory = nation_and_territory
        db.commit()

        resp = auth_client.post("/api/facilities/999999/cancel")

        assert resp.status_code == 404, (
            f"Expected 404 for non-existent facility, got {resp.status_code}"
        )


# ===========================================================================
# 10. Auth enforcement → 401
# ===========================================================================


class TestCancelAuthEnforcement:
    """Unauthenticated requests must be rejected with 401."""

    def test_cancel_unauthenticated_returns_401(
        self, db: Session, test_player: Player
    ):
        # Use a bare (unauthenticated) client — no session cookie
        app.dependency_overrides[get_db] = _db_override(db)
        try:
            with TestClient(app, raise_server_exceptions=True) as unauthenticated:
                nation = _make_nation(db, test_player)
                territory = _make_territory(db, "unauth-cancel-001", nation_id=nation.id)
                facility = _make_facility(db, territory.id, "mine", "under_construction")
                db.commit()

                resp = unauthenticated.post(f"/api/facilities/{facility.id}/cancel")

            assert resp.status_code == 401, (
                f"Expected 401 for unauthenticated request, got {resp.status_code}"
            )
        finally:
            app.dependency_overrides.clear()


# ===========================================================================
# 11. Mine — exact per-resource refund amounts
# ===========================================================================


class TestCancelMineExactRefund:
    """
    Mine build cost: minerals=60, fuel=30, currency=500.
    Starting nation resources: minerals=0, fuel=0, currency=0 so the refund
    values are the exact amounts credited, with no noise from existing stocks.
    """

    def test_cancel_mine_full_refund(
        self, db: Session, test_player: Player
    ):
        # Start with zero resources so refund amount == final balance exactly
        nation = _make_nation(db, test_player, minerals=0.0, fuel=0.0, currency=0.0)
        territory = _make_territory(db, "mine-refund-001", nation_id=nation.id)
        nation.home_territory_id = territory.id
        facility = _make_facility(db, territory.id, "mine", "under_construction")
        db.commit()

        token = create_access_token(test_player.id)
        app.dependency_overrides[get_db] = _db_override(db)
        try:
            with TestClient(app, raise_server_exceptions=True) as c:
                c.cookies.set("session", token)
                resp = c.post(f"/api/facilities/{facility.id}/cancel")
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text

        db.expire(nation)
        nation = db.get(Nation, nation.id)
        mine_cost = FACILITY_COSTS["mine"]
        assert float(nation.minerals) == mine_cost["minerals"], (
            f"mine cancel: expected minerals={mine_cost['minerals']}, got {nation.minerals}"
        )
        assert float(nation.fuel) == mine_cost["fuel"], (
            f"mine cancel: expected fuel={mine_cost['fuel']}, got {nation.fuel}"
        )
        assert float(nation.currency) == mine_cost["currency"], (
            f"mine cancel: expected currency={mine_cost['currency']}, got {nation.currency}"
        )


# ===========================================================================
# 12. Shipyard — exact per-resource refund amounts
# ===========================================================================


class TestCancelShipyardExactRefund:
    """
    Shipyard build cost: minerals=150, fuel=60, currency=2000.
    Starting nation resources: minerals=0, fuel=0, currency=0 so the refund
    values are the exact amounts credited with no prior-balance noise.
    """

    def test_cancel_shipyard_full_refund(
        self, db: Session, test_player: Player
    ):
        nation = _make_nation(db, test_player, minerals=0.0, fuel=0.0, currency=0.0)
        territory = _make_territory(db, "sy-refund-001", nation_id=nation.id)
        nation.home_territory_id = territory.id
        facility = _make_facility(db, territory.id, "shipyard", "under_construction")
        db.commit()

        token = create_access_token(test_player.id)
        app.dependency_overrides[get_db] = _db_override(db)
        try:
            with TestClient(app, raise_server_exceptions=True) as c:
                c.cookies.set("session", token)
                resp = c.post(f"/api/facilities/{facility.id}/cancel")
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text

        db.expire(nation)
        nation = db.get(Nation, nation.id)
        sy_cost = FACILITY_COSTS["shipyard"]
        assert float(nation.minerals) == sy_cost["minerals"], (
            f"shipyard cancel: expected minerals={sy_cost['minerals']}, got {nation.minerals}"
        )
        assert float(nation.fuel) == sy_cost["fuel"], (
            f"shipyard cancel: expected fuel={sy_cost['fuel']}, got {nation.fuel}"
        )
        assert float(nation.currency) == sy_cost["currency"], (
            f"shipyard cancel: expected currency={sy_cost['currency']}, got {nation.currency}"
        )


# ===========================================================================
# Extra: idempotency / double-cancel prevention
# ===========================================================================


class TestCancelIdempotency:
    """
    Cancelling the same facility twice must not double-refund resources.
    The second request should return 404 (facility no longer exists).
    """

    def test_cancel_twice_second_call_returns_404(
        self, db: Session, auth_client, nation_and_territory
    ):
        nation, territory = nation_and_territory
        facility = _make_facility(db, territory.id, "mine", "under_construction")
        db.commit()

        first = auth_client.post(f"/api/facilities/{facility.id}/cancel")
        assert first.status_code == 200, first.text

        second = auth_client.post(f"/api/facilities/{facility.id}/cancel")
        assert second.status_code == 404, (
            f"Second cancel of the same facility should return 404, got {second.status_code}"
        )

    def test_cancel_twice_does_not_double_refund_minerals(
        self, db: Session, auth_client, nation_and_territory
    ):
        nation, territory = nation_and_territory
        mine_cost = FACILITY_COSTS["mine"]
        initial_minerals = float(nation.minerals)
        facility = _make_facility(db, territory.id, "mine", "under_construction")
        db.commit()

        auth_client.post(f"/api/facilities/{facility.id}/cancel")
        auth_client.post(f"/api/facilities/{facility.id}/cancel")

        db.expire(nation)
        nation = db.get(Nation, nation.id)
        expected = initial_minerals + mine_cost["minerals"]
        assert float(nation.minerals) == expected, (
            f"Double-cancel must not double the refund: "
            f"expected minerals={expected}, got {nation.minerals}"
        )
