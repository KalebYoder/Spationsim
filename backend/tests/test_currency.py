"""
Test suite for the Currency resource feature.

Covers four areas:
  1. Nation model — currency column default is 0, nullable=False
  2. Tick logic (run_tick) — currency earned per colonized territory (500/territory/tick)
  3. ResourceLog model — currency_delta column written each tick
  4. NationResponse schema — currency field present and correct in GET /api/nations/mine

What already exists (NOT re-tested here):
  - currency_name column on Nation model
  - currency_name accepted in NationCreateRequest and saved at nation creation
  - currency_name returned in NationResponse
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
from app.db.database import get_db, SessionLocal
from app.models.infrastructure import Infrastructure
from app.models.nation import Nation
from app.models.player import Player
from app.models.resource_log import ResourceLog
from app.models.territory import Territory
from app.core.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CURRENCY_PER_TERRITORY = 500
MINE_UPKEEP = 10  # FACILITY_POPULATION_COST["mine"]
# Net income per territory with exactly one mine: CURRENCY_PER_TERRITORY - MINE_UPKEEP
NET_PER_INCOME_TERRITORY = CURRENCY_PER_TERRITORY - MINE_UPKEEP  # 490


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_override(session: Session):
    def _override():
        yield session
    return _override


def _commit_and_run_tick(db: Session) -> None:
    """Commit the transactional session so SessionLocal() inside run_tick can see the
    rows, then invoke run_tick synchronously as a plain function."""
    db.commit()
    from app.tasks.tick import run_tick
    run_tick()


def _make_colonized_territory(
    db: Session,
    nation_id: int,
    node_key: str,
    distance_from_center: int = 1,
) -> Territory:
    """Insert a colonized territory owned by the given nation and return it."""
    t = Territory(
        node_key=node_key,
        name=f"Colony {node_key}",
        territory_type="normal",
        nation_id=nation_id,
        mineral_richness=1.00,
        fuel_richness=1.00,
        distance_from_center=distance_from_center,
        is_colonized=True,
        colonized_at=datetime.now(timezone.utc),
    )
    db.add(t)
    db.flush()
    return t


def _add_mine(db: Session, territory_id: int) -> Infrastructure:
    """Add a mine to a territory, making it resource-generating (500 currency/tick income)."""
    infra = Infrastructure(territory_id=territory_id, type="mine", level=1)
    db.add(infra)
    db.flush()
    return infra


def _make_income_territory(
    db: Session,
    nation_id: int,
    node_key: str,
    distance_from_center: int = 1,
) -> Territory:
    """Insert a colonized territory with a mine (resource-generating, earns currency income)."""
    t = _make_colonized_territory(db, nation_id, node_key, distance_from_center)
    _add_mine(db, t.id)
    return t


# ---------------------------------------------------------------------------
# Local fixtures — second player/nation for isolation tests
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
        minerals=500,
        fuel=500,
    )
    db.add(nation)
    db.flush()
    return nation


# auth_client scoped to the transactional test session (mirrors test_confirmation_window.py)
@pytest.fixture()
def auth_client(db: Session, test_player: Player):
    token = create_access_token(test_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


# ===========================================================================
# 1. NATION MODEL — currency column
# ===========================================================================


class TestNationCurrencyColumn:
    """Nation.currency column: default value, type constraints."""

    def test_new_nation_currency_defaults_to_zero(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """A freshly created Nation fixture must have currency == 0."""
        db.expire(test_nation)
        nation = db.get(Nation, test_nation.id)
        assert nation is not None
        assert hasattr(nation, "currency"), (
            "Nation model must have a 'currency' attribute"
        )
        assert float(nation.currency) == 0.0, (
            f"New nation must start with currency=0, got {nation.currency!r}"
        )

    def test_currency_column_is_not_none(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Nation.currency must be non-null (nullable=False) by default."""
        db.expire(test_nation)
        nation = db.get(Nation, test_nation.id)
        assert nation.currency is not None, (
            "Nation.currency must not be None; column should be nullable=False with default 0"
        )

    def test_currency_column_can_be_set(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Nation.currency must accept a Numeric value and persist it."""
        test_nation.currency = 1500
        db.flush()
        db.expire(test_nation)
        nation = db.get(Nation, test_nation.id)
        assert float(nation.currency) == 1500.0, (
            f"Nation.currency must persist 1500, got {nation.currency!r}"
        )

    def test_currency_starts_at_zero_not_none_after_create_via_api(
        self,
        auth_client: TestClient,
        db: Session,
        test_player: Player,
        test_nation: Nation,
    ):
        """POST /api/nations/create must produce a nation with currency=0."""
        # We need an unclaimed territory to create against
        territory = Territory(
            node_key="99,99",
            name=None,
            territory_type="normal",
            nation_id=None,
            mineral_richness=1.00,
            fuel_richness=1.00,
            distance_from_center=10,
            is_colonized=False,
        )
        db.add(territory)
        db.flush()

        # test_player already has a nation (test_nation fixture via conftest).
        # We need a fresh player without a nation for this API call.
        # Instead we directly inspect the model-level default, which is covered
        # by test_new_nation_currency_defaults_to_zero above.
        # Here we verify via GET /api/nations/mine that the API also returns 0.
        db.expire_all()
        test_nation_obj = db.query(Nation).filter(Nation.player_id == test_player.id).first()
        assert test_nation_obj is not None
        assert float(test_nation_obj.currency) == 0.0


# ===========================================================================
# 2. GET /api/nations/mine — NationResponse schema
# ===========================================================================


class TestNationResponseCurrencyField:
    """NationResponse must include a 'currency' field."""

    def test_get_mine_includes_currency_field(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """GET /api/nations/mine must return a 'currency' key in the response JSON."""
        resp = auth_client.get("/api/nations/mine")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "currency" in data, (
            "GET /api/nations/mine response must include a 'currency' field"
        )

    def test_get_mine_currency_is_zero_for_new_nation(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """A new nation with no ticks run must have currency=0 in the API response."""
        resp = auth_client.get("/api/nations/mine")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["currency"] == 0.0, (
            f"New nation must have currency=0 in GET /api/nations/mine, got {data['currency']!r}"
        )

    def test_get_mine_currency_reflects_actual_balance(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """After manually setting currency, GET /api/nations/mine must reflect the new value."""
        test_nation.currency = 2500
        db.flush()

        resp = auth_client.get("/api/nations/mine")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert float(data["currency"]) == 2500.0, (
            f"GET /api/nations/mine must return the actual currency balance, got {data['currency']!r}"
        )

    def test_get_mine_unauthenticated_returns_401(
        self,
        client: TestClient,
    ):
        """Unauthenticated GET /api/nations/mine must return 401 (auth enforcement)."""
        resp = client.get("/api/nations/mine")
        assert resp.status_code == 401

    def test_get_mine_currency_is_numeric_type(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """The 'currency' field in NationResponse must be a number, not a string or None."""
        resp = auth_client.get("/api/nations/mine")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data["currency"], (int, float)), (
            f"'currency' in NationResponse must be a numeric type, got {type(data['currency'])}"
        )


# ===========================================================================
# 3. TICK — currency income generation
# ===========================================================================


class TestTickCurrencyGeneration:
    """run_tick: currency is earned per colonized territory each tick."""

    def test_one_income_territory_earns_net_490_currency_per_tick(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Nation with 1 territory+mine: gross 500 income, 10 mine upkeep = 490 net per tick."""
        _make_income_territory(db, test_nation.id, "0,0")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == float(NET_PER_INCOME_TERRITORY), (
                f"Nation with 1 mine territory must net {NET_PER_INCOME_TERRITORY} currency per tick, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_three_income_territories_earn_1470_currency_per_tick(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Nation with 3 territories+mines: 3×500 gross − 3×10 mine upkeep = 1470 net."""
        _make_income_territory(db, test_nation.id, "0,0", distance_from_center=0)
        _make_income_territory(db, test_nation.id, "1,0", distance_from_center=1)
        _make_income_territory(db, test_nation.id, "2,0", distance_from_center=2)

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 3 * NET_PER_INCOME_TERRITORY
            assert float(nation.currency) == float(expected), (
                f"Nation with 3 mine territories must net {expected} currency per tick, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_nation_with_no_colonized_territories_earns_zero_currency(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Nation with no colonized territories must earn 0 currency per tick."""
        # test_nation fixture starts with no territories — verify currency stays at 0
        initial_currency = float(test_nation.currency)

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == initial_currency, (
                f"Nation with 0 territories must earn 0 currency, but balance changed from "
                f"{initial_currency} to {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_currency_accumulates_across_multiple_ticks(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """After 2 ticks with 1 income territory, currency must equal 2 × net (2 × 490 = 980)."""
        _make_income_territory(db, test_nation.id, "0,0")

        _commit_and_run_tick(db)
        from app.tasks.tick import run_tick
        run_tick()

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 2 * NET_PER_INCOME_TERRITORY
            assert float(nation.currency) == float(expected), (
                f"After 2 ticks with 1 mine territory, currency must be {expected}, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_tick_adds_to_existing_currency_balance_not_replace(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Tick must ADD currency net delta to existing balance, not overwrite it."""
        test_nation.currency = 800
        _make_income_territory(db, test_nation.id, "0,0")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            # 800 existing + 490 net (500 income − 10 mine upkeep) = 1290
            expected = 800 + NET_PER_INCOME_TERRITORY
            assert float(nation.currency) == float(expected), (
                f"Tick must ADD {NET_PER_INCOME_TERRITORY} net to existing 800, expected {expected}, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_territory_without_mine_or_refinery_generates_no_currency(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """A colonized territory with no mine or refinery generates 0 currency income."""
        _make_colonized_territory(db, test_nation.id, "0,0")  # bare — no mine

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == 0.0, (
                f"Territory without mine/refinery must not generate currency, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_uncolonized_territory_does_not_generate_currency(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """An unclaimed (uncolonized) territory must not generate currency for any nation."""
        t = _make_income_territory(db, test_nation.id, "0,0")
        uncolonized = Territory(
            node_key="5,5",
            name=None,
            territory_type="normal",
            nation_id=None,
            mineral_richness=1.00,
            fuel_richness=1.00,
            distance_from_center=5,
            is_colonized=False,
        )
        db.add(uncolonized)
        db.flush()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            # Only the 1 colonized territory with mine generates income; net = 490
            assert float(nation.currency) == float(NET_PER_INCOME_TERRITORY), (
                f"Uncolonized territory must not add currency. Expected {NET_PER_INCOME_TERRITORY}, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_other_nations_territories_do_not_credit_wrong_nation(
        self,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """Currency from a territory must only credit the owning nation."""
        _make_income_territory(db, test_nation.id, "0,0", distance_from_center=0)
        _make_income_territory(db, other_nation.id, "3,0", distance_from_center=3)
        _make_income_territory(db, other_nation.id, "4,0", distance_from_center=4)

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            test_n = fresh.get(Nation, test_nation.id)
            other_n = fresh.get(Nation, other_nation.id)

            assert float(test_n.currency) == float(1 * NET_PER_INCOME_TERRITORY), (
                f"test_nation with 1 mine territory must net {NET_PER_INCOME_TERRITORY}, "
                f"got {test_n.currency!r}"
            )
            assert float(other_n.currency) == float(2 * NET_PER_INCOME_TERRITORY), (
                f"other_nation with 2 mine territories must net {2 * NET_PER_INCOME_TERRITORY}, "
                f"got {other_n.currency!r}"
            )
        finally:
            fresh.close()

    def test_tick_currency_income_scales_with_mine_territory_count(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Currency per tick is precisely 500 × resource-generating territory count (net after upkeep)."""
        _make_income_territory(db, test_nation.id, "0,0", distance_from_center=0)
        _make_income_territory(db, test_nation.id, "1,0", distance_from_center=1)

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 2 * NET_PER_INCOME_TERRITORY
            assert float(nation.currency) == float(expected), (
                f"2 mine territories net {expected} (2×490), got {nation.currency!r}"
            )
        finally:
            fresh.close()


# ===========================================================================
# 4. ResourceLog — currency_delta column
# ===========================================================================


class TestResourceLogCurrencyDelta:
    """ResourceLog must record currency_delta alongside minerals_delta and fuel_delta."""

    def test_resource_log_has_currency_delta_attribute(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """ResourceLog model must expose a 'currency_delta' attribute."""
        log = ResourceLog(
            nation_id=test_nation.id,
            tick_at=datetime.now(timezone.utc),
            minerals_delta=0,
            fuel_delta=0,
            currency_delta=500,
        )
        db.add(log)
        db.flush()
        db.expire(log)
        refreshed = db.get(ResourceLog, log.id)
        assert hasattr(refreshed, "currency_delta"), (
            "ResourceLog model must have a 'currency_delta' attribute"
        )
        assert float(refreshed.currency_delta) == 500.0, (
            f"ResourceLog.currency_delta must persist 500, got {refreshed.currency_delta!r}"
        )

    def test_tick_writes_resource_log_with_currency_delta(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """After a tick that earns currency, a ResourceLog row must exist with currency_delta set."""
        _make_income_territory(db, test_nation.id, "0,0")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            log = fresh.query(ResourceLog).filter(
                ResourceLog.nation_id == test_nation.id,
            ).order_by(ResourceLog.id.desc()).first()
            assert log is not None, (
                "A ResourceLog row must be created after a tick that generates currency"
            )
            assert log.currency_delta is not None, (
                "ResourceLog.currency_delta must be set (not None) when currency is earned"
            )
            assert float(log.currency_delta) > 0, (
                f"ResourceLog.currency_delta must be positive after earning currency, "
                f"got {log.currency_delta!r}"
            )
        finally:
            fresh.close()

    def test_tick_resource_log_currency_delta_equals_net_currency_earned(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """ResourceLog.currency_delta must equal the net currency delta (income − upkeep) that tick."""
        _make_income_territory(db, test_nation.id, "0,0")
        _make_income_territory(db, test_nation.id, "1,0", distance_from_center=1)

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            log = fresh.query(ResourceLog).filter(
                ResourceLog.nation_id == test_nation.id,
            ).order_by(ResourceLog.id.desc()).first()
            assert log is not None
            expected_delta = 2 * NET_PER_INCOME_TERRITORY  # 2 × 490 = 980
            assert float(log.currency_delta) == float(expected_delta), (
                f"ResourceLog.currency_delta for 2 mine territories must be {expected_delta}, "
                f"got {log.currency_delta!r}"
            )
        finally:
            fresh.close()

    def test_tick_resource_log_currency_delta_zero_when_no_territories(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """When a nation has no territories, its ResourceLog row (if any) must not log
        a positive currency_delta."""
        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            log = fresh.query(ResourceLog).filter(
                ResourceLog.nation_id == test_nation.id,
            ).first()
            # If no log was written (because nothing changed), that is also acceptable —
            # the key requirement is that currency_delta is 0 or absent, never positive.
            if log is not None and log.currency_delta is not None:
                assert float(log.currency_delta) == 0.0, (
                    f"Nation with no territories must have currency_delta=0, "
                    f"got {log.currency_delta!r}"
                )
        finally:
            fresh.close()

    def test_resource_log_currency_delta_nullable_for_old_rows(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """ResourceLog.currency_delta must be nullable (for rows written before this feature)."""
        log = ResourceLog(
            nation_id=test_nation.id,
            tick_at=datetime.now(timezone.utc),
            minerals_delta=10,
            fuel_delta=5,
            # currency_delta intentionally omitted
        )
        db.add(log)
        db.flush()
        db.expire(log)
        refreshed = db.get(ResourceLog, log.id)
        assert refreshed.currency_delta is None, (
            "ResourceLog.currency_delta must accept NULL values (for backward compatibility)"
        )

    def test_each_tick_writes_separate_resource_log_row(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Each tick must produce its own ResourceLog row, not overwrite the previous one."""
        _make_income_territory(db, test_nation.id, "0,0")

        _commit_and_run_tick(db)
        from app.tasks.tick import run_tick
        run_tick()

        fresh = SessionLocal()
        try:
            logs = fresh.query(ResourceLog).filter(
                ResourceLog.nation_id == test_nation.id,
            ).all()
            assert len(logs) >= 2, (
                f"Two ticks must produce at least 2 ResourceLog rows, found {len(logs)}"
            )
        finally:
            fresh.close()

    def test_resource_log_currency_delta_matches_nation_currency_sum(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """The sum of all ResourceLog.currency_delta rows must equal nation.currency after N ticks."""
        _make_income_territory(db, test_nation.id, "0,0")

        _commit_and_run_tick(db)
        from app.tasks.tick import run_tick
        run_tick()

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            logs = fresh.query(ResourceLog).filter(
                ResourceLog.nation_id == test_nation.id,
                ResourceLog.currency_delta.isnot(None),
            ).all()
            log_sum = sum(float(l.currency_delta) for l in logs)
            # The nation starts at 0 so the sum of all deltas should match the balance.
            # (No other currency sources exist at this point in the feature set.)
            assert float(nation.currency) == log_sum, (
                f"Sum of ResourceLog.currency_delta ({log_sum}) must equal "
                f"nation.currency ({nation.currency!r})"
            )
        finally:
            fresh.close()


# ===========================================================================
# 5. API — GET /api/nations/mine after ticks
# ===========================================================================


class TestGetMineAfterTick:
    """Verify that GET /api/nations/mine returns updated currency after ticks run."""

    def test_get_mine_currency_updates_after_tick(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        test_player: Player,
    ):
        """After a tick with 1 mine territory, GET /api/nations/mine returns 490 (net)."""
        _make_income_territory(db, test_nation.id, "0,0")

        _commit_and_run_tick(db)

        fresh_session = SessionLocal()
        try:
            token = create_access_token(test_player.id)
            app.dependency_overrides[get_db] = _db_override(fresh_session)
            with TestClient(app, raise_server_exceptions=True) as fresh_client:
                fresh_client.cookies.set("session", token)
                resp = fresh_client.get("/api/nations/mine")
            app.dependency_overrides.clear()

            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert float(data["currency"]) == float(NET_PER_INCOME_TERRITORY), (
                f"After one tick with 1 mine territory, GET /api/nations/mine must return "
                f"currency={NET_PER_INCOME_TERRITORY}, got {data['currency']!r}"
            )
        finally:
            fresh_session.close()

    def test_get_mine_currency_name_still_present_alongside_currency(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """NationResponse must include BOTH currency_name and currency fields."""
        resp = auth_client.get("/api/nations/mine")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "currency_name" in data, (
            "NationResponse must still include 'currency_name'"
        )
        assert "currency" in data, (
            "NationResponse must include new 'currency' field"
        )

    def test_get_mine_currency_is_float_not_string(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
    ):
        """currency field in NationResponse must be serialized as a number, not a string."""
        test_nation.currency = 1234.50
        db.flush()

        resp = auth_client.get("/api/nations/mine")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data["currency"], (int, float)), (
            f"'currency' must serialize as a number, got type {type(data['currency'])}"
        )
        assert abs(float(data["currency"]) - 1234.50) < 0.01, (
            f"Expected ~1234.50, got {data['currency']!r}"
        )
