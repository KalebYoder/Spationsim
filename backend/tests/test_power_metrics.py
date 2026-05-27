"""
Test suite for military_strength and industrial_strength power metrics.

military_strength  = total fighters across all fleets (all statuses)
industrial_strength = active mines + active refineries + 2 × active shipyards

Metrics are returned by:
  - GET /api/nations/{id}   (public profile, visible to everyone)
  - GET /api/nations/mine   (private, visible to the owner on the home page)

Covers:
  1. Empty nation → both metrics are 0
  2. military_strength counts fighters from all fleet statuses
  3. industrial_strength: mine = 1, refinery = 1, shipyard = 2
  4. Under-construction facilities do not count toward industrial_strength
  5. Probe factories do not count toward industrial_strength
  6. Nation isolation — other nations' assets don't bleed in
  7. Both endpoints return the same metrics for the same nation
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
from app.models.infrastructure import Infrastructure
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


def _make_player(db: Session, username: str) -> Player:
    p = Player(username=username, email=f"{username}@test.com",
               password_hash=hash_password("pw"))
    db.add(p)
    db.flush()
    return p


def _make_nation(db: Session, player: Player, name: str) -> Nation:
    n = Nation(player_id=player.id, name=name, minerals=500, fuel=500, currency=1000)
    db.add(n)
    db.flush()
    return n


def _make_territory(db: Session, nation_id: int, node_key: str) -> Territory:
    t = Territory(
        node_key=node_key,
        name=f"Planet {node_key}",
        territory_type="normal",
        nation_id=nation_id,
        mineral_richness=1,
        fuel_richness=1,
        distance_from_center=1,
        is_colonized=True,
        colonized_at=datetime.now(timezone.utc),
    )
    db.add(t)
    db.flush()
    return t


def _make_fleet(db: Session, nation_id: int, territory_id: int, units: int,
                status: str = "stationed") -> Fleet:
    f = Fleet(
        nation_id=nation_id,
        origin_territory=territory_id,
        unit_count=units,
        status=status,
        standing_order="hold",
        arrives_at=datetime(2099, 1, 1, tzinfo=timezone.utc) if status == "in_transit" else None,
    )
    db.add(f)
    db.flush()
    return f


def _make_infra(db: Session, territory_id: int, ftype: str,
                status: str = "active") -> Infrastructure:
    i = Infrastructure(territory_id=territory_id, type=ftype, level=1, status=status)
    db.add(i)
    db.flush()
    return i


def _auth_client(db: Session, player: Player) -> TestClient:
    token = create_access_token(player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    c = TestClient(app, raise_server_exceptions=True)
    c.cookies.set("session", token)
    return c


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def player(db):
    return _make_player(db, "pm_player")

@pytest.fixture()
def nation(db, player):
    return _make_nation(db, player, "Power Nation")

@pytest.fixture()
def territory(db, nation):
    return _make_territory(db, nation.id, "pm_0_0")

@pytest.fixture()
def other_player(db):
    return _make_player(db, "pm_other")

@pytest.fixture()
def other_nation(db, other_player):
    return _make_nation(db, other_player, "Other Power Nation")

@pytest.fixture()
def other_territory(db, other_nation):
    return _make_territory(db, other_nation.id, "pm_9_9")


# ---------------------------------------------------------------------------
# 1. Empty nation
# ---------------------------------------------------------------------------

class TestEmptyNation:

    def test_public_profile_empty_nation_both_zero(self, db, player, nation):
        db.commit()
        c = _auth_client(db, player)
        r = c.get(f"/api/nations/{nation.id}")
        assert r.status_code == 200
        data = r.json()
        assert data["military_strength"] == 0
        assert data["industrial_strength"] == 0
        app.dependency_overrides.clear()

    def test_mine_endpoint_empty_nation_both_zero(self, db, player, nation):
        db.commit()
        c = _auth_client(db, player)
        r = c.get("/api/nations/mine")
        assert r.status_code == 200
        data = r.json()
        assert data["military_strength"] == 0
        assert data["industrial_strength"] == 0
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 2. military_strength
# ---------------------------------------------------------------------------

class TestMilitaryStrength:

    def test_stationed_fighters_count(self, db, player, nation, territory):
        _make_fleet(db, nation.id, territory.id, units=15, status="stationed")
        db.commit()
        c = _auth_client(db, player)
        r = c.get(f"/api/nations/{nation.id}")
        assert r.json()["military_strength"] == 15
        app.dependency_overrides.clear()

    def test_in_transit_fighters_count(self, db, player, nation, territory):
        _make_fleet(db, nation.id, territory.id, units=8, status="in_transit")
        db.commit()
        c = _auth_client(db, player)
        r = c.get(f"/api/nations/{nation.id}")
        assert r.json()["military_strength"] == 8
        app.dependency_overrides.clear()

    def test_multiple_fleet_statuses_sum(self, db, player, nation, territory):
        _make_fleet(db, nation.id, territory.id, units=10, status="stationed")
        _make_fleet(db, nation.id, territory.id, units=5,  status="in_transit")
        _make_fleet(db, nation.id, territory.id, units=3,  status="holding")
        db.commit()
        c = _auth_client(db, player)
        r = c.get(f"/api/nations/{nation.id}")
        assert r.json()["military_strength"] == 18
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 3. industrial_strength: facility weights
# ---------------------------------------------------------------------------

class TestIndustrialStrength:

    def test_mine_counts_one(self, db, player, nation, territory):
        _make_infra(db, territory.id, "mine")
        db.commit()
        c = _auth_client(db, player)
        r = c.get(f"/api/nations/{nation.id}")
        assert r.json()["industrial_strength"] == 1
        app.dependency_overrides.clear()

    def test_refinery_counts_one(self, db, player, nation, territory):
        _make_infra(db, territory.id, "refinery")
        db.commit()
        c = _auth_client(db, player)
        r = c.get(f"/api/nations/{nation.id}")
        assert r.json()["industrial_strength"] == 1
        app.dependency_overrides.clear()

    def test_shipyard_counts_two(self, db, player, nation, territory):
        _make_infra(db, territory.id, "shipyard")
        db.commit()
        c = _auth_client(db, player)
        r = c.get(f"/api/nations/{nation.id}")
        assert r.json()["industrial_strength"] == 2
        app.dependency_overrides.clear()

    def test_mixed_facilities_sum(self, db, player, nation, territory):
        # mine(1) + refinery(1) + shipyard(2) = 4
        _make_infra(db, territory.id, "mine")
        _make_infra(db, territory.id, "refinery")
        _make_infra(db, territory.id, "shipyard")
        db.commit()
        c = _auth_client(db, player)
        r = c.get(f"/api/nations/{nation.id}")
        assert r.json()["industrial_strength"] == 4
        app.dependency_overrides.clear()

    def test_multiple_shipyards_each_count_two(self, db, player, nation, territory):
        _make_infra(db, territory.id, "shipyard")
        _make_infra(db, territory.id, "shipyard")
        db.commit()
        c = _auth_client(db, player)
        r = c.get(f"/api/nations/{nation.id}")
        assert r.json()["industrial_strength"] == 4
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 4. Under-construction facilities excluded
# ---------------------------------------------------------------------------

class TestUnderConstruction:

    def test_under_construction_facility_not_counted(self, db, player, nation, territory):
        _make_infra(db, territory.id, "mine", status="under_construction")
        db.commit()
        c = _auth_client(db, player)
        r = c.get(f"/api/nations/{nation.id}")
        assert r.json()["industrial_strength"] == 0
        app.dependency_overrides.clear()

    def test_active_counts_construction_does_not(self, db, player, nation, territory):
        _make_infra(db, territory.id, "mine", status="active")
        _make_infra(db, territory.id, "shipyard", status="under_construction")
        db.commit()
        c = _auth_client(db, player)
        r = c.get(f"/api/nations/{nation.id}")
        assert r.json()["industrial_strength"] == 1
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 5. Probe factory excluded
# ---------------------------------------------------------------------------

class TestProbeFactory:

    def test_probe_factory_not_counted(self, db, player, nation, territory):
        _make_infra(db, territory.id, "probe_factory")
        db.commit()
        c = _auth_client(db, player)
        r = c.get(f"/api/nations/{nation.id}")
        assert r.json()["industrial_strength"] == 0
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 6. Nation isolation
# ---------------------------------------------------------------------------

class TestIsolation:

    def test_other_nation_fighters_not_counted(
        self, db, player, nation, territory, other_nation, other_territory
    ):
        _make_fleet(db, nation.id,       territory.id,       units=10)
        _make_fleet(db, other_nation.id, other_territory.id, units=99)
        db.commit()
        c = _auth_client(db, player)
        r = c.get(f"/api/nations/{nation.id}")
        assert r.json()["military_strength"] == 10
        app.dependency_overrides.clear()

    def test_other_nation_facilities_not_counted(
        self, db, player, nation, territory, other_nation, other_territory
    ):
        _make_infra(db, territory.id,       "mine")
        _make_infra(db, other_territory.id, "shipyard")
        _make_infra(db, other_territory.id, "shipyard")
        db.commit()
        c = _auth_client(db, player)
        r = c.get(f"/api/nations/{nation.id}")
        assert r.json()["industrial_strength"] == 1
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 7. Both endpoints consistent
# ---------------------------------------------------------------------------

class TestBothEndpointsConsistent:

    def test_public_and_mine_return_same_metrics(self, db, player, nation, territory):
        _make_fleet(db, nation.id, territory.id, units=7)
        _make_infra(db, territory.id, "mine")
        _make_infra(db, territory.id, "shipyard")
        db.commit()
        c = _auth_client(db, player)
        pub  = c.get(f"/api/nations/{nation.id}").json()
        priv = c.get("/api/nations/mine").json()
        assert pub["military_strength"]   == priv["military_strength"]   == 7
        assert pub["industrial_strength"] == priv["industrial_strength"] == 3
        app.dependency_overrides.clear()
