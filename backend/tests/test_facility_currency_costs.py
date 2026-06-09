"""
Test suite for facility currency costs and nation starting currency.

Covers:
  1. Nation creation — POST /api/nations gives 2000 starting currency
  2. Mine build — costs 500 currency (in addition to minerals/fuel)
  3. Refinery build — costs 500 currency
  4. Shipyard build — costs 1000 currency
  5. Insufficient currency — build request rejected with 409 when currency < cost
  6. Currency deducted alongside minerals and fuel (not instead of them)
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
from app.models.nation import Nation
from app.models.player import Player
from app.models.territory import Territory
from app.models.territory_population import TerritoryPopulation
from app.core.security import create_access_token, hash_password
from app.constants import FACILITY_COSTS, POPULATION_START

MINE_CURRENCY_COST = 500
REFINERY_CURRENCY_COST = 500
SHIPYARD_CURRENCY_COST = 2000
NATION_STARTING_CURRENCY = 2000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_override(session: Session):
    def _override():
        yield session
    return _override


def _make_territory(
    db: Session,
    node_key: str,
    nation_id: int | None = None,
    is_owned: bool = False,
    territory_type: str = "normal",
) -> Territory:
    t = Territory(
        node_key=node_key,
        name=f"Planet {node_key}",
        territory_type=territory_type,
        nation_id=nation_id,
        mineral_richness=2,
        fuel_richness=2,
        distance_from_center=1,
        is_owned=is_owned,
        owned_at=datetime.now(timezone.utc) if is_owned else None,
    )
    db.add(t)
    db.flush()
    return t


def _make_nation_with_resources(
    db: Session,
    player: Player,
    minerals: float = 1000,
    fuel: float = 1000,
    currency: float = 2000,
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


def _colonize(db: Session, nation: Nation, territory: Territory) -> None:
    territory.nation_id = nation.id
    territory.is_owned = True
    territory.owned_at = datetime.now(timezone.utc)
    db.add(TerritoryPopulation(
        territory_id=territory.id,
        current=POPULATION_START * 10,  # plenty of population to staff
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
def nation_with_territory(db: Session, test_player: Player):
    """Nation owning one colonized territory with ample resources."""
    nation = _make_nation_with_resources(db, test_player)
    territory = _make_territory(db, "home-001", nation_id=nation.id, is_owned=True)
    nation.home_territory_id = territory.id
    db.add(TerritoryPopulation(
        territory_id=territory.id,
        current=POPULATION_START * 10,
    ))
    db.flush()
    return nation, territory


# ===========================================================================
# 1. NATION CREATION — starting currency
# ===========================================================================


class TestNationStartingCurrency:
    """POST /api/nations must give every new nation 2000 starting currency."""

    def test_new_nation_has_2000_currency(self, db: Session, auth_client, test_player: Player):
        territory = _make_territory(db, "start-001")
        db.commit()

        resp = auth_client.post("/api/nations", json={
            "name": "Starborn Empire",
            "currency_name": "Credits",
            "flag_color": "#FF5733",
            "home_territory_id": territory.id,
            "home_planet_name": "New Eden",
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["currency"] == NATION_STARTING_CURRENCY, (
            f"Expected starting currency {NATION_STARTING_CURRENCY}, got {data['currency']}"
        )

    def test_new_nation_currency_in_get_mine(self, db: Session, auth_client, test_player: Player):
        """GET /api/nations/mine also reflects 2000 starting currency."""
        territory = _make_territory(db, "start-002")
        db.commit()

        auth_client.post("/api/nations", json={
            "name": "Galactic Union",
            "currency_name": "Sols",
            "flag_color": "#3A86FF",
            "home_territory_id": territory.id,
            "home_planet_name": "Origin",
        })

        resp = auth_client.get("/api/nations/mine")
        assert resp.status_code == 200, resp.text
        assert resp.json()["currency"] == NATION_STARTING_CURRENCY


# ===========================================================================
# 2. MINE BUILD — 500 currency cost
# ===========================================================================


class TestMineCurrencyCost:
    """Building a mine must deduct 500 currency."""

    def test_mine_deducts_500_currency(
        self, db: Session, auth_client, nation_with_territory
    ):
        nation, territory = nation_with_territory
        db.commit()

        resp = auth_client.post("/api/facilities", json={
            "territory_id": territory.id,
            "type": "mine",
        })
        assert resp.status_code == 201, resp.text

        db.expire(nation)
        nation = db.get(Nation, nation.id)
        assert float(nation.currency) == 2000 - MINE_CURRENCY_COST, (
            f"Expected currency {2000 - MINE_CURRENCY_COST}, got {nation.currency}"
        )

    def test_mine_also_deducts_minerals_and_fuel(
        self, db: Session, auth_client, nation_with_territory
    ):
        nation, territory = nation_with_territory
        initial_minerals = float(nation.minerals)
        initial_fuel = float(nation.fuel)
        mine_cost = FACILITY_COSTS["mine"]
        db.commit()

        auth_client.post("/api/facilities", json={"territory_id": territory.id, "type": "mine"})

        db.expire(nation)
        nation = db.get(Nation, nation.id)
        assert float(nation.minerals) == initial_minerals - mine_cost["minerals"]
        assert float(nation.fuel) == initial_fuel - mine_cost["fuel"]

    def test_mine_rejected_when_currency_insufficient(
        self, db: Session, auth_client, test_player: Player
    ):
        nation = _make_nation_with_resources(
            db, test_player, minerals=1000, fuel=1000, currency=MINE_CURRENCY_COST - 1
        )
        territory = _make_territory(db, "mine-poor-001", nation_id=nation.id, is_owned=True)
        nation.home_territory_id = territory.id
        db.add(TerritoryPopulation(territory_id=territory.id, current=500))
        db.commit()

        resp = auth_client.post("/api/facilities", json={"territory_id": territory.id, "type": "mine"})
        assert resp.status_code == 409, resp.text


# ===========================================================================
# 3. REFINERY BUILD — 500 currency cost
# ===========================================================================


class TestRefineryCurrencyCost:
    """Building a refinery must deduct 500 currency."""

    def test_refinery_deducts_500_currency(
        self, db: Session, auth_client, nation_with_territory
    ):
        nation, territory = nation_with_territory
        db.commit()

        resp = auth_client.post("/api/facilities", json={
            "territory_id": territory.id,
            "type": "refinery",
        })
        assert resp.status_code == 201, resp.text

        db.expire(nation)
        nation = db.get(Nation, nation.id)
        assert float(nation.currency) == 2000 - REFINERY_CURRENCY_COST, (
            f"Expected currency {2000 - REFINERY_CURRENCY_COST}, got {nation.currency}"
        )

    def test_refinery_rejected_when_currency_insufficient(
        self, db: Session, auth_client, test_player: Player
    ):
        nation = _make_nation_with_resources(
            db, test_player, minerals=1000, fuel=1000, currency=REFINERY_CURRENCY_COST - 1
        )
        territory = _make_territory(db, "ref-poor-001", nation_id=nation.id, is_owned=True)
        nation.home_territory_id = territory.id
        db.add(TerritoryPopulation(territory_id=territory.id, current=500))
        db.commit()

        resp = auth_client.post("/api/facilities", json={"territory_id": territory.id, "type": "refinery"})
        assert resp.status_code == 409, resp.text


# ===========================================================================
# 4. SHIPYARD BUILD — 2000 currency cost
# ===========================================================================


class TestShipyardCurrencyCost:
    """Building a shipyard must deduct 2000 currency."""

    def test_shipyard_deducts_2000_currency(
        self, db: Session, auth_client, nation_with_territory
    ):
        nation, territory = nation_with_territory
        db.commit()

        resp = auth_client.post("/api/facilities", json={
            "territory_id": territory.id,
            "type": "shipyard",
        })
        assert resp.status_code == 201, resp.text

        db.expire(nation)
        nation = db.get(Nation, nation.id)
        assert float(nation.currency) == 2000 - SHIPYARD_CURRENCY_COST, (
            f"Expected currency {2000 - SHIPYARD_CURRENCY_COST}, got {nation.currency}"
        )

    def test_shipyard_rejected_when_currency_insufficient(
        self, db: Session, auth_client, test_player: Player
    ):
        nation = _make_nation_with_resources(
            db, test_player, minerals=1000, fuel=1000, currency=SHIPYARD_CURRENCY_COST - 1
        )
        territory = _make_territory(db, "sy-poor-001", nation_id=nation.id, is_owned=True)
        nation.home_territory_id = territory.id
        db.add(TerritoryPopulation(territory_id=territory.id, current=500))
        db.commit()

        resp = auth_client.post("/api/facilities", json={"territory_id": territory.id, "type": "shipyard"})
        assert resp.status_code == 409, resp.text

    def test_shipyard_with_exactly_2000_currency_succeeds(
        self, db: Session, auth_client, test_player: Player
    ):
        """Exactly 2000 currency is sufficient — boundary condition."""
        nation = _make_nation_with_resources(
            db, test_player, minerals=1000, fuel=1000, currency=SHIPYARD_CURRENCY_COST
        )
        territory = _make_territory(db, "sy-exact-001", nation_id=nation.id, is_owned=True)
        nation.home_territory_id = territory.id
        db.add(TerritoryPopulation(territory_id=territory.id, current=500))
        db.commit()

        resp = auth_client.post("/api/facilities", json={"territory_id": territory.id, "type": "shipyard"})
        assert resp.status_code == 201, resp.text

        db.expire(nation)
        nation = db.get(Nation, nation.id)
        assert float(nation.currency) == 0


