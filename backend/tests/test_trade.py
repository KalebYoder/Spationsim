"""
Test suite for the Trade system.

Covers:
  1. Propose trade — happy path, validation, resource checks, route check
  2. Route check endpoint
  3. Accept (two-click confirmation state machine)
       - First click sets accepted_at
       - Second click too soon → 409
       - Second click after cooldown → sets confirmed_at
       - Both sides confirmed → trade executes, resources transfer
  4. Edit terms — resets all confirmation state
  5. Reject — recipient only
  6. Cancel — proposer only
  7. List trades — returns pending only, both directions
"""

from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    os.getenv("TEST_DATABASE_URL", "postgresql://spationsim:SpationDev2026@db/spationsim_test"),
)
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.db.database import get_db
from app.models.diplomacy import Diplomacy
from app.models.nation import Nation
from app.models.player import Player
from app.models.territory import Territory
from app.models.trade import Trade
from app.core.security import create_access_token, hash_password


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


def _make_nation(db: Session, player: Player, name: str, minerals=5000.0, fuel=5000.0, currency=50000.0) -> Nation:
    n = Nation(player_id=player.id, name=name, minerals=minerals, fuel=fuel, currency=currency)
    db.add(n)
    db.flush()
    return n


def _make_territory(db: Session, node_key: str, nation: Nation) -> Territory:
    t = Territory(
        node_key=node_key,
        nation_id=nation.id,
        mineral_richness=2,
        fuel_richness=2,
        distance_from_center=1,
        territory_type="normal",
        is_owned=True,
    )
    db.add(t)
    db.flush()
    return t


def _set_war(db: Session, a_id: int, b_id: int) -> None:
    a, b = min(a_id, b_id), max(a_id, b_id)
    db.add(Diplomacy(nation_a=a, nation_b=b, status="war"))
    db.flush()


def _make_trade(db: Session, from_nation: Nation, to_nation: Nation, **kwargs) -> Trade:
    now = datetime.now(timezone.utc)
    defaults = dict(
        offer_minerals=100, offer_fuel=0, offer_currency=0,
        request_minerals=0, request_fuel=100, request_currency=0,
        status="pending",
        from_accepted_at=now,
    )
    defaults.update(kwargs)
    t = Trade(from_nation_id=from_nation.id, to_nation_id=to_nation.id, **defaults)
    db.add(t)
    db.flush()
    return t


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
def my_nation(db: Session, test_player: Player) -> Nation:
    return _make_nation(db, test_player, "My Nation")


@pytest.fixture()
def other_player(db: Session) -> Player:
    return _make_player(db, "other")


@pytest.fixture()
def other_nation(db: Session, other_player: Player) -> Nation:
    return _make_nation(db, other_player, "Other Nation")


@pytest.fixture()
def adjacent_territories(db: Session, my_nation: Nation, other_nation: Nation):
    """Nation A owns 0,0; Nation B owns 1,0 — directly adjacent, route exists."""
    t_a = _make_territory(db, "0,0", my_nation)
    t_b = _make_territory(db, "1,0", other_nation)
    db.commit()
    return t_a, t_b


# ===========================================================================
# 1. PROPOSE TRADE
# ===========================================================================


class TestProposeTrade:

    def test_propose_happy_path(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        resp = auth_client.post("/api/trade", json={
            "to_nation_id": other_nation.id,
            "offer_minerals": 100,
            "request_fuel": 50,
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "pending"
        assert data["offer_minerals"] == 100.0
        assert data["request_fuel"] == 50.0

    def test_propose_sets_from_accepted_at_immediately(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        resp = auth_client.post("/api/trade", json={
            "to_nation_id": other_nation.id,
            "offer_minerals": 100,
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["from_accepted_at"] is not None

    def test_cannot_trade_with_self(self, db, auth_client, my_nation, adjacent_territories):
        resp = auth_client.post("/api/trade", json={
            "to_nation_id": my_nation.id,
            "offer_minerals": 100,
        })
        assert resp.status_code == 409

    def test_cannot_trade_while_at_war(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        _set_war(db, my_nation.id, other_nation.id)
        db.commit()
        resp = auth_client.post("/api/trade", json={
            "to_nation_id": other_nation.id,
            "offer_minerals": 100,
        })
        assert resp.status_code == 409

    def test_insufficient_minerals_rejected(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        resp = auth_client.post("/api/trade", json={
            "to_nation_id": other_nation.id,
            "offer_minerals": 999999,
        })
        assert resp.status_code == 409

    def test_all_zero_amounts_rejected(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        resp = auth_client.post("/api/trade", json={
            "to_nation_id": other_nation.id,
            "offer_minerals": 0,
        })
        assert resp.status_code == 422

    def test_no_route_blocked(self, db, auth_client, my_nation, other_nation):
        # Nations own territories with no adjacency between them in the DB
        _make_territory(db, "0,0", my_nation)
        _make_territory(db, "10,10", other_nation)
        db.commit()
        resp = auth_client.post("/api/trade", json={
            "to_nation_id": other_nation.id,
            "offer_minerals": 100,
        })
        assert resp.status_code == 409
        assert "route" in resp.json()["detail"].lower()

    def test_hostile_territory_blocks_route(self, db, auth_client, my_nation, other_nation):
        hostile_p = _make_player(db, "hostile")
        hostile_n = _make_nation(db, hostile_p, "Hostile Nation")
        _make_territory(db, "0,0", my_nation)
        _make_territory(db, "1,0", hostile_n)   # blocks direct path
        _make_territory(db, "2,0", other_nation)
        _set_war(db, my_nation.id, hostile_n.id)
        db.commit()
        resp = auth_client.post("/api/trade", json={
            "to_nation_id": other_nation.id,
            "offer_minerals": 100,
        })
        assert resp.status_code == 409


# ===========================================================================
# 2. ROUTE CHECK ENDPOINT
# ===========================================================================


class TestRouteCheck:

    def test_route_exists_when_adjacent(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        resp = auth_client.get(f"/api/trade/route/{other_nation.id}")
        assert resp.status_code == 200
        assert resp.json()["has_route"] is True

    def test_no_route_returns_reason(self, db, auth_client, my_nation, other_nation):
        _make_territory(db, "0,0", my_nation)
        _make_territory(db, "99,99", other_nation)
        db.commit()
        resp = auth_client.get(f"/api/trade/route/{other_nation.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_route"] is False
        assert data["reason"]


# ===========================================================================
# 3. ACCEPT — TWO-CLICK CONFIRMATION STATE MACHINE
# ===========================================================================


class TestAcceptTrade:

    def test_first_click_sets_to_accepted_at(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        trade = _make_trade(db, my_nation, other_nation)
        db.commit()

        # Log in as other_nation
        other_token = create_access_token(other_nation.player_id)
        app.dependency_overrides[get_db] = _db_override(db)
        with TestClient(app, raise_server_exceptions=True) as c:
            c.cookies.set("session", other_token)
            resp = c.post(f"/api/trade/{trade.id}/accept")
        app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["to_accepted_at"] is not None
        assert data["to_confirmed_at"] is None
        assert data["status"] == "pending"

    def test_second_click_too_soon_rejected(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        trade = _make_trade(db, my_nation, other_nation)
        # Simulate recipient has just clicked (accepted_at = now)
        trade.to_accepted_at = datetime.now(timezone.utc)
        db.commit()

        other_token = create_access_token(other_nation.player_id)
        app.dependency_overrides[get_db] = _db_override(db)
        with TestClient(app, raise_server_exceptions=True) as c:
            c.cookies.set("session", other_token)
            resp = c.post(f"/api/trade/{trade.id}/accept")
        app.dependency_overrides.clear()

        assert resp.status_code == 409
        assert "Wait" in resp.json()["detail"]

    def test_second_click_after_cooldown_sets_confirmed(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        trade = _make_trade(db, my_nation, other_nation)
        # Simulate cooldown already elapsed
        trade.to_accepted_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        db.commit()

        other_token = create_access_token(other_nation.player_id)
        app.dependency_overrides[get_db] = _db_override(db)
        with TestClient(app, raise_server_exceptions=True) as c:
            c.cookies.set("session", other_token)
            resp = c.post(f"/api/trade/{trade.id}/accept")
        app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["to_confirmed_at"] is not None
        # Only recipient confirmed; proposer hasn't — trade still pending
        assert data["status"] == "pending"

    def test_both_confirmed_executes_trade(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        """When both sides confirm, resources transfer and status becomes accepted."""
        my_nation.minerals = 1000
        other_nation.fuel   = 1000
        db.flush()

        trade = _make_trade(
            db, my_nation, other_nation,
            offer_minerals=200, request_fuel=300,
        )
        # Proposer already confirmed (cooldown elapsed)
        trade.from_confirmed_at = datetime.now(timezone.utc)
        # Recipient first click already done (cooldown elapsed)
        trade.to_accepted_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        db.commit()

        other_token = create_access_token(other_nation.player_id)
        app.dependency_overrides[get_db] = _db_override(db)
        with TestClient(app, raise_server_exceptions=True) as c:
            c.cookies.set("session", other_token)
            resp = c.post(f"/api/trade/{trade.id}/accept")
        app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "accepted"

        db.expire_all()
        my_nation_fresh  = db.get(Nation, my_nation.id)
        other_nation_fresh = db.get(Nation, other_nation.id)
        # Proposer gave 200 minerals, received 300 fuel
        assert float(my_nation_fresh.minerals) == pytest.approx(800.0)
        assert float(my_nation_fresh.fuel) == pytest.approx(5300.0)
        # Recipient gave 300 fuel, received 200 minerals
        assert float(other_nation_fresh.fuel) == pytest.approx(700.0)
        assert float(other_nation_fresh.minerals) == pytest.approx(5200.0)

    def test_non_party_cannot_accept(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        trade = _make_trade(db, my_nation, other_nation)
        third_p = _make_player(db, "third")
        _make_nation(db, third_p, "Third Nation")
        db.commit()

        third_token = create_access_token(third_p.id)
        app.dependency_overrides[get_db] = _db_override(db)
        with TestClient(app, raise_server_exceptions=True) as c:
            c.cookies.set("session", third_token)
            resp = c.post(f"/api/trade/{trade.id}/accept")
        app.dependency_overrides.clear()

        assert resp.status_code == 403

    def test_proposer_first_click_confirms_after_cooldown(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        """Proposer's accepted_at is set on creation; they can confirm after cooldown."""
        trade = _make_trade(db, my_nation, other_nation)
        # Wind back from_accepted_at so cooldown has elapsed
        trade.from_accepted_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        db.commit()

        resp = auth_client.post(f"/api/trade/{trade.id}/accept")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["from_confirmed_at"] is not None


# ===========================================================================
# 4. EDIT TERMS
# ===========================================================================


class TestEditTrade:

    def test_edit_updates_amounts(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        trade = _make_trade(db, my_nation, other_nation)
        db.commit()

        resp = auth_client.put(f"/api/trade/{trade.id}", json={
            "offer_minerals": 500,
            "request_fuel": 250,
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["offer_minerals"] == 500.0
        assert data["request_fuel"] == 250.0

    def test_edit_resets_all_confirmation_fields(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        now = datetime.now(timezone.utc)
        trade = _make_trade(db, my_nation, other_nation)
        trade.from_accepted_at  = now
        trade.from_confirmed_at = now
        trade.to_accepted_at    = now
        db.commit()

        resp = auth_client.put(f"/api/trade/{trade.id}", json={
            "offer_minerals": 200,
            "request_fuel": 100,
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["from_accepted_at"]  is None
        assert data["from_confirmed_at"] is None
        assert data["to_accepted_at"]    is None
        assert data["to_confirmed_at"]   is None

    def test_recipient_can_edit(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        trade = _make_trade(db, my_nation, other_nation)
        db.commit()

        other_token = create_access_token(other_nation.player_id)
        app.dependency_overrides[get_db] = _db_override(db)
        with TestClient(app, raise_server_exceptions=True) as c:
            c.cookies.set("session", other_token)
            resp = c.put(f"/api/trade/{trade.id}", json={"offer_minerals": 50, "request_fuel": 50})
        app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text

    def test_non_party_cannot_edit(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        trade = _make_trade(db, my_nation, other_nation)
        third_p = _make_player(db, "third2")
        _make_nation(db, third_p, "Third2")
        db.commit()

        third_token = create_access_token(third_p.id)
        app.dependency_overrides[get_db] = _db_override(db)
        with TestClient(app, raise_server_exceptions=True) as c:
            c.cookies.set("session", third_token)
            resp = c.put(f"/api/trade/{trade.id}", json={"offer_minerals": 50})
        app.dependency_overrides.clear()

        assert resp.status_code == 403


# ===========================================================================
# 5. REJECT
# ===========================================================================


class TestRejectTrade:

    def test_recipient_can_reject(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        trade = _make_trade(db, my_nation, other_nation)
        db.commit()

        other_token = create_access_token(other_nation.player_id)
        app.dependency_overrides[get_db] = _db_override(db)
        with TestClient(app, raise_server_exceptions=True) as c:
            c.cookies.set("session", other_token)
            resp = c.post(f"/api/trade/{trade.id}/reject")
        app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "rejected"

    def test_proposer_cannot_reject(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        trade = _make_trade(db, my_nation, other_nation)
        db.commit()
        resp = auth_client.post(f"/api/trade/{trade.id}/reject")
        assert resp.status_code == 403


# ===========================================================================
# 6. CANCEL
# ===========================================================================


class TestCancelTrade:

    def test_proposer_can_cancel(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        trade = _make_trade(db, my_nation, other_nation)
        db.commit()
        resp = auth_client.post(f"/api/trade/{trade.id}/cancel")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "cancelled"

    def test_recipient_cannot_cancel(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        trade = _make_trade(db, my_nation, other_nation)
        db.commit()

        other_token = create_access_token(other_nation.player_id)
        app.dependency_overrides[get_db] = _db_override(db)
        with TestClient(app, raise_server_exceptions=True) as c:
            c.cookies.set("session", other_token)
            resp = c.post(f"/api/trade/{trade.id}/cancel")
        app.dependency_overrides.clear()

        assert resp.status_code == 403


# ===========================================================================
# 7. LIST TRADES
# ===========================================================================


class TestListTrades:

    def test_list_returns_pending_trades(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        _make_trade(db, my_nation, other_nation)
        _make_trade(db, other_nation, my_nation)
        db.commit()
        resp = auth_client.get("/api/trade")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_accepted_trades_excluded(self, db, auth_client, my_nation, other_nation, adjacent_territories):
        _make_trade(db, my_nation, other_nation, status="accepted")
        db.commit()
        resp = auth_client.get("/api/trade")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_other_nations_trades_excluded(self, db, auth_client, my_nation, other_nation):
        third_p = _make_player(db, "third3")
        third_n = _make_nation(db, third_p, "Third3 Nation")
        _make_trade(db, other_nation, third_n)
        db.commit()
        resp = auth_client.get("/api/trade")
        assert resp.status_code == 200
        assert resp.json() == []
