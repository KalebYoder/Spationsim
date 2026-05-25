"""
Test suite for planet rename cooldown.

A territory can only be renamed once every 12 ticks (24 hours).
  - First rename always succeeds (no prior last_renamed_at).
  - Renaming within 24 hours of the last rename returns 409.
  - Renaming after 24 hours succeeds.
  - last_renamed_at is updated to now on each successful rename.
  - Other 403/404 guards remain unchanged.
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
from app.models.nation import Nation
from app.models.player import Player
from app.models.territory import Territory
from app.core.security import create_access_token, hash_password

RENAME_COOLDOWN_HOURS = 24  # 12 ticks × 2 h/tick


def _make_territory(db: Session, nation_id: int, node_key: str = "10,10") -> Territory:
    t = Territory(
        node_key=node_key,
        name="Old Name",
        territory_type="normal",
        nation_id=nation_id,
        mineral_richness=1.00,
        fuel_richness=1.00,
        distance_from_center=5,
        is_colonized=True,
        colonized_at=datetime.now(timezone.utc),
    )
    db.add(t)
    db.flush()
    return t


# ===========================================================================
# 1. FIRST RENAME — no cooldown yet
# ===========================================================================


class TestFirstRename:
    def test_first_rename_succeeds(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """Territory with no last_renamed_at can always be renamed."""
        t = _make_territory(db, test_nation.id)
        assert t.last_renamed_at is None

        resp = auth_client.patch(f"/api/territories/{t.id}/name", json={"name": "New Name"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "New Name"

    def test_first_rename_sets_last_renamed_at(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """Successful rename sets last_renamed_at to approximately now."""
        t = _make_territory(db, test_nation.id)
        before = datetime.now(timezone.utc)

        auth_client.patch(f"/api/territories/{t.id}/name", json={"name": "Named"})

        db.expire(t)
        db.refresh(t)
        assert t.last_renamed_at is not None, "last_renamed_at must be set after rename"
        assert t.last_renamed_at >= before, "last_renamed_at must not be in the past"


# ===========================================================================
# 2. COOLDOWN — rename within 24 hours rejected
# ===========================================================================


class TestRenameCooldown:
    def test_rename_within_cooldown_returns_409(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """Renaming within 24 hours of last rename must return 409."""
        t = _make_territory(db, test_nation.id)
        t.last_renamed_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.flush()

        resp = auth_client.patch(f"/api/territories/{t.id}/name", json={"name": "Too Soon"})
        assert resp.status_code == 409, resp.text

    def test_rename_cooldown_error_mentions_time_remaining(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """409 detail must include some indication of remaining wait time."""
        t = _make_territory(db, test_nation.id)
        t.last_renamed_at = datetime.now(timezone.utc) - timedelta(hours=12)
        db.flush()

        resp = auth_client.patch(f"/api/territories/{t.id}/name", json={"name": "Still Soon"})
        assert resp.status_code == 409
        detail = resp.json().get("detail", "")
        # Must mention hours or time remaining
        assert any(word in detail.lower() for word in ("hour", "h ", "remain", "wait", "until")), (
            f"409 detail must mention remaining time, got: {detail!r}"
        )

    def test_rename_exactly_at_cooldown_boundary_is_rejected(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """A rename attempted 23h59m after the last one (still within 24h) must be rejected."""
        t = _make_territory(db, test_nation.id)
        t.last_renamed_at = datetime.now(timezone.utc) - timedelta(hours=23, minutes=59)
        db.flush()

        resp = auth_client.patch(f"/api/territories/{t.id}/name", json={"name": "Boundary"})
        assert resp.status_code == 409, resp.text

    def test_rename_just_after_cooldown_succeeds(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """A rename attempted 24h+ after the last one must succeed."""
        t = _make_territory(db, test_nation.id)
        t.last_renamed_at = datetime.now(timezone.utc) - timedelta(hours=RENAME_COOLDOWN_HOURS, seconds=1)
        db.flush()

        resp = auth_client.patch(f"/api/territories/{t.id}/name", json={"name": "After Cooldown"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "After Cooldown"

    def test_rename_after_cooldown_updates_last_renamed_at(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """last_renamed_at is refreshed each time a rename succeeds."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        t = _make_territory(db, test_nation.id)
        t.last_renamed_at = old_time
        db.flush()

        auth_client.patch(f"/api/territories/{t.id}/name", json={"name": "Refreshed"})

        db.expire(t)
        db.refresh(t)
        assert t.last_renamed_at > old_time, (
            "last_renamed_at must be updated to a more recent timestamp after rename"
        )


# ===========================================================================
# 3. COOLDOWN LENGTH — 12 ticks × 2 h = 24 h
# ===========================================================================


class TestCooldownLength:
    def test_cooldown_is_24_hours(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """Rename 23h59m59s after last rename must fail; 24h0m1s must succeed."""
        t1 = _make_territory(db, test_nation.id, "10,11")
        t1.last_renamed_at = datetime.now(timezone.utc) - timedelta(hours=23, minutes=59, seconds=59)
        db.flush()
        resp = auth_client.patch(f"/api/territories/{t1.id}/name", json={"name": "Too Early"})
        assert resp.status_code == 409, "23h59m59s should still be in cooldown"

        t2 = _make_territory(db, test_nation.id, "10,12")
        t2.last_renamed_at = datetime.now(timezone.utc) - timedelta(hours=24, seconds=1)
        db.flush()
        resp2 = auth_client.patch(f"/api/territories/{t2.id}/name", json={"name": "Just After"})
        assert resp2.status_code == 200, "24h0m1s should be past cooldown"


# ===========================================================================
# 4. EXISTING GUARDS — 403 / 404 still enforced
# ===========================================================================


class TestExistingGuards:
    def test_rename_unknown_territory_returns_404(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        resp = auth_client.patch("/api/territories/99999/name", json={"name": "Ghost"})
        assert resp.status_code == 404

    def test_rename_territory_owned_by_other_nation_returns_403(
        self,
        db: Session,
        test_nation: Nation,
        test_player: Player,
    ):
        """A player cannot rename a territory they do not own."""
        other_player = Player(
            username="enemy_rename",
            email="enemy_rename@example.com",
            password_hash=hash_password("password123"),
        )
        db.add(other_player)
        db.flush()
        other_nation = Nation(
            player_id=other_player.id,
            name="Enemy Nation Rename",
            minerals=0,
            fuel=0,
        )
        db.add(other_nation)
        db.flush()
        enemy_territory = _make_territory(db, other_nation.id, "20,20")
        db.flush()

        token = create_access_token(test_player.id)
        app.dependency_overrides[get_db] = lambda: (yield db)
        with TestClient(app, raise_server_exceptions=True) as c:
            c.cookies.set("session", token)
            resp = c.patch(f"/api/territories/{enemy_territory.id}/name", json={"name": "Mine Now"})
        app.dependency_overrides.clear()

        assert resp.status_code == 403, resp.text

    def test_rename_unauthenticated_returns_401(
        self,
        client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        t = _make_territory(db, test_nation.id, "30,30")
        resp = client.patch(f"/api/territories/{t.id}/name", json={"name": "No Auth"})
        assert resp.status_code == 401
