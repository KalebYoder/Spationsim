"""
Test suite for currency upkeep costs in the tick system.

Covers:
  1. Facilities have no currency upkeep — buildings do not subtract from currency each tick.
     Population assignment (staffing) remains a hard constraint but is not a currency cost.
  2. Fighter upkeep — 2 currency per starfighter (unit_count) per tick across all Fleet
     rows owned by the nation, regardless of fleet status.
  3. Combined upkeep — fighter upkeep is the only currency drain; facilities add no cost.
  4. ResourceLog accuracy — currency_delta written to the log equals net (income − fighter_upkeep).
  5. Nation isolation — Nation A's units/facilities never affect Nation B's upkeep.
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
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.fleet import Fleet
from app.models.infrastructure import Infrastructure
from app.models.nation import Nation
from app.models.player import Player
from app.models.resource_log import ResourceLog
from app.models.territory import Territory
from app.core.security import hash_password

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CURRENCY_PER_FACILITY = 30
FIGHTER_UPKEEP_PER_UNIT = 2
TERRITORY_UPKEEP_K = 10  # k × n² territory count currency upkeep, mirrors constants.py


# ---------------------------------------------------------------------------
# Helpers (mirror test_currency.py)
# ---------------------------------------------------------------------------


def _commit_and_run_tick(db: Session) -> None:
    """Commit the transactional test session so SessionLocal() inside run_tick
    can see the rows, then invoke run_tick synchronously."""
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


def _make_infrastructure(
    db: Session,
    territory_id: int,
    facility_type: str,
) -> Infrastructure:
    """Add one Infrastructure row of the given type to a territory."""
    infra = Infrastructure(
        territory_id=territory_id,
        type=facility_type,
        level=1,
    )
    db.add(infra)
    db.flush()
    return infra


def _make_fleet(
    db: Session,
    nation_id: int,
    origin_territory_id: int,
    unit_count: int,
    status: str = "stationed",
) -> Fleet:
    """Create a fleet row with the given unit count and status."""
    fleet = Fleet(
        nation_id=nation_id,
        name=f"Fleet-{status}-{unit_count}",
        origin_territory=origin_territory_id,
        destination_territory=None,
        unit_count=unit_count,
        status=status,
        standing_order="hold",
    )
    db.add(fleet)
    db.flush()
    return fleet


# ---------------------------------------------------------------------------
# Local fixtures — second player/nation for isolation tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def other_player(db: Session) -> Player:
    player = Player(
        username="otherplayer_upkeep",
        email="other_upkeep@example.com",
        password_hash=hash_password("otherpassword123"),
    )
    db.add(player)
    db.flush()
    return player


@pytest.fixture()
def other_nation(db: Session, other_player: Player) -> Nation:
    nation = Nation(
        player_id=other_player.id,
        name="Other Nation Upkeep",
        minerals=500,
        fuel=500,
        currency=0,
    )
    db.add(nation)
    db.flush()
    return nation


# ===========================================================================
# 1. FACILITIES HAVE NO CURRENCY UPKEEP
# ===========================================================================


class TestFacilitiesHaveNoCurrencyUpkeep:
    """Facilities do not cost currency per tick.
    Population assignment is a hard constraint (you cannot staff a mine without pop),
    but it is not converted into a currency drain at tick time."""

    def test_mine_on_1_territory_earns_30(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """1 mine, n=1: income=30, territory_upkeep=10×1²=10, net=20."""
        territory = _make_colonized_territory(db, test_nation.id, "up_1_0")
        _make_infrastructure(db, territory.id, "mine")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 30 - TERRITORY_UPKEEP_K * 1**2  # 20
            assert float(nation.currency) == float(expected), (
                f"1 mine (30) minus territory upkeep (10) = {expected}; got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_shipyard_does_not_reduce_currency(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """mine+shipyard, n=1: income=30 (mine only), territory_upkeep=10, net=20."""
        territory = _make_colonized_territory(db, test_nation.id, "up_2_0")
        _make_infrastructure(db, territory.id, "mine")
        _make_infrastructure(db, territory.id, "shipyard")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 30 - TERRITORY_UPKEEP_K * 1**2  # 20
            assert float(nation.currency) == float(expected), (
                f"mine (30) − territory_upkeep (10) = {expected}; shipyard costs nothing; "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_mixed_facilities_no_currency_deduction(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """mine+refinery+shipyard, n=1: income=60 (2×30), territory_upkeep=10, net=50."""
        territory = _make_colonized_territory(db, test_nation.id, "up_3_0")
        _make_infrastructure(db, territory.id, "mine")
        _make_infrastructure(db, territory.id, "refinery")
        _make_infrastructure(db, territory.id, "shipyard")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 60 - TERRITORY_UPKEEP_K * 1**2  # 50
            assert float(nation.currency) == float(expected), (
                f"mine+refinery (60) minus territory_upkeep (10) = {expected}; "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_no_facilities_territory_generates_no_income(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """n=1, no mine/refinery: income=0, territory_upkeep=10×1²=10, net=-10."""
        _make_colonized_territory(db, test_nation.id, "up_4_0")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = -TERRITORY_UPKEEP_K * 1**2  # 0 income − 10 upkeep = -10
            assert float(nation.currency) == float(expected), (
                f"No-mine territory earns 0 but pays territory upkeep; expected {expected}, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_three_mines_no_currency_upkeep(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """3 mines, n=1: income=90 (3×30), territory_upkeep=10×1²=10, net=80."""
        territory = _make_colonized_territory(db, test_nation.id, "up_5_0")
        _make_infrastructure(db, territory.id, "mine")
        _make_infrastructure(db, territory.id, "mine")
        _make_infrastructure(db, territory.id, "mine")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 90 - TERRITORY_UPKEEP_K * 1**2  # 80
            assert float(nation.currency) == float(expected), (
                f"3 mines (90) minus territory_upkeep (10) = {expected}; got {nation.currency!r}"
            )
        finally:
            fresh.close()


    def test_facilities_across_multiple_territories_no_currency_drain(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """n=2: mine on A (income=30), shipyard on B (income=0); territory_upkeep=10×4=40, net=-10."""
        t_a = _make_colonized_territory(db, test_nation.id, "up_7_0", distance_from_center=1)
        t_b = _make_colonized_territory(db, test_nation.id, "up_7_1", distance_from_center=2)
        _make_infrastructure(db, t_a.id, "mine")
        _make_infrastructure(db, t_b.id, "shipyard")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 30 - TERRITORY_UPKEEP_K * 2**2  # 30 - 40 = -10
            assert float(nation.currency) == float(expected), (
                f"mine (30) minus territory_upkeep for n=2 (40) = {expected}; "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()


# ===========================================================================
# 2. FIGHTER UPKEEP
# ===========================================================================


class TestFighterUpkeep:
    """Upkeep = 2 × total unit_count across all fleets for the nation, regardless of status."""

    def test_5_stationed_fighters_upkeep_10(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """n=1, mine + 5 fighters: income=30, fighter_upkeep=10, territory_upkeep=10, net=10."""
        territory = _make_colonized_territory(db, test_nation.id, "up_f1_0")
        _make_infrastructure(db, territory.id, "mine")
        _make_fleet(db, test_nation.id, territory.id, unit_count=5, status="stationed")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 30 - 5*2 - TERRITORY_UPKEEP_K * 1**2  # 30 - 10 - 10 = 10
            assert float(nation.currency) == float(expected), (
                f"5 fighters upkeep=10, income=30, territory_upkeep=10: expected {expected}, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_20_fighters_split_across_two_fleets_upkeep_40(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """n=1, mine + 20 fighters (40 upkeep), territory_upkeep=10: income=30, net=-20."""
        t_origin = _make_colonized_territory(db, test_nation.id, "up_f2_0")
        _make_infrastructure(db, t_origin.id, "mine")
        t_dest = Territory(
            node_key="up_f2_1", territory_type="normal", nation_id=None,
            mineral_richness=1.0, fuel_richness=1.0, distance_from_center=2, is_colonized=False,
        )
        db.add(t_dest)
        db.flush()

        _make_fleet(db, test_nation.id, t_origin.id, unit_count=12, status="stationed")
        fleet_transit = Fleet(
            nation_id=test_nation.id,
            name="Transit Fleet",
            origin_territory=t_origin.id,
            destination_territory=t_dest.id,
            unit_count=8,
            status="in_transit",
            standing_order="hold",
            arrives_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            departs_at=datetime.now(timezone.utc),
        )
        db.add(fleet_transit)
        db.flush()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 30 - 20*2 - TERRITORY_UPKEEP_K * 1**2  # 30 - 40 - 10 = -20
            assert float(nation.currency) == float(expected), (
                f"20 fighters (40) + territory_upkeep (10), income=30: expected {expected}, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_zero_fighters_no_fighter_upkeep(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """n=1, 1 mine, no fleets: income=30, territory_upkeep=10, net=20."""
        t = _make_colonized_territory(db, test_nation.id, "up_f3_0")
        _make_infrastructure(db, t.id, "mine")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 30 - TERRITORY_UPKEEP_K * 1**2  # 20
            assert float(nation.currency) == float(expected), (
                f"mine (30) minus territory_upkeep (10) = {expected}; got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_fighters_in_pending_confirmation_still_cost_upkeep(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """n=1, mine + 10 fighters (20 upkeep) + territory_upkeep=10: income=30, net=0."""
        territory = _make_colonized_territory(db, test_nation.id, "up_f4_0")
        _make_infrastructure(db, territory.id, "mine")
        fleet = Fleet(
            nation_id=test_nation.id,
            name="Pending Fleet",
            origin_territory=territory.id,
            destination_territory=territory.id,
            unit_count=10,
            status="pending_confirmation",
            standing_order="hold",
            confirmation_expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        db.add(fleet)
        db.flush()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 30 - 10*2 - TERRITORY_UPKEEP_K * 1**2  # 30 - 20 - 10 = 0
            assert float(nation.currency) == float(expected), (
                f"10 fighters (20) + territory_upkeep (10), income=30: expected {expected}, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_fighters_in_holding_still_cost_upkeep(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """n=1, mine + 15 fighters (30 upkeep) + territory_upkeep=10: income=30, net=-10."""
        territory = _make_colonized_territory(db, test_nation.id, "up_f5_0")
        _make_infrastructure(db, territory.id, "mine")
        _make_fleet(db, test_nation.id, territory.id, unit_count=15, status="holding")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 30 - 15*2 - TERRITORY_UPKEEP_K * 1**2  # 30 - 30 - 10 = -10
            assert float(nation.currency) == float(expected), (
                f"15 fighters (30) + territory_upkeep (10), income=30: expected {expected}, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_fighters_in_engaged_still_cost_upkeep(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """n=1, mine + 25 fighters (50 upkeep) + territory_upkeep=10: income=30, net=-30."""
        territory = _make_colonized_territory(db, test_nation.id, "up_f6_0")
        _make_infrastructure(db, territory.id, "mine")
        _make_fleet(db, test_nation.id, territory.id, unit_count=25, status="engaged")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 30 - 25*2 - TERRITORY_UPKEEP_K * 1**2  # 30 - 50 - 10 = -30
            assert float(nation.currency) == float(expected), (
                f"25 fighters (50) + territory_upkeep (10), income=30: expected {expected}, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_fighter_upkeep_sums_all_fleets_for_nation(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """n=1, mine + 10 fighters (20 upkeep) + territory_upkeep=10: income=30, net=0."""
        territory = _make_colonized_territory(db, test_nation.id, "up_f7_0")
        _make_infrastructure(db, territory.id, "mine")
        t_dest = Territory(
            node_key="up_f7_1", territory_type="normal", nation_id=None,
            mineral_richness=1.0, fuel_richness=1.0, distance_from_center=2, is_colonized=False,
        )
        db.add(t_dest)
        db.flush()

        _make_fleet(db, test_nation.id, territory.id, unit_count=3, status="stationed")
        _make_fleet(db, test_nation.id, territory.id, unit_count=4, status="holding")
        fleet_transit = Fleet(
            nation_id=test_nation.id,
            name="Transit Mini",
            origin_territory=territory.id,
            destination_territory=t_dest.id,
            unit_count=3,
            status="in_transit",
            standing_order="hold",
            arrives_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            departs_at=datetime.now(timezone.utc),
        )
        db.add(fleet_transit)
        db.flush()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 30 - 10*2 - TERRITORY_UPKEEP_K * 1**2  # 30 - 20 - 10 = 0
            assert float(nation.currency) == float(expected), (
                f"10 fighters (20) + territory_upkeep (10), income=30: expected {expected}, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()


# ===========================================================================
# 3. FIGHTER-ONLY UPKEEP (facilities are free)
# ===========================================================================


class TestCombinedUpkeep:
    """Fighter upkeep is the only per-tick currency drain. Facilities are free."""

    def test_fighter_upkeep_deducted_from_territory_income(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """n=1, mine + 5 fighters: income=30, fighter_upkeep=10, territory_upkeep=10, net=10."""
        territory = _make_colonized_territory(db, test_nation.id, "up_c1_0")
        _make_infrastructure(db, territory.id, "mine")
        _make_fleet(db, test_nation.id, territory.id, unit_count=5, status="stationed")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 30 - 5*2 - TERRITORY_UPKEEP_K * 1**2  # 30 - 10 - 10 = 10
            assert float(nation.currency) == float(expected), (
                f"mine (30) - fighters (10) - territory_upkeep (10) = {expected}; "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_fighter_upkeep_can_push_currency_negative(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """n=1 (anchor owned, no facilities) + 10 fighters: income=0, fighter_upkeep=20,
        territory_upkeep=10, net=-30. Currency must go negative — no floor."""
        anchor = Territory(
            node_key="up_c2_anchor",
            name="Anchor",
            territory_type="normal",
            nation_id=test_nation.id,
            mineral_richness=1.00,
            fuel_richness=1.00,
            distance_from_center=1,
            is_colonized=False,
        )
        db.add(anchor)
        db.flush()

        _make_fleet(db, test_nation.id, anchor.id, unit_count=10, status="stationed")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 0 - 10*2 - TERRITORY_UPKEEP_K * 1**2  # 0 - 20 - 10 = -30
            assert float(nation.currency) == float(expected), (
                f"10 fighters (20) + territory_upkeep (10), no income: "
                f"expected {expected}, got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_large_scenario_only_fighters_cost_currency(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """n=2, 2 mines + shipyard + 15 fighters: income=60, fighter_upkeep=30,
        territory_upkeep=10×4=40, net=-10."""
        t1 = _make_colonized_territory(db, test_nation.id, "up_c3_0", distance_from_center=1)
        t2 = _make_colonized_territory(db, test_nation.id, "up_c3_1", distance_from_center=2)
        _make_infrastructure(db, t1.id, "mine")
        _make_infrastructure(db, t2.id, "mine")
        _make_infrastructure(db, t1.id, "shipyard")
        _make_fleet(db, test_nation.id, t1.id, unit_count=15, status="stationed")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 60 - 15*2 - TERRITORY_UPKEEP_K * 2**2  # 60 - 30 - 40 = -10
            assert float(nation.currency) == float(expected), (
                f"2 mines (60) - fighters (30) - territory_upkeep (40) = {expected}; "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_upkeep_applies_to_existing_balance_not_just_new_income(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Pre-balance=1000; n=1, mine (+30), 3 fighters (-6), territory_upkeep (-10): net=14, final=1014."""
        test_nation.currency = 1000
        territory = _make_colonized_territory(db, test_nation.id, "up_c4_0")
        _make_infrastructure(db, territory.id, "mine")
        _make_fleet(db, test_nation.id, territory.id, unit_count=3, status="stationed")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            expected = 1000 + 30 - 3*2 - TERRITORY_UPKEEP_K * 1**2  # 1000 + 30 - 6 - 10 = 1014
            assert float(nation.currency) == float(expected), (
                f"Pre-balance 1000 + net 14 (30-6-10) = {expected}; got {nation.currency!r}"
            )
        finally:
            fresh.close()


# ===========================================================================
# 4. RESOURCELOG ACCURACY
# ===========================================================================


class TestResourceLogUpkeepAccuracy:
    """currency_delta written to ResourceLog must equal the NET delta (income minus fighter_upkeep)."""

    def test_resource_log_currency_delta_is_full_income_when_no_fighters(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """n=1, 1 mine, no fighters: income=30, territory_upkeep=10, delta=20."""
        territory = _make_colonized_territory(db, test_nation.id, "up_l1_0")
        _make_infrastructure(db, territory.id, "mine")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            log = fresh.query(ResourceLog).filter(
                ResourceLog.nation_id == test_nation.id,
            ).order_by(ResourceLog.id.desc()).first()
            assert log is not None, "ResourceLog row must exist after tick"
            expected = 30 - TERRITORY_UPKEEP_K * 1**2  # 20
            assert float(log.currency_delta) == float(expected), (
                f"currency_delta must be {expected} (30 income - 10 territory_upkeep), "
                f"got {log.currency_delta!r}"
            )
        finally:
            fresh.close()

    def test_resource_log_currency_delta_negative_when_upkeep_exceeds_income(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """n=1 (anchor owned, no facilities) + 10 fighters: income=0, fighter_upkeep=20,
        territory_upkeep=10, currency_delta = -30."""
        anchor = Territory(
            node_key="up_l2_anchor",
            name="Anchor L2",
            territory_type="normal",
            nation_id=test_nation.id,
            mineral_richness=1.00,
            fuel_richness=1.00,
            distance_from_center=1,
            is_colonized=False,
        )
        db.add(anchor)
        db.flush()
        _make_fleet(db, test_nation.id, anchor.id, unit_count=10, status="stationed")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            log = fresh.query(ResourceLog).filter(
                ResourceLog.nation_id == test_nation.id,
            ).order_by(ResourceLog.id.desc()).first()
            assert log is not None, "ResourceLog row must exist when upkeep creates a net change"
            expected = 0 - 10*2 - TERRITORY_UPKEEP_K * 1**2  # -30
            assert float(log.currency_delta) == float(expected), (
                f"10 fighters (20) + territory_upkeep (10), no income: delta must be {expected}, "
                f"got {log.currency_delta!r}"
            )
        finally:
            fresh.close()

    def test_resource_log_currency_delta_negative_nation_currency_decreases(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """n=1, pre=100, 10 fighters + territory_upkeep=10: total upkeep=30, final=70."""
        test_nation.currency = 100
        anchor = Territory(
            node_key="up_l3_anchor",
            name="Anchor L3",
            territory_type="normal",
            nation_id=test_nation.id,
            mineral_richness=1.00,
            fuel_richness=1.00,
            distance_from_center=1,
            is_colonized=False,
        )
        db.add(anchor)
        db.flush()
        _make_fleet(db, test_nation.id, anchor.id, unit_count=10, status="stationed")

        _commit_and_run_tick(db)

        expected_delta = 0 - 10*2 - TERRITORY_UPKEEP_K * 1**2  # -30
        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == 100.0 + expected_delta, (
                f"Starting at 100, delta={expected_delta}: expected {100+expected_delta}, "
                f"got {nation.currency!r}"
            )
            log = fresh.query(ResourceLog).filter(
                ResourceLog.nation_id == test_nation.id,
            ).order_by(ResourceLog.id.desc()).first()
            assert log is not None
            assert float(log.currency_delta) == float(expected_delta), (
                f"currency_delta must equal {expected_delta}, got {log.currency_delta!r}"
            )
        finally:
            fresh.close()

    def test_resource_log_written_when_only_upkeep_no_income(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """A ResourceLog row must be written even when income is zero but fighter upkeep is non-zero."""
        anchor = Territory(
            node_key="up_l4_anchor",
            name="Anchor L4",
            territory_type="normal",
            nation_id=test_nation.id,
            mineral_richness=1.00,
            fuel_richness=1.00,
            distance_from_center=1,
            is_colonized=False,
        )
        db.add(anchor)
        db.flush()
        _make_fleet(db, test_nation.id, anchor.id, unit_count=5, status="stationed")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            log = fresh.query(ResourceLog).filter(
                ResourceLog.nation_id == test_nation.id,
            ).first()
            assert log is not None, (
                "ResourceLog must be written when upkeep causes a net currency change, "
                "even with no territory income"
            )
        finally:
            fresh.close()

    def test_resource_log_sum_matches_nation_currency_with_upkeep(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """After 2 ticks the sum of all ResourceLog.currency_delta rows must equal nation.currency.
        n=1, 1 mine (30), 5 fighters (-10), territory_upkeep (-10) → net 10/tick."""
        territory = _make_colonized_territory(db, test_nation.id, "up_l5_0")
        _make_infrastructure(db, territory.id, "mine")
        _make_fleet(db, test_nation.id, territory.id, unit_count=5, status="stationed")

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
            assert float(nation.currency) == log_sum, (
                f"Sum of currency_delta ({log_sum}) must equal nation.currency "
                f"({nation.currency!r}) when starting from 0"
            )
        finally:
            fresh.close()


# ===========================================================================
# 5. NATION ISOLATION
# ===========================================================================


class TestUpkeepIsolation:
    """Upkeep costs from Nation A's fleets must NOT affect Nation B."""

    def test_nation_a_fighters_do_not_affect_nation_b_upkeep(
        self,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """Nation A's fighters do not increase Nation B's upkeep.
        A: n=1, mine (30) − 50 fighters (100) − territory_upkeep (10) = -80.
        B: n=1, mine (30) − territory_upkeep (10) = 20."""
        t_a = _make_colonized_territory(db, test_nation.id, "up_iso1_a", distance_from_center=1)
        t_b = _make_colonized_territory(db, other_nation.id, "up_iso1_b", distance_from_center=2)
        _make_infrastructure(db, t_a.id, "mine")
        _make_infrastructure(db, t_b.id, "mine")

        _make_fleet(db, test_nation.id, t_a.id, unit_count=50, status="stationed")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation_a = fresh.get(Nation, test_nation.id)
            nation_b = fresh.get(Nation, other_nation.id)

            exp_a = 30 - 50*2 - TERRITORY_UPKEEP_K * 1**2  # 30 - 100 - 10 = -80
            exp_b = 30 - TERRITORY_UPKEEP_K * 1**2          # 30 - 10 = 20
            assert float(nation_a.currency) == float(exp_a), (
                f"Nation A: mine (30) - fighters (100) - territory_upkeep (10) = {exp_a}; "
                f"got {nation_a.currency!r}"
            )
            assert float(nation_b.currency) == float(exp_b), (
                f"Nation B (unaffected by A): mine (30) - territory_upkeep (10) = {exp_b}; "
                f"got {nation_b.currency!r}"
            )
        finally:
            fresh.close()

    def test_nation_a_facilities_do_not_affect_nation_b_upkeep(
        self,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """Nation A's facilities do not affect Nation B's currency.
        A: n=1, mine (30) − territory_upkeep (10) = 20.
        B: n=1, mine (30) − territory_upkeep (10) = 20."""
        t_a = _make_colonized_territory(db, test_nation.id, "up_iso2_a", distance_from_center=1)
        t_b = _make_colonized_territory(db, other_nation.id, "up_iso2_b", distance_from_center=2)
        _make_infrastructure(db, t_a.id, "mine")
        _make_infrastructure(db, t_b.id, "mine")

        _make_infrastructure(db, t_a.id, "shipyard")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation_a = fresh.get(Nation, test_nation.id)
            nation_b = fresh.get(Nation, other_nation.id)

            exp = 30 - TERRITORY_UPKEEP_K * 1**2  # 20
            assert float(nation_a.currency) == float(exp), (
                f"Nation A mine+shipyard: mine (30) - territory_upkeep (10) = {exp}; "
                f"got {nation_a.currency!r}"
            )
            assert float(nation_b.currency) == float(exp), (
                f"Nation B (unaffected): mine (30) - territory_upkeep (10) = {exp}; "
                f"got {nation_b.currency!r}"
            )
        finally:
            fresh.close()

    def test_upkeep_calculations_are_per_nation_not_global(
        self,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """Each nation's upkeep is calculated independently.
        A: n=1, mine (30) - 5 fighters (10) - territory_upkeep (10) = 10.
        B: n=2, 2 mines (60) - 20 fighters (40) - territory_upkeep (40) = -20."""
        t_a = _make_colonized_territory(db, test_nation.id, "up_iso3_a", distance_from_center=1)
        t_b1 = _make_colonized_territory(db, other_nation.id, "up_iso3_b1", distance_from_center=2)
        t_b2 = _make_colonized_territory(db, other_nation.id, "up_iso3_b2", distance_from_center=3)

        _make_infrastructure(db, t_a.id, "mine")
        _make_fleet(db, test_nation.id, t_a.id, unit_count=5, status="stationed")

        _make_infrastructure(db, t_b1.id, "mine")
        _make_infrastructure(db, t_b2.id, "mine")
        _make_infrastructure(db, t_b1.id, "shipyard")
        _make_fleet(db, other_nation.id, t_b1.id, unit_count=20, status="stationed")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation_a = fresh.get(Nation, test_nation.id)
            nation_b = fresh.get(Nation, other_nation.id)

            exp_a = 30 - 5*2 - TERRITORY_UPKEEP_K * 1**2   # 30 - 10 - 10 = 10
            exp_b = 60 - 20*2 - TERRITORY_UPKEEP_K * 2**2  # 60 - 40 - 40 = -20
            assert float(nation_a.currency) == float(exp_a), (
                f"Nation A: mine (30) - fighters (10) - territory_upkeep (10) = {exp_a}; "
                f"got {nation_a.currency!r}"
            )
            assert float(nation_b.currency) == float(exp_b), (
                f"Nation B: 2 mines (60) - fighters (40) - territory_upkeep (40) = {exp_b}; "
                f"got {nation_b.currency!r}"
            )
        finally:
            fresh.close()

    def test_resource_log_for_each_nation_reflects_own_upkeep(
        self,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """ResourceLog.currency_delta independently reflects each nation's net delta.
        A: n=1, mine (30) − territory_upkeep (10) = delta 20.
        B: n=1, mine (30) − territory_upkeep (10) = delta 20."""
        t_a = _make_colonized_territory(db, test_nation.id, "up_iso4_a", distance_from_center=1)
        t_b = _make_colonized_territory(db, other_nation.id, "up_iso4_b", distance_from_center=2)

        _make_infrastructure(db, t_a.id, "mine")
        _make_infrastructure(db, t_b.id, "mine")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            log_a = fresh.query(ResourceLog).filter(
                ResourceLog.nation_id == test_nation.id,
            ).order_by(ResourceLog.id.desc()).first()
            log_b = fresh.query(ResourceLog).filter(
                ResourceLog.nation_id == other_nation.id,
            ).order_by(ResourceLog.id.desc()).first()

            assert log_a is not None, "ResourceLog must exist for Nation A"
            exp = 30 - TERRITORY_UPKEEP_K * 1**2  # 20
            assert float(log_a.currency_delta) == float(exp), (
                f"Nation A delta must be {exp} (30 income - 10 territory_upkeep), "
                f"got {log_a.currency_delta!r}"
            )
            assert log_b is not None, "ResourceLog must exist for Nation B"
            assert float(log_b.currency_delta) == float(exp), (
                f"Nation B delta must be {exp} (30 income - 10 territory_upkeep), "
                f"got {log_b.currency_delta!r}"
            )
        finally:
            fresh.close()
