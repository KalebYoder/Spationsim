"""
Test suite for fleet fuel upkeep.

Fighters consume 1 fuel per unit per tick when not docked on a territory
owned by their nation. "Docked" = status "stationed" on a territory
whose nation_id matches the fleet's nation. Any other status or location pays upkeep.

Covers:
  1. Stationed on own territory → no fuel cost
  2. In transit                 → 1 fuel/unit/tick
  3. pending_confirmation       → 1 fuel/unit/tick
  4. holding                    → 1 fuel/unit/tick
  5. engaged                    → 1 fuel/unit/tick
  6. Stationed on unclaimed territory → 1 fuel/unit/tick
  7. Stationed on enemy territory     → 1 fuel/unit/tick
  8. Mixed: docked + in-space → only in-space fighters cost fuel
  9. ResourceLog fuel_delta reflects upkeep
  10. Nation isolation
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
from app.models.nation import Nation
from app.models.player import Player
from app.models.resource_log import ResourceLog
from app.models.territory import Territory
from app.core.security import hash_password

FUEL_PER_UNIT = 1


def _run_tick(db: Session) -> None:
    db.commit()
    from app.tasks.tick import run_tick
    run_tick()


def _own_territory(db: Session, nation_id: int, node_key: str) -> Territory:
    t = Territory(
        node_key=node_key,
        name=f"Territory {node_key}",
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


def _unclaimed_territory(db: Session, node_key: str) -> Territory:
    t = Territory(
        node_key=node_key,
        name=f"Void {node_key}",
        territory_type="void",
        nation_id=None,
        mineral_richness=0,
        fuel_richness=0,
        distance_from_center=2,
        is_colonized=False,
    )
    db.add(t)
    db.flush()
    return t


def _fleet(db: Session, nation_id: int, origin_id: int, units: int, status: str,
           destination_id: int | None = None) -> Fleet:
    f = Fleet(
        nation_id=nation_id,
        origin_territory=origin_id,
        destination_territory=destination_id,
        unit_count=units,
        status=status,
        standing_order="hold",
        arrives_at=datetime(2099, 1, 1, tzinfo=timezone.utc) if status == "in_transit" else None,
        confirmation_expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc) if status == "pending_confirmation" else None,
    )
    db.add(f)
    db.flush()
    return f


def _fuel(db: Session, nation_id: int) -> float:
    s = SessionLocal()
    try:
        return float(s.get(Nation, nation_id).fuel)
    finally:
        s.close()


@pytest.fixture()
def other_player(db: Session) -> Player:
    p = Player(username="other_fueltest", email="otherfuel@example.com",
               password_hash=hash_password("pw"))
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def other_nation(db: Session, other_player: Player) -> Nation:
    n = Nation(player_id=other_player.id, name="Other Fuel Nation", minerals=0, fuel=1000)
    db.add(n)
    db.flush()
    return n


# ===========================================================================
# 1. Stationed on own territory — no fuel cost
# ===========================================================================


class TestDockedNoUpkeep:

    def test_stationed_on_own_territory_no_fuel_drain(self, db, test_nation):
        """Fleet stationed on a territory it owns pays no fuel upkeep."""
        start_fuel = float(test_nation.fuel)
        own = _own_territory(db, test_nation.id, "ff_dock_1")
        _fleet(db, test_nation.id, own.id, units=10, status="stationed")

        _run_tick(db)

        assert _fuel(db, test_nation.id) == start_fuel, \
            "Stationed on own territory: fuel must not change"

    def test_multiple_fleets_docked_on_own_territories_no_fuel_drain(self, db, test_nation):
        """Two fleets on two different own territories: neither costs fuel."""
        start_fuel = float(test_nation.fuel)
        t1 = _own_territory(db, test_nation.id, "ff_dock_2a")
        t2 = _own_territory(db, test_nation.id, "ff_dock_2b")
        _fleet(db, test_nation.id, t1.id, units=5, status="stationed")
        _fleet(db, test_nation.id, t2.id, units=7, status="stationed")

        _run_tick(db)

        assert _fuel(db, test_nation.id) == start_fuel


# ===========================================================================
# 2. In transit
# ===========================================================================


class TestInTransitUpkeep:

    def test_in_transit_fleet_costs_1_fuel_per_unit(self, db, test_nation):
        """10 fighters in transit → 10 fuel drain."""
        start_fuel = float(test_nation.fuel)
        home = _own_territory(db, test_nation.id, "ff_tr_1h")
        dest = _unclaimed_territory(db, "ff_tr_1d")
        _fleet(db, test_nation.id, home.id, units=10, status="in_transit", destination_id=dest.id)

        _run_tick(db)

        assert _fuel(db, test_nation.id) == start_fuel - 10


# ===========================================================================
# 3. pending_confirmation
# ===========================================================================


class TestPendingConfirmationUpkeep:

    def test_pending_confirmation_costs_fuel(self, db, test_nation):
        """8 fighters in pending_confirmation → 8 fuel drain."""
        start_fuel = float(test_nation.fuel)
        home = _own_territory(db, test_nation.id, "ff_pc_1h")
        enemy_t = _unclaimed_territory(db, "ff_pc_1e")
        _fleet(db, test_nation.id, home.id, units=8, status="pending_confirmation",
               destination_id=enemy_t.id)

        _run_tick(db)

        assert _fuel(db, test_nation.id) == start_fuel - 8


# ===========================================================================
# 4. holding
# ===========================================================================


class TestHoldingUpkeep:

    def test_holding_costs_fuel(self, db, test_nation):
        """15 fighters holding → 15 fuel drain."""
        start_fuel = float(test_nation.fuel)
        home = _own_territory(db, test_nation.id, "ff_hld_1h")
        foreign = _unclaimed_territory(db, "ff_hld_1f")
        _fleet(db, test_nation.id, foreign.id, units=15, status="holding")

        _run_tick(db)

        assert _fuel(db, test_nation.id) == start_fuel - 15


# ===========================================================================
# 5. engaged
# ===========================================================================


class TestEngagedUpkeep:

    def test_engaged_costs_fuel(self, db, test_nation):
        """20 fighters engaged → 20 fuel drain."""
        start_fuel = float(test_nation.fuel)
        home = _own_territory(db, test_nation.id, "ff_eng_1h")
        enemy_t = _unclaimed_territory(db, "ff_eng_1e")
        _fleet(db, test_nation.id, enemy_t.id, units=20, status="engaged",
               destination_id=enemy_t.id)

        _run_tick(db)

        assert _fuel(db, test_nation.id) == start_fuel - 20


# ===========================================================================
# 6. Stationed on unclaimed territory
# ===========================================================================


class TestStationedUnclaimed:

    def test_stationed_on_unclaimed_void_costs_fuel(self, db, test_nation):
        """Fleet stationed on an unclaimed void (not owner's territory) costs fuel."""
        start_fuel = float(test_nation.fuel)
        void = _unclaimed_territory(db, "ff_unc_1")
        _fleet(db, test_nation.id, void.id, units=6, status="stationed")

        _run_tick(db)

        assert _fuel(db, test_nation.id) == start_fuel - 6


# ===========================================================================
# 7. Stationed on enemy territory
# ===========================================================================


class TestStationedEnemy:

    def test_stationed_on_enemy_territory_costs_fuel(self, db, test_nation, other_nation):
        """Fleet stationed on a territory owned by another nation costs fuel."""
        start_fuel = float(test_nation.fuel)
        enemy_planet = _own_territory(db, other_nation.id, "ff_enem_1")
        _fleet(db, test_nation.id, enemy_planet.id, units=12, status="stationed")

        _run_tick(db)

        assert _fuel(db, test_nation.id) == start_fuel - 12


# ===========================================================================
# 8. Mixed: docked + in-space
# ===========================================================================


class TestMixedUpkeep:

    def test_docked_and_in_transit_only_in_transit_costs_fuel(self, db, test_nation):
        """10 docked + 5 in-transit: only the 5 in-transit fighters cost fuel."""
        start_fuel = float(test_nation.fuel)
        home = _own_territory(db, test_nation.id, "ff_mix_1h")
        dest = _unclaimed_territory(db, "ff_mix_1d")
        _fleet(db, test_nation.id, home.id, units=10, status="stationed")
        _fleet(db, test_nation.id, home.id, units=5, status="in_transit", destination_id=dest.id)

        _run_tick(db)

        assert _fuel(db, test_nation.id) == start_fuel - 5

    def test_multiple_in_space_statuses_all_cost_fuel(self, db, test_nation):
        """Docked=8, in_transit=3, holding=4, pending_confirmation=2.
        In-space total = 9. Expected fuel drain = 9."""
        start_fuel = float(test_nation.fuel)
        home = _own_territory(db, test_nation.id, "ff_mix_2h")
        void1 = _unclaimed_territory(db, "ff_mix_2v1")
        void2 = _unclaimed_territory(db, "ff_mix_2v2")

        _fleet(db, test_nation.id, home.id, units=8, status="stationed")
        _fleet(db, test_nation.id, home.id, units=3, status="in_transit", destination_id=void1.id)
        _fleet(db, test_nation.id, void1.id, units=4, status="holding")
        _fleet(db, test_nation.id, home.id, units=2, status="pending_confirmation",
               destination_id=void2.id)

        _run_tick(db)

        assert _fuel(db, test_nation.id) == start_fuel - 9


# ===========================================================================
# 9. ResourceLog fuel_delta
# ===========================================================================


class TestFuelUpkeepResourceLog:

    def test_resource_log_fuel_delta_reflects_in_space_upkeep(self, db, test_nation):
        """10 fighters in transit: ResourceLog.fuel_delta should be -10."""
        home = _own_territory(db, test_nation.id, "ff_log_1h")
        dest = _unclaimed_territory(db, "ff_log_1d")
        _fleet(db, test_nation.id, home.id, units=10, status="in_transit", destination_id=dest.id)

        _run_tick(db)

        s = SessionLocal()
        try:
            log = s.query(ResourceLog).filter(
                ResourceLog.nation_id == test_nation.id
            ).order_by(ResourceLog.id.desc()).first()
            assert log is not None
            assert float(log.fuel_delta) == -10
        finally:
            s.close()

    def test_resource_log_no_fuel_delta_when_all_docked(self, db, test_nation):
        """All fighters docked: fuel_delta in ResourceLog should be 0 (or no log if no other deltas)."""
        home = _own_territory(db, test_nation.id, "ff_log_2h")
        _fleet(db, test_nation.id, home.id, units=10, status="stationed")

        _run_tick(db)

        s = SessionLocal()
        try:
            log = s.query(ResourceLog).filter(
                ResourceLog.nation_id == test_nation.id
            ).order_by(ResourceLog.id.desc()).first()
            # If a log was written it must show 0 fuel drain; or no log at all (no deltas)
            if log is not None:
                assert float(log.fuel_delta) == 0
        finally:
            s.close()


# ===========================================================================
# 10. Nation isolation
# ===========================================================================


class TestFuelUpkeepIsolation:

    def test_nation_a_in_space_does_not_drain_nation_b_fuel(self, db, test_nation, other_nation):
        """Nation A has fighters in transit. Nation B's fuel must be unchanged."""
        start_fuel_b = float(other_nation.fuel)
        home = _own_territory(db, test_nation.id, "ff_iso_1h")
        dest = _unclaimed_territory(db, "ff_iso_1d")
        _fleet(db, test_nation.id, home.id, units=20, status="in_transit", destination_id=dest.id)

        _run_tick(db)

        assert _fuel(db, other_nation.id) == start_fuel_b

    def test_each_nation_charged_independently(self, db, test_nation, other_nation):
        """A has 10 in-transit, B has 5 in-transit. Each pays their own upkeep."""
        start_fuel_a = float(test_nation.fuel)
        start_fuel_b = float(other_nation.fuel)
        home_a = _own_territory(db, test_nation.id, "ff_iso_2ha")
        home_b = _own_territory(db, other_nation.id, "ff_iso_2hb")
        dest = _unclaimed_territory(db, "ff_iso_2d")
        _fleet(db, test_nation.id, home_a.id, units=10, status="in_transit", destination_id=dest.id)
        _fleet(db, other_nation.id, home_b.id, units=5, status="in_transit", destination_id=dest.id)

        _run_tick(db)

        assert _fuel(db, test_nation.id) == start_fuel_a - 10
        assert _fuel(db, other_nation.id) == start_fuel_b - 5
