"""
Test suite for currency upkeep costs in the tick system.

Covers:
  1. Assigned-population upkeep — 1 currency per assigned population unit per tick,
     where "assigned population" is derived from FACILITY_POPULATION_COST[facility.type]
     for every Infrastructure row owned by the nation (Mine=10, Refinery=10,
     Probe Factory=20, Shipyard=40).
  2. Fighter upkeep — 2 currency per starfighter (unit_count) per tick across all Fleet
     rows owned by the nation, regardless of fleet status.
  3. Combined upkeep — both costs deducted together in a single tick pass.
  4. ResourceLog accuracy — currency_delta written to the log equals net (income − upkeep),
     which can be negative.
  5. Nation isolation — Nation A's units/facilities never affect Nation B's upkeep.

These tests are written BEFORE the implementation.  They will fail until the feature
is wired into backend/app/tasks/tick.py.

Pattern: follow test_currency.py exactly — use _commit_and_run_tick / SessionLocal().
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
# Constants (mirrors what the implementation must use)
# ---------------------------------------------------------------------------

CURRENCY_PER_TERRITORY = 500
FIGHTER_UPKEEP_PER_UNIT = 2

# From backend/app/constants.py
FACILITY_POPULATION_COST = {
    "mine":          10,
    "refinery":      10,
    "probe_factory": 20,
    "shipyard":      40,
}


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
# 1. ASSIGNED-POPULATION UPKEEP
# ===========================================================================


class TestAssignedPopulationUpkeep:
    """Upkeep = sum(FACILITY_POPULATION_COST[f.type]) for all infra owned by nation."""

    def test_mine_upkeep_10_with_1_territory_net_490(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """1 mine (10 assigned pop) + 1 colonized territory: net = 500 - 10 = 490."""
        territory = _make_colonized_territory(db, test_nation.id, "up_1_0")
        _make_infrastructure(db, territory.id, "mine")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == 490.0, (
                f"1 mine upkeep=10, 1 territory income=500: expected net 490, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_shipyard_upkeep_40_with_1_territory_net_450(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """mine(10)+shipyard(40) on 1 territory: income=500, upkeep=50, net=450."""
        territory = _make_colonized_territory(db, test_nation.id, "up_2_0")
        _make_infrastructure(db, territory.id, "mine")     # makes territory income-generating
        _make_infrastructure(db, territory.id, "shipyard")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == 450.0, (
                f"mine(10)+shipyard(40) upkeep=50, income=500: expected net 450, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_mixed_facilities_upkeep_60_with_1_territory_net_440(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """mine(10) + refinery(10) + shipyard(40) = 60 assigned pop; 1 territory: net = 500 - 60 = 440."""
        territory = _make_colonized_territory(db, test_nation.id, "up_3_0")
        _make_infrastructure(db, territory.id, "mine")
        _make_infrastructure(db, territory.id, "refinery")
        _make_infrastructure(db, territory.id, "shipyard")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == 440.0, (
                f"mine+refinery+shipyard upkeep=60, 1 territory income=500: "
                f"expected net 440, got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_no_facilities_territory_generates_no_income(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Nation with 1 colonized territory and no mine/refinery: 0 currency income, 0 upkeep."""
        _make_colonized_territory(db, test_nation.id, "up_4_0")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == 0.0, (
                f"Territory without mine/refinery generates no income; expected 0, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_three_mines_upkeep_30_with_1_territory_net_470(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """3 mines (3×10=30 assigned pop) + 1 territory: net = 500 - 30 = 470.
        Verifies upkeep scales linearly with facility count."""
        territory = _make_colonized_territory(db, test_nation.id, "up_5_0")
        _make_infrastructure(db, territory.id, "mine")
        _make_infrastructure(db, territory.id, "mine")
        _make_infrastructure(db, territory.id, "mine")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == 470.0, (
                f"3 mines upkeep=30, 1 territory income=500: expected net 470, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_probe_factory_upkeep_20_with_1_territory_net_470(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """mine(10)+probe_factory(20) on 1 territory: income=500, upkeep=30, net=470."""
        territory = _make_colonized_territory(db, test_nation.id, "up_6_0")
        _make_infrastructure(db, territory.id, "mine")          # income-generating
        _make_infrastructure(db, territory.id, "probe_factory")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == 470.0, (
                f"mine(10)+probe_factory(20) upkeep=30, income=500: expected net 470, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_facilities_on_multiple_territories_upkeep_sums_correctly(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """territory A has mine (income+upkeep); territory B has shipyard only (no income, upkeep).
        income=500 (t_a only), upkeep=10(mine)+40(shipyard)=50, net=450."""
        t_a = _make_colonized_territory(db, test_nation.id, "up_7_0", distance_from_center=1)
        t_b = _make_colonized_territory(db, test_nation.id, "up_7_1", distance_from_center=2)
        _make_infrastructure(db, t_a.id, "mine")       # income-generating; upkeep=10
        _make_infrastructure(db, t_b.id, "shipyard")   # NOT income-generating; upkeep=40

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            # income: 500 (t_a has mine); upkeep: 10 + 40 = 50; net = 450
            assert float(nation.currency) == 450.0, (
                f"mine on t_a (income=500) + shipyard on t_b (no income), upkeep=50: "
                f"expected net 450, got {nation.currency!r}"
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
        """mine(10) + 5 fighters(10 upkeep) on 1 territory: income=500, upkeep=20, net=480."""
        territory = _make_colonized_territory(db, test_nation.id, "up_f1_0")
        _make_infrastructure(db, territory.id, "mine")
        _make_fleet(db, test_nation.id, territory.id, unit_count=5, status="stationed")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == 480.0, (
                f"mine(10)+5 fighters(10), income=500: expected net 480, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_20_fighters_split_across_two_fleets_upkeep_40(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Fleet A (stationed, 12 fighters) + Fleet B (in_transit, 8 fighters) = 20 total.
        mine(10) + 20 fighters(40 upkeep); income=500; net=450."""
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
            assert float(nation.currency) == 450.0, (
                f"mine(10)+12 stationed+8 in_transit (20 fighters, upkeep=40), "
                f"income=500: expected net 450, got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_zero_fighters_no_fighter_upkeep(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Nation with 1 mine territory and no fleets: income=500, mine_upkeep=10, net=490."""
        t = _make_colonized_territory(db, test_nation.id, "up_f3_0")
        _make_infrastructure(db, t.id, "mine")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == 490.0, (
                f"No fighters means no fighter upkeep; mine territory nets 490; "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_fighters_in_pending_confirmation_still_cost_upkeep(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Fighters in pending_confirmation cost upkeep regardless of status.
        mine(10) + 10 fighters(20 upkeep); income=500; net=470."""
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
            assert float(nation.currency) == 470.0, (
                f"mine(10)+10 fighters in pending_confirmation (upkeep=20), income=500: "
                f"expected net 470, got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_fighters_in_holding_still_cost_upkeep(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Fighters with status=holding cost upkeep.
        mine(10) + 15 fighters(30 upkeep); income=500; net=460."""
        territory = _make_colonized_territory(db, test_nation.id, "up_f5_0")
        _make_infrastructure(db, territory.id, "mine")
        _make_fleet(db, test_nation.id, territory.id, unit_count=15, status="holding")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == 460.0, (
                f"mine(10)+15 fighters in holding (upkeep=30), income=500: "
                f"expected net 460, got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_fighters_in_engaged_still_cost_upkeep(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Fighters with status=engaged cost upkeep.
        mine(10) + 25 fighters(50 upkeep); income=500; net=440."""
        territory = _make_colonized_territory(db, test_nation.id, "up_f6_0")
        _make_infrastructure(db, territory.id, "mine")
        _make_fleet(db, test_nation.id, territory.id, unit_count=25, status="engaged")

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == 440.0, (
                f"mine(10)+25 fighters in engaged (upkeep=50), income=500: "
                f"expected net 440, got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_fighter_upkeep_sums_all_fleets_for_nation(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Multiple fleets with different statuses: total upkeep = 2 × sum of all unit_counts.
        mine(10) + Fleet1 stationed=3, Fleet2 holding=4, Fleet3 in_transit=3 → 10 fighters(20).
        income=500; total upkeep=30; net=470."""
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
            assert float(nation.currency) == 470.0, (
                f"mine(10)+3+4+3=10 fighters (upkeep=20), income=500: "
                f"expected net 470, got {nation.currency!r}"
            )
        finally:
            fresh.close()


# ===========================================================================
# 3. COMBINED UPKEEP
# ===========================================================================


class TestCombinedUpkeep:
    """Both population and fighter upkeep are subtracted in the same tick pass."""

    def test_pop_upkeep_plus_fighter_upkeep_deducted_together(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """1 mine (pop upkeep=10) + 5 fighters (fighter upkeep=10) + 1 territory (income=500):
        net = 500 - 10 - 10 = 480."""
        territory = _make_colonized_territory(db, test_nation.id, "up_c1_0")
        _make_infrastructure(db, territory.id, "mine")           # pop upkeep = 10
        _make_fleet(db, test_nation.id, territory.id, unit_count=5, status="stationed")  # fighter upkeep = 10

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == 480.0, (
                f"mine(10 pop) + 5 fighters(10 upkeep), income=500: "
                f"expected net 480, got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_combined_upkeep_can_push_currency_negative(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """No territories (income=0) + 1 mine (pop upkeep=10) + 10 fighters (fighter upkeep=20):
        net = 0 - 10 - 20 = -30.  Currency must go negative — no floor."""
        # Provide an uncolonized territory as a home base for the fleet anchor
        # (origin_territory must exist; territory need not be colonized for upkeep)
        uncolonized = Territory(
            node_key="up_c2_anchor",
            name="Anchor",
            territory_type="normal",
            nation_id=test_nation.id,
            mineral_richness=1.00,
            fuel_richness=1.00,
            distance_from_center=1,
            is_colonized=False,
        )
        db.add(uncolonized)
        db.flush()

        _make_infrastructure(db, uncolonized.id, "mine")           # pop upkeep = 10
        _make_fleet(db, test_nation.id, uncolonized.id, unit_count=10, status="stationed")  # fighter upkeep = 20

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            # income = 0 (no colonized territories); upkeep = 10 + 20 = 30
            assert float(nation.currency) == -30.0, (
                f"No colonized territories, mine(10)+10 fighters(20) upkeep: "
                f"expected -30 (currency can go negative), got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_combined_upkeep_large_scenario(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """2 income territories + shipyard + probe_factory + 15 fighters.
        mine on each territory (2×10=20 upkeep); 2×500=1000 income;
        shipyard(40)+probe_factory(20)+15 fighters(30)=90; total upkeep=110; net=890."""
        t1 = _make_colonized_territory(db, test_nation.id, "up_c3_0", distance_from_center=1)
        t2 = _make_colonized_territory(db, test_nation.id, "up_c3_1", distance_from_center=2)
        _make_infrastructure(db, t1.id, "mine")            # makes t1 income-generating; upkeep=10
        _make_infrastructure(db, t2.id, "mine")            # makes t2 income-generating; upkeep=10
        _make_infrastructure(db, t1.id, "shipyard")        # pop upkeep = 40
        _make_infrastructure(db, t2.id, "probe_factory")   # pop upkeep = 20
        _make_fleet(db, test_nation.id, t1.id, unit_count=15, status="stationed")  # fighter upkeep = 30

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            # income=1000; upkeep=10+10+40+20+30=110; net=890
            assert float(nation.currency) == 890.0, (
                f"2 mine territories(1000) - mines(20) - shipyard(40) - probe_factory(20) "
                f"- 15 fighters(30): expected net 890, got {nation.currency!r}"
            )
        finally:
            fresh.close()

    def test_upkeep_applies_to_existing_balance_not_just_new_income(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Starting with a pre-existing currency balance: tick must add net delta on top.
        Pre-balance=1000; 1 territory(+500); 1 mine(-10); 3 fighters(-6): net delta=484; final=1484."""
        test_nation.currency = 1000
        territory = _make_colonized_territory(db, test_nation.id, "up_c4_0")
        _make_infrastructure(db, territory.id, "mine")        # pop upkeep = 10
        _make_fleet(db, test_nation.id, territory.id, unit_count=3, status="stationed")  # fighter upkeep = 6

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            # 1000 + (500 - 10 - 6) = 1000 + 484 = 1484
            assert float(nation.currency) == 1484.0, (
                f"Pre-balance 1000 + net delta 484 (500-10-6): expected 1484, "
                f"got {nation.currency!r}"
            )
        finally:
            fresh.close()


# ===========================================================================
# 4. RESOURCELOG ACCURACY
# ===========================================================================


class TestResourceLogUpkeepAccuracy:
    """currency_delta written to ResourceLog must equal the NET delta (income minus upkeep)."""

    def test_resource_log_currency_delta_is_net_not_gross_income(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """With 1 territory and 1 mine, gross income=500 but net=490.
        ResourceLog.currency_delta must be 490, not 500."""
        territory = _make_colonized_territory(db, test_nation.id, "up_l1_0")
        _make_infrastructure(db, territory.id, "mine")   # pop upkeep = 10

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            log = fresh.query(ResourceLog).filter(
                ResourceLog.nation_id == test_nation.id,
            ).order_by(ResourceLog.id.desc()).first()
            assert log is not None, "ResourceLog row must exist after tick"
            assert float(log.currency_delta) == 490.0, (
                f"currency_delta must be net 490 (500 income - 10 upkeep), "
                f"got {log.currency_delta!r}"
            )
        finally:
            fresh.close()

    def test_resource_log_currency_delta_negative_when_upkeep_exceeds_income(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """When upkeep > income the currency_delta in ResourceLog must be negative.
        0 territories (income=0) + 10 fighters (upkeep=20): currency_delta = -20."""
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
            assert float(log.currency_delta) == -20.0, (
                f"10 fighters upkeep=20 with no income: currency_delta must be -20, "
                f"got {log.currency_delta!r}"
            )
        finally:
            fresh.close()

    def test_resource_log_currency_delta_negative_nation_currency_decreases(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """Negative currency_delta must reduce nation.currency.
        Starting at 100 currency; upkeep=20 and no income → final = 80."""
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

        fresh = SessionLocal()
        try:
            nation = fresh.get(Nation, test_nation.id)
            assert float(nation.currency) == 80.0, (
                f"Starting at 100, upkeep=20 with no income: expected 80, got {nation.currency!r}"
            )
            log = fresh.query(ResourceLog).filter(
                ResourceLog.nation_id == test_nation.id,
            ).order_by(ResourceLog.id.desc()).first()
            assert log is not None
            assert float(log.currency_delta) == -20.0, (
                f"currency_delta must equal -20, got {log.currency_delta!r}"
            )
        finally:
            fresh.close()

    def test_resource_log_written_when_only_upkeep_no_income(
        self,
        db: Session,
        test_nation: Nation,
    ):
        """A ResourceLog row must be written even when income is zero but upkeep is non-zero.
        The net delta is non-zero so the log entry must be created."""
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
        """After 2 ticks the sum of all ResourceLog.currency_delta rows must equal
        nation.currency (starting from 0).
        Setup: 1 territory income=500, mine upkeep=10, 5 fighters upkeep=10 → net per tick=480."""
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
    """Upkeep costs from Nation A's fleets and facilities must NOT affect Nation B."""

    def test_nation_a_fighters_do_not_affect_nation_b_upkeep(
        self,
        db: Session,
        test_nation: Nation,
        other_nation: Nation,
    ):
        """Nation A's fighters do not increase Nation B's upkeep.
        Both have 1 mine territory. A: income=500, mine(10)+50 fighters(100)=110 upkeep, net=390.
        B: income=500, mine(10) upkeep, net=490."""
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

            # Nation A: 500 income - 10 mine - 100 fighter upkeep = 390
            assert float(nation_a.currency) == 390.0, (
                f"Nation A with mine+50 fighters: expected 390, got {nation_a.currency!r}"
            )
            # Nation B: 500 income - 10 mine upkeep = 490
            assert float(nation_b.currency) == 490.0, (
                f"Nation B with only mine: expected 490 (unaffected by A's upkeep), "
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
        """Nation A's shipyard upkeep does not bleed into Nation B.
        A: mine(10)+shipyard(40) upkeep, income=500, net=450.
        B: mine(10) upkeep, income=500, net=490."""
        t_a = _make_colonized_territory(db, test_nation.id, "up_iso2_a", distance_from_center=1)
        t_b = _make_colonized_territory(db, other_nation.id, "up_iso2_b", distance_from_center=2)
        _make_infrastructure(db, t_a.id, "mine")
        _make_infrastructure(db, t_b.id, "mine")

        _make_infrastructure(db, t_a.id, "shipyard")  # Nation A extra upkeep = 40

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation_a = fresh.get(Nation, test_nation.id)
            nation_b = fresh.get(Nation, other_nation.id)

            # Nation A: 500 income - 10 mine - 40 shipyard = 450
            assert float(nation_a.currency) == 450.0, (
                f"Nation A with mine+shipyard: expected 450, got {nation_a.currency!r}"
            )
            # Nation B: 500 income - 10 mine = 490
            assert float(nation_b.currency) == 490.0, (
                f"Nation B with only mine: expected 490 (unaffected by A's upkeep), "
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
        Nation A: mine(10)+5 fighters(10) on 1 territory → net=480.
        Nation B: mines on both territories(20)+shipyard(40)+20 fighters(40) → net=1000-100=900."""
        t_a = _make_colonized_territory(db, test_nation.id, "up_iso3_a", distance_from_center=1)
        t_b1 = _make_colonized_territory(db, other_nation.id, "up_iso3_b1", distance_from_center=2)
        t_b2 = _make_colonized_territory(db, other_nation.id, "up_iso3_b2", distance_from_center=3)

        _make_infrastructure(db, t_a.id, "mine")             # Nation A: income + upkeep=10
        _make_fleet(db, test_nation.id, t_a.id, unit_count=5, status="stationed")  # Nation A: upkeep=10

        _make_infrastructure(db, t_b1.id, "mine")            # Nation B: t_b1 income + upkeep=10
        _make_infrastructure(db, t_b2.id, "mine")            # Nation B: t_b2 income + upkeep=10
        _make_infrastructure(db, t_b1.id, "shipyard")        # Nation B: upkeep=40
        _make_fleet(db, other_nation.id, t_b1.id, unit_count=20, status="stationed")  # Nation B: upkeep=40

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            nation_a = fresh.get(Nation, test_nation.id)
            nation_b = fresh.get(Nation, other_nation.id)

            # A: 500 - 10(mine) - 10(fighters) = 480
            assert float(nation_a.currency) == 480.0, (
                f"Nation A (mine+5 fighters): expected 480, got {nation_a.currency!r}"
            )
            # B: 1000 - 10 - 10(mines) - 40(shipyard) - 40(fighters) = 900
            assert float(nation_b.currency) == 900.0, (
                f"Nation B (2 mine territories+shipyard+20 fighters): expected 900, "
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
        Nation A: mine(10 upkeep), income=500, net=490.
        Nation B: mine(10 upkeep), income=500, net=490."""
        t_a = _make_colonized_territory(db, test_nation.id, "up_iso4_a", distance_from_center=1)
        t_b = _make_colonized_territory(db, other_nation.id, "up_iso4_b", distance_from_center=2)

        _make_infrastructure(db, t_a.id, "mine")   # Nation A pop upkeep = 10
        _make_infrastructure(db, t_b.id, "mine")   # Nation B pop upkeep = 10

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
            assert float(log_a.currency_delta) == 490.0, (
                f"Nation A ResourceLog.currency_delta must be 490, got {log_a.currency_delta!r}"
            )

            assert log_b is not None, "ResourceLog must exist for Nation B"
            assert float(log_b.currency_delta) == 490.0, (
                f"Nation B ResourceLog.currency_delta must be 490 (mine upkeep deducted), "
                f"got {log_b.currency_delta!r}"
            )
        finally:
            fresh.close()
