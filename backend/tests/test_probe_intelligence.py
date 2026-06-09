"""
Test suite for the probe intelligence display: GET /api/probes/data

The "Your Intelligence" table in the probe window shows:
  - Planet name (territory_name, nullable)
  - Coordinates (node_key — always present, separate column)
  - Mineral richness (float)
  - Fuel richness (float)
  - Time scouted (discovered_at — ISO datetime string)
  - Status (is_owned, nation_name)

Tests verify the response contract the frontend relies on, covering field
presence, nullability, ordering, and per-nation isolation.
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
from app.models.probe_data import ProbeData
from app.models.territory import Territory
from app.core.security import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_territory(
    db: Session,
    node_key: str,
    name: str | None = None,
    nation_id: int | None = None,
    is_owned: bool = False,
    mineral_richness: float = 1.50,
    fuel_richness: float = 0.75,
) -> Territory:
    t = Territory(
        node_key=node_key,
        name=name,
        territory_type="normal",
        nation_id=nation_id,
        mineral_richness=mineral_richness,
        fuel_richness=fuel_richness,
        distance_from_center=3,
        is_owned=is_owned,
        owned_at=datetime.now(timezone.utc) if is_owned else None,
    )
    db.add(t)
    db.flush()
    return t


def _make_probe_data(
    db: Session,
    territory_id: int,
    discovered_by: int,
    mineral_richness: float = 1.50,
    fuel_richness: float = 0.75,
    discovered_at: datetime | None = None,
) -> ProbeData:
    pd = ProbeData(
        territory_id=territory_id,
        discovered_by=discovered_by,
        mineral_richness=mineral_richness,
        fuel_richness=fuel_richness,
        discovered_at=discovered_at or datetime.now(timezone.utc),
    )
    db.add(pd)
    db.flush()
    return pd


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def other_player(db: Session) -> Player:
    p = Player(
        username="other_probe",
        email="other_probe@example.com",
        password_hash=hash_password("password123"),
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def other_nation(db: Session, other_player: Player) -> Nation:
    n = Nation(
        player_id=other_player.id,
        name="Other Probe Nation",
        minerals=0,
        fuel=0,
    )
    db.add(n)
    db.flush()
    return n


# ===========================================================================
# 1. AUTH / PRECONDITIONS
# ===========================================================================


class TestAuthGuards:
    def test_unauthenticated_returns_401(self, client: TestClient):
        resp = client.get("/api/probes/data")
        assert resp.status_code == 401

    def test_authenticated_without_nation_returns_404(
        self, db: Session, test_player: Player
    ):
        token = create_access_token(test_player.id)
        app.dependency_overrides[get_db] = lambda: (yield db)
        with TestClient(app, raise_server_exceptions=True) as c:
            c.cookies.set("session", token)
            resp = c.get("/api/probes/data")
        app.dependency_overrides.clear()
        assert resp.status_code == 404


# ===========================================================================
# 2. EMPTY STATE
# ===========================================================================


class TestEmptyIntelligence:
    def test_no_probe_data_returns_empty_list(
        self, auth_client: TestClient, test_nation: Nation
    ):
        resp = auth_client.get("/api/probes/data")
        assert resp.status_code == 200, resp.text
        assert resp.json() == []

    def test_response_is_a_list(
        self, auth_client: TestClient, test_nation: Nation
    ):
        resp = auth_client.get("/api/probes/data")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ===========================================================================
# 3. REQUIRED FIELDS — contract the frontend depends on
# ===========================================================================


class TestResponseFields:
    """Every probe data entry must carry all fields the intelligence table renders."""

    def test_node_key_always_present(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        """Coordinates column requires node_key on every row."""
        t = _make_territory(db, "5,3")
        _make_probe_data(db, t.id, test_nation.id)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        assert resp.status_code == 200
        row = resp.json()[0]
        assert "node_key" in row, "node_key must be present for the Coordinates column"
        assert row["node_key"] == "5,3"

    def test_territory_name_field_present(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        """Planet column requires territory_name (may be null)."""
        t = _make_territory(db, "5,4", name="Proxima Base")
        _make_probe_data(db, t.id, test_nation.id)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        row = resp.json()[0]
        assert "territory_name" in row, "territory_name must be in the response"
        assert row["territory_name"] == "Proxima Base"

    def test_territory_name_is_null_when_unnamed(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        """Unnamed planets must return territory_name=null (frontend shows 'Unnamed')."""
        t = _make_territory(db, "5,5", name=None)
        _make_probe_data(db, t.id, test_nation.id)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        row = resp.json()[0]
        assert row["territory_name"] is None, (
            f"Unnamed territory must have territory_name=null, got {row['territory_name']!r}"
        )

    def test_mineral_richness_is_float(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        """Minerals column requires mineral_richness as a number."""
        t = _make_territory(db, "5,6", mineral_richness=1.75)
        _make_probe_data(db, t.id, test_nation.id, mineral_richness=1.75)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        row = resp.json()[0]
        assert "mineral_richness" in row
        assert isinstance(row["mineral_richness"], (int, float)), (
            f"mineral_richness must be numeric, got {type(row['mineral_richness'])}"
        )
        assert abs(row["mineral_richness"] - 1.75) < 0.001

    def test_fuel_richness_is_float(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        """Fuel column requires fuel_richness as a number."""
        t = _make_territory(db, "5,7", fuel_richness=0.50)
        _make_probe_data(db, t.id, test_nation.id, fuel_richness=0.50)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        row = resp.json()[0]
        assert "fuel_richness" in row
        assert isinstance(row["fuel_richness"], (int, float))
        assert abs(row["fuel_richness"] - 0.50) < 0.001

    def test_discovered_at_is_iso_string(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        """Scouted column requires discovered_at as an ISO datetime string."""
        t = _make_territory(db, "5,8")
        _make_probe_data(db, t.id, test_nation.id)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        row = resp.json()[0]
        assert "discovered_at" in row
        assert isinstance(row["discovered_at"], str), (
            "discovered_at must be a string"
        )
        # Must parse as a valid datetime
        dt = datetime.fromisoformat(row["discovered_at"].replace("Z", "+00:00"))
        assert dt is not None

    def test_is_owned_field_present(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        """Status column requires is_owned boolean."""
        t = _make_territory(db, "5,9")
        _make_probe_data(db, t.id, test_nation.id)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        row = resp.json()[0]
        assert "is_owned" in row
        assert isinstance(row["is_owned"], bool)

    def test_all_display_fields_present_in_single_row(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        """Every field the intelligence table renders must appear in one row."""
        t = _make_territory(db, "6,0", name="Test System")
        _make_probe_data(db, t.id, test_nation.id)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        row = resp.json()[0]
        required = {"node_key", "territory_name", "mineral_richness", "fuel_richness",
                    "discovered_at", "is_owned", "nation_name"}
        missing = required - set(row.keys())
        assert not missing, f"Missing fields in probe data response: {missing}"


# ===========================================================================
# 4. RICHNESS VALUES — accuracy
# ===========================================================================


class TestRichnessValues:
    def test_richness_values_match_territory(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        """Displayed richness must be the values recorded at scan time, not territory current."""
        t = _make_territory(db, "7,0", mineral_richness=2.00, fuel_richness=1.25)
        _make_probe_data(db, t.id, test_nation.id, mineral_richness=2.00, fuel_richness=1.25)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        row = resp.json()[0]
        assert abs(row["mineral_richness"] - 2.00) < 0.001
        assert abs(row["fuel_richness"] - 1.25) < 0.001

    def test_minimum_richness_zero(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        """Richness of 0.00 must serialize without error."""
        t = _make_territory(db, "7,1", mineral_richness=0.00, fuel_richness=0.00)
        _make_probe_data(db, t.id, test_nation.id, mineral_richness=0.00, fuel_richness=0.00)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        row = resp.json()[0]
        assert row["mineral_richness"] == 0.0
        assert row["fuel_richness"] == 0.0


# ===========================================================================
# 5. COLONIZATION STATUS
# ===========================================================================


class TestColonizationStatus:
    def test_unclaimed_territory_is_not_colonized(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        """Unclaimed territory: is_owned=false, nation_name=null."""
        t = _make_territory(db, "8,0", is_owned=False)
        _make_probe_data(db, t.id, test_nation.id)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        row = resp.json()[0]
        assert row["is_owned"] is False
        assert row["nation_name"] is None

    def test_colonized_territory_shows_owner_name(
        self, auth_client: TestClient, db: Session,
        test_nation: Nation, other_nation: Nation
    ):
        """Colonized territory: is_owned=true, nation_name is the owner's name."""
        t = _make_territory(db, "8,1", nation_id=other_nation.id, is_owned=True)
        _make_probe_data(db, t.id, test_nation.id)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        row = resp.json()[0]
        assert row["is_owned"] is True
        assert row["nation_name"] == other_nation.name

    def test_own_colonized_territory_shows_own_name(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        """A probe discovering your own territory: is_owned=true, nation_name=your nation."""
        t = _make_territory(db, "8,2", nation_id=test_nation.id, is_owned=True)
        _make_probe_data(db, t.id, test_nation.id)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        row = resp.json()[0]
        assert row["is_owned"] is True
        assert row["nation_name"] == test_nation.name


# ===========================================================================
# 6. ORDERING — most recently scouted first
# ===========================================================================


class TestOrdering:
    def test_most_recently_discovered_comes_first(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        """Results must be sorted newest-first so the latest intelligence is at the top."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=10)
        new_time = datetime.now(timezone.utc) - timedelta(minutes=30)

        t_old = _make_territory(db, "9,0")
        t_new = _make_territory(db, "9,1")
        _make_probe_data(db, t_old.id, test_nation.id, discovered_at=old_time)
        _make_probe_data(db, t_new.id, test_nation.id, discovered_at=new_time)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        rows = resp.json()
        assert len(rows) == 2
        assert rows[0]["node_key"] == "9,1", (
            "Most recently discovered territory must appear first"
        )
        assert rows[1]["node_key"] == "9,0"

    def test_three_entries_ordered_newest_first(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        now = datetime.now(timezone.utc)
        t1 = _make_territory(db, "10,0")
        t2 = _make_territory(db, "10,1")
        t3 = _make_territory(db, "10,2")
        _make_probe_data(db, t1.id, test_nation.id, discovered_at=now - timedelta(hours=5))
        _make_probe_data(db, t2.id, test_nation.id, discovered_at=now - timedelta(hours=1))
        _make_probe_data(db, t3.id, test_nation.id, discovered_at=now - timedelta(hours=3))
        db.commit()

        resp = auth_client.get("/api/probes/data")
        keys = [r["node_key"] for r in resp.json()]
        assert keys == ["10,1", "10,2", "10,0"], (
            f"Expected newest-first ordering, got {keys}"
        )


# ===========================================================================
# 7. ISOLATION — only the requesting nation's data
# ===========================================================================


class TestNationIsolation:
    def test_only_own_probe_data_returned(
        self, auth_client: TestClient, db: Session,
        test_nation: Nation, other_nation: Nation
    ):
        """Probe data discovered by another nation must not appear in the response."""
        t_own = _make_territory(db, "11,0")
        t_other = _make_territory(db, "11,1")
        _make_probe_data(db, t_own.id, test_nation.id)
        _make_probe_data(db, t_other.id, other_nation.id)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        rows = resp.json()
        assert len(rows) == 1, (
            f"Must only return own probe data, got {len(rows)} rows"
        )
        assert rows[0]["node_key"] == "11,0"

    def test_other_nation_sees_only_their_data(
        self, db: Session, test_nation: Nation, other_nation: Nation, other_player: Player
    ):
        """When the other nation calls the endpoint, they see only their own records."""
        t_own = _make_territory(db, "12,0")
        t_other = _make_territory(db, "12,1")
        _make_probe_data(db, t_own.id, test_nation.id)
        _make_probe_data(db, t_other.id, other_nation.id)
        db.commit()

        token = create_access_token(other_player.id)
        app.dependency_overrides[get_db] = lambda: (yield db)
        with TestClient(app, raise_server_exceptions=True) as c:
            c.cookies.set("session", token)
            resp = c.get("/api/probes/data")
        app.dependency_overrides.clear()

        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["node_key"] == "12,1"

    def test_same_territory_discovered_by_both_nations_returned_separately(
        self, auth_client: TestClient, db: Session,
        test_nation: Nation, other_nation: Nation
    ):
        """Two nations can each have a probe_data row for the same territory (both see theirs)."""
        t = _make_territory(db, "13,0")
        _make_probe_data(db, t.id, test_nation.id, mineral_richness=1.00)
        _make_probe_data(db, t.id, other_nation.id, mineral_richness=2.00)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["node_key"] == "13,0"
        assert abs(rows[0]["mineral_richness"] - 1.00) < 0.001


# ===========================================================================
# 8. MULTIPLE TERRITORIES
# ===========================================================================


class TestMultipleEntries:
    def test_all_discovered_territories_returned(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        """All territories the nation has probe data for must appear in the list."""
        keys = ["14,0", "14,1", "14,2", "14,3", "14,4"]
        for k in keys:
            t = _make_territory(db, k)
            _make_probe_data(db, t.id, test_nation.id)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        returned_keys = {r["node_key"] for r in resp.json()}
        assert returned_keys == set(keys), (
            f"Expected all {len(keys)} territories, got {returned_keys}"
        )

    def test_count_matches_probe_data_rows(
        self, auth_client: TestClient, db: Session, test_nation: Nation
    ):
        """Response length must equal the number of ProbeData rows for the nation."""
        for i in range(6):
            t = _make_territory(db, f"15,{i}")
            _make_probe_data(db, t.id, test_nation.id)
        db.commit()

        resp = auth_client.get("/api/probes/data")
        assert len(resp.json()) == 6
