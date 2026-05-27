"""
Test suite for diplomacy status feature.

Covers two areas:
  1. Status API — PUT /api/diplomacy/{target_nation_id} sets war/neutral/friendly
     with correct validation rules (vacation block, 24h war minimum, etc.)
     GET /api/diplomacy/{target_nation_id} returns current status
     GET /api/diplomacy/relations returns all non-neutral relationships

  2. Fleet movement by diplomacy status:
     - Friendly: dispatch to planet allowed; fleet lands normally on arrival
     - Neutral:  dispatch to claimed void allowed; dispatch to planet blocked (409)
     - War:      dispatch to any territory allowed; planet → pending_confirmation + defender
                 alert event; void → lands normally + defender alert event

  Not tested here: combat resolution (tested in test_war.py, test_confirmation_window.py)
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
from app.db.database import get_db, SessionLocal
from app.models.diplomacy import Diplomacy
from app.models.event import Event
from app.models.fleet import Fleet
from app.models.nation import Nation
from app.models.player import Player
from app.models.territory import Territory
from app.models.territory_population import TerritoryPopulation
from app.core.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_override(session: Session):
    def _override():
        yield session
    return _override


def _make_player(db: Session, username: str, email: str) -> Player:
    p = Player(username=username, email=email, password_hash=hash_password("pw"))
    db.add(p)
    db.flush()
    return p


def _make_nation(db: Session, player: Player, name: str, minerals=500, fuel=500, currency=2000) -> Nation:
    n = Nation(player_id=player.id, name=name, minerals=minerals, fuel=fuel, currency=currency)
    db.add(n)
    db.flush()
    return n


def _make_territory(
    db: Session,
    node_key: str,
    nation_id: int | None = None,
    is_colonized: bool = False,
    territory_type: str = "normal",
    mineral_richness: int = 2,
    fuel_richness: int = 2,
) -> Territory:
    t = Territory(
        node_key=node_key,
        name=f"Planet {node_key}",
        territory_type=territory_type,
        nation_id=nation_id,
        mineral_richness=mineral_richness,
        fuel_richness=fuel_richness,
        distance_from_center=1,
        is_colonized=is_colonized,
        colonized_at=datetime.now(timezone.utc) if is_colonized else None,
    )
    db.add(t)
    db.flush()
    return t


def _make_void(db: Session, node_key: str, nation_id: int | None = None) -> Territory:
    return _make_territory(
        db, node_key, nation_id=nation_id, is_colonized=bool(nation_id),
        territory_type="void", mineral_richness=0, fuel_richness=0,
    )


def _make_fleet(db: Session, nation_id: int, origin_id: int, unit_count: int = 10) -> Fleet:
    f = Fleet(
        nation_id=nation_id,
        origin_territory=origin_id,
        unit_count=unit_count,
        status="stationed",
    )
    db.add(f)
    db.flush()
    return f


def _set_diplomacy(db: Session, a_id: int, b_id: int, status: str) -> None:
    a, b = min(a_id, b_id), max(a_id, b_id)
    row = db.query(Diplomacy).filter(Diplomacy.nation_a == a, Diplomacy.nation_b == b).first()
    if row:
        row.status = status
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(Diplomacy(nation_a=a, nation_b=b, status=status, updated_at=datetime.now(timezone.utc)))
    db.flush()


def _commit_and_run_tick(db: Session) -> None:
    db.commit()
    from app.tasks.tick import run_tick
    run_tick()


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
    return _make_player(db, "other", "other@example.com")


@pytest.fixture()
def other_nation(db: Session, other_player: Player) -> Nation:
    return _make_nation(db, other_player, "Other Nation")


# ===========================================================================
# 1. STATUS API
# ===========================================================================


class TestSetDiplomacyStatus:
    """PUT /api/diplomacy/{target_nation_id} correctly updates status."""

    def test_set_friendly_via_put_rejected(self, db: Session, auth_client, test_player, test_nation, other_nation):
        """PUT /api/diplomacy only accepts neutral/war; friendly is set via friend-request flow."""
        db.commit()
        resp = auth_client.put(f"/api/diplomacy/{other_nation.id}", json={"status": "friendly"})
        assert resp.status_code == 422

    def test_set_war_creates_pending(self, db: Session, auth_client, test_player, test_nation, other_nation):
        """Declaring war returns war_pending — full war starts after 2 ticks."""
        db.commit()
        resp = auth_client.put(f"/api/diplomacy/{other_nation.id}", json={"status": "war"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "war_pending"

    def test_war_pending_to_neutral_blocked_within_24h(
        self, db: Session, auth_client, test_player, test_nation, other_nation
    ):
        """war_pending also enforces the 24h minimum before ending."""
        a, b = min(test_nation.id, other_nation.id), max(test_nation.id, other_nation.id)
        db.add(Diplomacy(
            nation_a=a, nation_b=b, status="war_pending",
            updated_at=datetime.now(timezone.utc),
        ))
        db.commit()
        resp = auth_client.put(f"/api/diplomacy/{other_nation.id}", json={"status": "neutral"})
        assert resp.status_code == 409, resp.text

    def test_war_pending_transitions_to_war_after_two_ticks(
        self, db: Session, test_player, test_nation, other_nation
    ):
        """Tick promotes war_pending to war once war_starts_at has passed."""
        a, b = min(test_nation.id, other_nation.id), max(test_nation.id, other_nation.id)
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.add(Diplomacy(
            nation_a=a, nation_b=b, status="war_pending",
            updated_at=past - timedelta(hours=4),
            war_starts_at=past,
        ))
        db.commit()
        from app.tasks.tick import run_tick
        run_tick()
        with SessionLocal() as s:
            row = s.query(Diplomacy).filter(Diplomacy.nation_a == a, Diplomacy.nation_b == b).first()
            assert row.status == "war", f"Expected war, got {row.status}"

    def test_war_pending_not_promoted_before_war_starts_at(
        self, db: Session, test_player, test_nation, other_nation
    ):
        """Tick must not promote war_pending before war_starts_at."""
        a, b = min(test_nation.id, other_nation.id), max(test_nation.id, other_nation.id)
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        db.add(Diplomacy(
            nation_a=a, nation_b=b, status="war_pending",
            updated_at=datetime.now(timezone.utc) - timedelta(hours=1),
            war_starts_at=future,
        ))
        db.commit()
        from app.tasks.tick import run_tick
        run_tick()
        with SessionLocal() as s:
            row = s.query(Diplomacy).filter(Diplomacy.nation_a == a, Diplomacy.nation_b == b).first()
            assert row.status == "war_pending", "Tick must not promote early"

    def test_set_neutral_from_friendly(
        self, db: Session, auth_client, test_player, test_nation, other_nation
    ):
        _set_diplomacy(db, test_nation.id, other_nation.id, "friendly")
        db.commit()
        resp = auth_client.put(f"/api/diplomacy/{other_nation.id}", json={"status": "neutral"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "neutral"

    def test_war_to_neutral_blocked_within_24h(
        self, db: Session, auth_client, test_player, test_nation, other_nation
    ):
        a, b = min(test_nation.id, other_nation.id), max(test_nation.id, other_nation.id)
        db.add(Diplomacy(
            nation_a=a, nation_b=b, status="war",
            updated_at=datetime.now(timezone.utc),
        ))
        db.commit()
        resp = auth_client.put(f"/api/diplomacy/{other_nation.id}", json={"status": "neutral"})
        assert resp.status_code == 409, resp.text
        assert "24" in resp.json()["detail"]

    def test_war_to_neutral_blocked_within_24h(
        self, db: Session, auth_client, test_player, test_nation, other_nation
    ):
        a, b = min(test_nation.id, other_nation.id), max(test_nation.id, other_nation.id)
        db.add(Diplomacy(
            nation_a=a, nation_b=b, status="war",
            updated_at=datetime.now(timezone.utc),
        ))
        db.commit()
        resp = auth_client.put(f"/api/diplomacy/{other_nation.id}", json={"status": "neutral"})
        assert resp.status_code == 409, resp.text

    def test_war_to_neutral_allowed_after_24h(
        self, db: Session, auth_client, test_player, test_nation, other_nation
    ):
        a, b = min(test_nation.id, other_nation.id), max(test_nation.id, other_nation.id)
        db.add(Diplomacy(
            nation_a=a, nation_b=b, status="war",
            updated_at=datetime.now(timezone.utc) - timedelta(hours=25),
        ))
        db.commit()
        resp = auth_client.put(f"/api/diplomacy/{other_nation.id}", json={"status": "neutral"})
        assert resp.status_code == 200, resp.text

    def test_set_war_blocked_on_vacation_nation(
        self, db: Session, auth_client, test_player, test_nation, other_player, other_nation
    ):
        other_player.vacation_mode = True
        other_player.vacation_since = datetime.now(timezone.utc)
        db.flush()
        db.commit()
        resp = auth_client.put(f"/api/diplomacy/{other_nation.id}", json={"status": "war"})
        assert resp.status_code == 409, resp.text

    def test_invalid_status_rejected(
        self, db: Session, auth_client, test_player, test_nation, other_nation
    ):
        db.commit()
        resp = auth_client.put(f"/api/diplomacy/{other_nation.id}", json={"status": "allied"})
        assert resp.status_code == 422, resp.text

    def test_cannot_set_status_on_self(
        self, db: Session, auth_client, test_player, test_nation
    ):
        db.commit()
        resp = auth_client.put(f"/api/diplomacy/{test_nation.id}", json={"status": "war"})
        assert resp.status_code == 409, resp.text


class TestGetDiplomacyStatus:
    """GET /api/diplomacy/{target_nation_id} returns current status."""

    def test_default_is_neutral(
        self, db: Session, auth_client, test_player, test_nation, other_nation
    ):
        db.commit()
        resp = auth_client.get(f"/api/diplomacy/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "neutral"

    def test_returns_war_when_at_war(
        self, db: Session, auth_client, test_player, test_nation, other_nation
    ):
        _set_diplomacy(db, test_nation.id, other_nation.id, "war")
        db.commit()
        resp = auth_client.get(f"/api/diplomacy/{other_nation.id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "war"

    def test_returns_friendly_when_friendly(
        self, db: Session, auth_client, test_player, test_nation, other_nation
    ):
        _set_diplomacy(db, test_nation.id, other_nation.id, "friendly")
        db.commit()
        resp = auth_client.get(f"/api/diplomacy/{other_nation.id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "friendly"


class TestGetRelations:
    """GET /api/diplomacy/relations returns all non-neutral relationships."""

    def test_empty_when_all_neutral(
        self, db: Session, auth_client, test_player, test_nation, other_nation
    ):
        db.commit()
        resp = auth_client.get("/api/diplomacy/relations")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_war_and_friendly_not_neutral(
        self, db: Session, auth_client, test_player, test_nation
    ):
        p2 = _make_player(db, "p2", "p2@example.com")
        p3 = _make_player(db, "p3", "p3@example.com")
        n2 = _make_nation(db, p2, "Nation 2")
        n3 = _make_nation(db, p3, "Nation 3")
        _set_diplomacy(db, test_nation.id, n2.id, "war")
        _set_diplomacy(db, test_nation.id, n3.id, "friendly")
        db.commit()

        resp = auth_client.get("/api/diplomacy/relations")
        assert resp.status_code == 200
        statuses = {r["nation_id"]: r["status"] for r in resp.json()}
        assert statuses[n2.id] == "war"
        assert statuses[n3.id] == "friendly"


# ===========================================================================
# 2. FLEET DISPATCH VALIDATION
# ===========================================================================


class TestFleetDispatchByDiplomacy:
    """Dispatch is gated by diplomacy status and territory type."""

    def _setup_two_nations(self, db: Session, test_player: Player):
        """Player nation at home, enemy nation at their territory. Returns (my_nation, my_home, enemy_nation, enemy_territory)."""
        my_nation = _make_nation(db, test_player, "My Nation")
        my_home = _make_territory(db, "0,0", nation_id=my_nation.id, is_colonized=True)
        my_nation.home_territory_id = my_home.id
        db.add(TerritoryPopulation(territory_id=my_home.id, current=500))
        _make_fleet(db, my_nation.id, my_home.id, unit_count=20)

        other_p = _make_player(db, "enemy", "enemy@example.com")
        enemy_nation = _make_nation(db, other_p, "Enemy Nation")
        return my_nation, my_home, enemy_nation

    def test_dispatch_to_friendly_planet_allowed(
        self, db: Session, auth_client, test_player: Player
    ):
        my_nation, my_home, enemy_nation = self._setup_two_nations(db, test_player)
        enemy_planet = _make_territory(db, "1,0", nation_id=enemy_nation.id, is_colonized=True)
        _set_diplomacy(db, my_nation.id, enemy_nation.id, "friendly")
        db.commit()

        resp = auth_client.post("/api/military/fleets/send", json={
            "from_territory_id": my_home.id,
            "to_territory_id": enemy_planet.id,
            "quantity": 5,
        })
        assert resp.status_code == 201, resp.text

    def test_dispatch_to_neutral_void_allowed(
        self, db: Session, auth_client, test_player: Player
    ):
        my_nation, my_home, enemy_nation = self._setup_two_nations(db, test_player)
        enemy_void = _make_void(db, "1,0", nation_id=enemy_nation.id)
        # neutral is the default — no need to set diplomacy
        db.commit()

        resp = auth_client.post("/api/military/fleets/send", json={
            "from_territory_id": my_home.id,
            "to_territory_id": enemy_void.id,
            "quantity": 5,
        })
        assert resp.status_code == 201, resp.text

    def test_dispatch_to_neutral_planet_blocked(
        self, db: Session, auth_client, test_player: Player
    ):
        my_nation, my_home, enemy_nation = self._setup_two_nations(db, test_player)
        enemy_planet = _make_territory(db, "1,0", nation_id=enemy_nation.id, is_colonized=True)
        # neutral is default
        db.commit()

        resp = auth_client.post("/api/military/fleets/send", json={
            "from_territory_id": my_home.id,
            "to_territory_id": enemy_planet.id,
            "quantity": 5,
        })
        assert resp.status_code == 409, resp.text

    def test_dispatch_to_war_planet_allowed(
        self, db: Session, auth_client, test_player: Player
    ):
        my_nation, my_home, enemy_nation = self._setup_two_nations(db, test_player)
        enemy_planet = _make_territory(db, "1,0", nation_id=enemy_nation.id, is_colonized=True)
        _set_diplomacy(db, my_nation.id, enemy_nation.id, "war")
        db.commit()

        resp = auth_client.post("/api/military/fleets/send", json={
            "from_territory_id": my_home.id,
            "to_territory_id": enemy_planet.id,
            "quantity": 5,
        })
        assert resp.status_code == 201, resp.text

    def test_dispatch_to_war_void_allowed(
        self, db: Session, auth_client, test_player: Player
    ):
        my_nation, my_home, enemy_nation = self._setup_two_nations(db, test_player)
        enemy_void = _make_void(db, "1,0", nation_id=enemy_nation.id)
        _set_diplomacy(db, my_nation.id, enemy_nation.id, "war")
        db.commit()

        resp = auth_client.post("/api/military/fleets/send", json={
            "from_territory_id": my_home.id,
            "to_territory_id": enemy_void.id,
            "quantity": 5,
        })
        assert resp.status_code == 201, resp.text


# ===========================================================================
# 3. FLEET ARRIVAL BY DIPLOMACY STATUS
# ===========================================================================


class TestFleetArrivalByDiplomacy:
    """Tick processes fleet arrivals according to diplomacy rules."""

    def _make_arriving_fleet(
        self, db: Session, attacker_nation_id: int, dest_id: int
    ) -> Fleet:
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        f = Fleet(
            nation_id=attacker_nation_id,
            origin_territory=None,
            destination_territory=dest_id,
            unit_count=5,
            status="in_transit",
            departs_at=past - timedelta(hours=2),
            arrives_at=past,
        )
        db.add(f)
        db.flush()
        return f

    def test_fleet_arrives_at_friendly_planet_lands_normally(self, db: Session, test_player):
        attacker_p = _make_player(db, "atk", "atk@example.com")
        attacker_n = _make_nation(db, attacker_p, "Attacker")
        defender_p = _make_player(db, "def", "def@example.com")
        defender_n = _make_nation(db, defender_p, "Defender")

        atk_home = _make_territory(db, "0,0", nation_id=attacker_n.id, is_colonized=True)
        def_planet = _make_territory(db, "1,0", nation_id=defender_n.id, is_colonized=True)
        attacker_n.home_territory_id = atk_home.id

        _set_diplomacy(db, attacker_n.id, defender_n.id, "friendly")
        fleet = self._make_arriving_fleet(db, attacker_n.id, def_planet.id)
        _commit_and_run_tick(db)

        with SessionLocal() as s:
            f = s.get(Fleet, fleet.id)
            # Should land (stationed or merged) — not pending_confirmation
            assert f is None or f.status != "pending_confirmation", (
                f"Fleet at friendly territory must not enter confirmation window (status={f.status if f else 'deleted/merged'})"
            )

    def test_fleet_arrives_at_war_planet_enters_confirmation(self, db: Session, test_player):
        attacker_p = _make_player(db, "atk", "atk@example.com")
        attacker_n = _make_nation(db, attacker_p, "Attacker")
        defender_p = _make_player(db, "def", "def@example.com")
        defender_n = _make_nation(db, defender_p, "Defender")

        atk_home = _make_territory(db, "0,0", nation_id=attacker_n.id, is_colonized=True)
        def_planet = _make_territory(db, "1,0", nation_id=defender_n.id, is_colonized=True)
        attacker_n.home_territory_id = atk_home.id

        _set_diplomacy(db, attacker_n.id, defender_n.id, "war")
        fleet = self._make_arriving_fleet(db, attacker_n.id, def_planet.id)
        _commit_and_run_tick(db)

        with SessionLocal() as s:
            f = s.get(Fleet, fleet.id)
            assert f is not None
            assert f.status == "pending_confirmation"

    def test_fleet_arrives_at_war_planet_generates_defender_alert(self, db: Session, test_player):
        attacker_p = _make_player(db, "atk", "atk@example.com")
        attacker_n = _make_nation(db, attacker_p, "Attacker")
        defender_p = _make_player(db, "def", "def@example.com")
        defender_n = _make_nation(db, defender_p, "Defender")

        atk_home = _make_territory(db, "0,0", nation_id=attacker_n.id, is_colonized=True)
        def_planet = _make_territory(db, "1,0", nation_id=defender_n.id, is_colonized=True)
        attacker_n.home_territory_id = atk_home.id

        _set_diplomacy(db, attacker_n.id, defender_n.id, "war")
        self._make_arriving_fleet(db, attacker_n.id, def_planet.id)
        _commit_and_run_tick(db)

        with SessionLocal() as s:
            alert = s.query(Event).filter(
                Event.type == "enemy_fleet_arrived",
                Event.payload["defender_nation_id"].as_integer() == defender_n.id,
            ).first()
            assert alert is not None, "Defender must receive enemy_fleet_arrived event for war planet entry"

    def test_fleet_arrives_at_war_void_lands_and_generates_alert(self, db: Session, test_player):
        attacker_p = _make_player(db, "atk", "atk@example.com")
        attacker_n = _make_nation(db, attacker_p, "Attacker")
        defender_p = _make_player(db, "def", "def@example.com")
        defender_n = _make_nation(db, defender_p, "Defender")

        atk_home = _make_territory(db, "0,0", nation_id=attacker_n.id, is_colonized=True)
        def_void = _make_void(db, "1,0", nation_id=defender_n.id)
        attacker_n.home_territory_id = atk_home.id

        _set_diplomacy(db, attacker_n.id, defender_n.id, "war")
        fleet = self._make_arriving_fleet(db, attacker_n.id, def_void.id)
        _commit_and_run_tick(db)

        with SessionLocal() as s:
            # Fleet must NOT be in pending_confirmation (void → land normally)
            f = s.get(Fleet, fleet.id)
            assert f is None or f.status != "pending_confirmation", (
                "Fleet at war-enemy void territory must not enter confirmation window"
            )
            # But defender must receive an alert
            alert = s.query(Event).filter(
                Event.type == "enemy_fleet_entered_territory",
                Event.payload["defender_nation_id"].as_integer() == defender_n.id,
            ).first()
            assert alert is not None, "Defender must be alerted when enemy fleet enters void territory during war"

    def test_fleet_arrives_at_war_pending_planet_lands_not_confirmation(self, db: Session, test_player):
        """During war_pending, fleet arriving at a planet lands — no confirmation window yet."""
        attacker_p = _make_player(db, "atk", "atk@example.com")
        attacker_n = _make_nation(db, attacker_p, "Attacker")
        defender_p = _make_player(db, "def", "def@example.com")
        defender_n = _make_nation(db, defender_p, "Defender")

        atk_home = _make_territory(db, "0,0", nation_id=attacker_n.id, is_colonized=True)
        def_planet = _make_territory(db, "1,0", nation_id=defender_n.id, is_colonized=True)
        attacker_n.home_territory_id = atk_home.id

        _set_diplomacy(db, attacker_n.id, defender_n.id, "war_pending")
        fleet = self._make_arriving_fleet(db, attacker_n.id, def_planet.id)
        _commit_and_run_tick(db)

        with SessionLocal() as s:
            f = s.get(Fleet, fleet.id)
            assert f is None or f.status != "pending_confirmation", (
                "Fleet must not enter confirmation window during war_pending"
            )

    def test_fleet_arrives_at_war_pending_planet_generates_alert(self, db: Session, test_player):
        """During war_pending, fleet arriving at a planet still alerts the defender."""
        attacker_p = _make_player(db, "atk", "atk@example.com")
        attacker_n = _make_nation(db, attacker_p, "Attacker")
        defender_p = _make_player(db, "def", "def@example.com")
        defender_n = _make_nation(db, defender_p, "Defender")

        atk_home = _make_territory(db, "0,0", nation_id=attacker_n.id, is_colonized=True)
        def_planet = _make_territory(db, "1,0", nation_id=defender_n.id, is_colonized=True)
        attacker_n.home_territory_id = atk_home.id

        _set_diplomacy(db, attacker_n.id, defender_n.id, "war_pending")
        self._make_arriving_fleet(db, attacker_n.id, def_planet.id)
        _commit_and_run_tick(db)

        with SessionLocal() as s:
            alert = s.query(Event).filter(
                Event.type == "enemy_fleet_entered_territory",
                Event.payload["defender_nation_id"].as_integer() == defender_n.id,
            ).first()
            assert alert is not None, "Defender must be alerted during war_pending planet entry"

    def test_fleet_arrives_at_neutral_void_lands_without_alert(self, db: Session, test_player):
        attacker_p = _make_player(db, "atk", "atk@example.com")
        attacker_n = _make_nation(db, attacker_p, "Attacker")
        defender_p = _make_player(db, "def", "def@example.com")
        defender_n = _make_nation(db, defender_p, "Defender")

        atk_home = _make_territory(db, "0,0", nation_id=attacker_n.id, is_colonized=True)
        def_void = _make_void(db, "1,0", nation_id=defender_n.id)
        attacker_n.home_territory_id = atk_home.id

        # neutral is default — no diplomacy row needed
        fleet = self._make_arriving_fleet(db, attacker_n.id, def_void.id)
        _commit_and_run_tick(db)

        with SessionLocal() as s:
            f = s.get(Fleet, fleet.id)
            assert f is None or f.status != "pending_confirmation"
            # No enemy_fleet_entered_territory alert for neutral
            alert = s.query(Event).filter(
                Event.type == "enemy_fleet_entered_territory",
                Event.payload["defender_nation_id"].as_integer() == defender_n.id,
            ).first()
            assert alert is None, "Neutral void entry must not generate an alert"
