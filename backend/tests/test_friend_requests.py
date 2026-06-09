"""
Test suite for the friend request flow.

Covers:
  1. Sending a friend request — creates friend_pending, fires event
  2. Accepting a friend request — sets status to friendly for both
  3. Refusing a friend request — sets status back to neutral
  4. Removing a friend — unilateral, no confirmation, sets neutral
  5. Cannot send friend request while at war
  6. friend_pending treated as neutral for fleet dispatch (planet entry blocked)
  7. GET /api/diplomacy/friends returns friends + incoming requests
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
from app.models.diplomacy import Diplomacy
from app.models.event import Event
from app.models.fleet import Fleet
from app.models.nation import Nation
from app.models.player import Player
from app.models.territory import Territory
from app.models.territory_population import TerritoryPopulation
from app.core.security import create_access_token, hash_password
from app.constants import POPULATION_START

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_override(session: Session):
    def _override():
        yield session
    return _override


def _make_player(db: Session, username: str) -> Player:
    p = Player(username=username, email=f"{username}@example.com", password_hash=hash_password("pw"))
    db.add(p)
    db.flush()
    return p


def _make_nation(db: Session, player: Player, name: str) -> Nation:
    n = Nation(player_id=player.id, name=name, minerals=500, fuel=500, currency=2000)
    db.add(n)
    db.flush()
    return n


def _make_territory(db: Session, node_key: str, nation_id: int, is_owned=True) -> Territory:
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


def _set_diplomacy(db: Session, a_id: int, b_id: int, status: str, requested_by: int | None = None) -> None:
    a, b = min(a_id, b_id), max(a_id, b_id)
    row = db.query(Diplomacy).filter(Diplomacy.nation_a == a, Diplomacy.nation_b == b).first()
    if row:
        row.status = status
        row.requested_by = requested_by
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(Diplomacy(
            nation_a=a, nation_b=b, status=status,
            requested_by=requested_by,
            updated_at=datetime.now(timezone.utc),
        ))
    db.flush()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def auth_client(db: Session, test_player: Player):
    token = create_access_token(test_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def other_player(db: Session) -> Player:
    return _make_player(db, "other")


@pytest.fixture()
def other_nation(db: Session, other_player: Player) -> Nation:
    return _make_nation(db, other_player, "Other Nation")


# ===========================================================================
# 1. SENDING A FRIEND REQUEST
# ===========================================================================


class TestSendFriendRequest:

    def test_creates_friend_pending(self, db, auth_client, test_nation, other_nation):
        db.commit()
        resp = auth_client.post(f"/api/diplomacy/{other_nation.id}/friend-request")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "friend_pending"

    def test_requested_by_is_my_nation(self, db, auth_client, test_nation, other_nation):
        db.commit()
        auth_client.post(f"/api/diplomacy/{other_nation.id}/friend-request")
        a, b = min(test_nation.id, other_nation.id), max(test_nation.id, other_nation.id)
        row = db.query(Diplomacy).filter(Diplomacy.nation_a == a, Diplomacy.nation_b == b).first()
        assert row.requested_by == test_nation.id

    def test_fires_friend_request_event(self, db, auth_client, test_nation, other_nation):
        db.commit()
        auth_client.post(f"/api/diplomacy/{other_nation.id}/friend-request")
        event = db.query(Event).filter(Event.type == "friend_request_received").first()
        assert event is not None
        assert event.payload["target_nation_id"] == other_nation.id

    def test_cannot_send_request_to_self(self, db, auth_client, test_nation):
        db.commit()
        resp = auth_client.post(f"/api/diplomacy/{test_nation.id}/friend-request")
        assert resp.status_code == 409

    def test_cannot_send_request_when_at_war(self, db, auth_client, test_nation, other_nation):
        _set_diplomacy(db, test_nation.id, other_nation.id, "war")
        db.commit()
        resp = auth_client.post(f"/api/diplomacy/{other_nation.id}/friend-request")
        assert resp.status_code == 409

    def test_duplicate_request_is_noop(self, db, auth_client, test_nation, other_nation):
        _set_diplomacy(db, test_nation.id, other_nation.id, "friend_pending", requested_by=test_nation.id)
        db.commit()
        resp = auth_client.post(f"/api/diplomacy/{other_nation.id}/friend-request")
        assert resp.status_code == 200
        assert resp.json()["status"] == "friend_pending"


# ===========================================================================
# 2. ACCEPTING A FRIEND REQUEST
# ===========================================================================


class TestAcceptFriendRequest:

    def test_accept_sets_friendly(self, db, auth_client, test_nation, other_nation):
        # other_nation sent a request to test_nation (incoming for test_nation)
        _set_diplomacy(db, test_nation.id, other_nation.id, "friend_pending", requested_by=other_nation.id)
        db.commit()
        resp = auth_client.post(f"/api/diplomacy/{other_nation.id}/accept-friend")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "friendly"

    def test_accept_clears_requested_by(self, db, auth_client, test_nation, other_nation):
        _set_diplomacy(db, test_nation.id, other_nation.id, "friend_pending", requested_by=other_nation.id)
        db.commit()
        auth_client.post(f"/api/diplomacy/{other_nation.id}/accept-friend")
        a, b = min(test_nation.id, other_nation.id), max(test_nation.id, other_nation.id)
        row = db.query(Diplomacy).filter(Diplomacy.nation_a == a, Diplomacy.nation_b == b).first()
        assert row.requested_by is None

    def test_cannot_accept_own_outgoing_request(self, db, auth_client, test_nation, other_nation):
        """Cannot accept a request you sent yourself."""
        _set_diplomacy(db, test_nation.id, other_nation.id, "friend_pending", requested_by=test_nation.id)
        db.commit()
        resp = auth_client.post(f"/api/diplomacy/{other_nation.id}/accept-friend")
        assert resp.status_code == 409

    def test_cannot_accept_when_no_request(self, db, auth_client, test_nation, other_nation):
        db.commit()
        resp = auth_client.post(f"/api/diplomacy/{other_nation.id}/accept-friend")
        assert resp.status_code == 409


# ===========================================================================
# 3. REFUSING A FRIEND REQUEST
# ===========================================================================


class TestRefuseFriendRequest:

    def test_refuse_sets_neutral(self, db, auth_client, test_nation, other_nation):
        _set_diplomacy(db, test_nation.id, other_nation.id, "friend_pending", requested_by=other_nation.id)
        db.commit()
        resp = auth_client.post(f"/api/diplomacy/{other_nation.id}/refuse-friend")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "neutral"

    def test_can_refuse_own_outgoing_to_cancel(self, db, auth_client, test_nation, other_nation):
        """Sender can cancel their own outgoing request."""
        _set_diplomacy(db, test_nation.id, other_nation.id, "friend_pending", requested_by=test_nation.id)
        db.commit()
        resp = auth_client.post(f"/api/diplomacy/{other_nation.id}/refuse-friend")
        assert resp.status_code == 200
        assert resp.json()["status"] == "neutral"


# ===========================================================================
# 4. REMOVING A FRIEND
# ===========================================================================


class TestRemoveFriend:

    def test_remove_sets_neutral(self, db, auth_client, test_nation, other_nation):
        _set_diplomacy(db, test_nation.id, other_nation.id, "friendly")
        db.commit()
        resp = auth_client.post(f"/api/diplomacy/{other_nation.id}/remove-friend")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "neutral"

    def test_remove_when_not_friends_returns_409(self, db, auth_client, test_nation, other_nation):
        db.commit()
        resp = auth_client.post(f"/api/diplomacy/{other_nation.id}/remove-friend")
        assert resp.status_code == 409


# ===========================================================================
# 5. FRIENDS LIST ENDPOINT
# ===========================================================================


class TestFriendsEndpoint:

    def test_get_friends_returns_friendly_nations(self, db, auth_client, test_nation, other_nation):
        _set_diplomacy(db, test_nation.id, other_nation.id, "friendly")
        db.commit()
        resp = auth_client.get("/api/diplomacy/friends")
        assert resp.status_code == 200
        data = resp.json()
        ids = [r["nation_id"] for r in data]
        assert other_nation.id in ids

    def test_get_friends_includes_incoming_requests(self, db, auth_client, test_nation, other_nation):
        """Incoming friend requests appear in the friends endpoint with friend_pending status."""
        _set_diplomacy(db, test_nation.id, other_nation.id, "friend_pending", requested_by=other_nation.id)
        db.commit()
        resp = auth_client.get("/api/diplomacy/friends")
        assert resp.status_code == 200
        data = resp.json()
        entry = next((r for r in data if r["nation_id"] == other_nation.id), None)
        assert entry is not None
        assert entry["status"] == "friend_pending"

    def test_get_friends_excludes_neutral(self, db, auth_client, test_nation, other_nation):
        db.commit()
        resp = auth_client.get("/api/diplomacy/friends")
        assert resp.status_code == 200
        assert resp.json() == []


# ===========================================================================
# 6. FLEET DISPATCH: friend_pending treated as neutral
# ===========================================================================


class TestFriendPendingDispatch:

    def test_dispatch_to_friend_pending_planet_blocked(self, db: Session, auth_client, test_player):
        my_nation = _make_nation(db, test_player, "My Nation")
        my_home = _make_territory(db, "0,0", my_nation.id)
        my_nation.home_territory_id = my_home.id
        fleet = Fleet(nation_id=my_nation.id, origin_territory=my_home.id, unit_count=20, status="stationed")
        db.add(fleet)

        other_p = _make_player(db, "tgt")
        other_n = _make_nation(db, other_p, "Target Nation")
        other_planet = _make_territory(db, "1,0", other_n.id)

        _set_diplomacy(db, my_nation.id, other_n.id, "friend_pending", requested_by=my_nation.id)
        db.flush()
        db.commit()

        resp = auth_client.post("/api/military/fleets/send", json={
            "from_territory_id": my_home.id,
            "to_territory_id": other_planet.id,
            "quantity": 5,
        })
        assert resp.status_code == 409, resp.text

    def test_get_relation_includes_requested_by(self, db, auth_client, test_nation, other_nation):
        """GET /api/diplomacy/{id} returns requested_by so UI can tell direction."""
        _set_diplomacy(db, test_nation.id, other_nation.id, "friend_pending", requested_by=test_nation.id)
        db.commit()
        resp = auth_client.get(f"/api/diplomacy/{other_nation.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "friend_pending"
        assert data["requested_by"] == test_nation.id
