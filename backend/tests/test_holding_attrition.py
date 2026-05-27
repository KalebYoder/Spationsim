"""
Test suite for holding-fleet attrition.

Each tick a fleet with status="holding" loses max(1, round(unit_count × 0.01)) units.
The minimum loss is always 1 — a holding fleet cannot park indefinitely.
A fleet that reaches 0 is deleted and a destroyed event is fired.
Fleets in any other status are not affected.

Attrition rate reference (losses per tick):
  1–149 units  →  1 loss/tick
  150–249      →  2 losses/tick   (round(1.5)=2 Python banker's rounding)
  250–349      →  3 losses/tick
  ...

Covers:
  1. Any holding fleet loses at least 1 unit per tick
  2. Large fleets lose proportionally more (1% rounded)
  3. Fleet reaching 0 is deleted and a "fleet_destroyed_by_attrition" event fires
  4. Attrition event logged with correct payload
  5. Non-holding fleets (stationed, in_transit, pending_confirmation) are untouched
  6. Nation isolation
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
from app.models.event import Event
from app.models.fleet import Fleet
from app.models.nation import Nation
from app.models.player import Player
from app.models.territory import Territory
from app.core.security import hash_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_tick(db: Session) -> None:
    db.commit()
    from app.tasks.tick import run_tick
    run_tick()


def _territory(db: Session, node_key: str, nation_id: int | None = None) -> Territory:
    t = Territory(
        node_key=node_key,
        name=f"T {node_key}",
        territory_type="normal",
        nation_id=nation_id,
        mineral_richness=1,
        fuel_richness=1,
        distance_from_center=1,
        is_colonized=nation_id is not None,
        colonized_at=datetime.now(timezone.utc) if nation_id else None,
    )
    db.add(t)
    db.flush()
    return t


def _holding_fleet(db, nation_id, origin_id, dest_id, units) -> Fleet:
    f = Fleet(
        nation_id=nation_id,
        origin_territory=origin_id,
        destination_territory=dest_id,
        unit_count=units,
        status="holding",
        standing_order="hold",
    )
    db.add(f)
    db.flush()
    return f


def _fleet(db, nation_id, origin_id, units, status, dest_id=None) -> Fleet:
    f = Fleet(
        nation_id=nation_id,
        origin_territory=origin_id,
        destination_territory=dest_id,
        unit_count=units,
        status=status,
        standing_order="hold",
        arrives_at=datetime(2099, 1, 1, tzinfo=timezone.utc) if status == "in_transit" else None,
        confirmation_expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc) if status == "pending_confirmation" else None,
    )
    db.add(f)
    db.flush()
    return f


@pytest.fixture()
def other_player(db):
    p = Player(username="ha_other", email="ha_other@test.com",
               password_hash=hash_password("pw"))
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def other_nation(db, other_player):
    n = Nation(player_id=other_player.id, name="Other HA Nation",
               minerals=0, fuel=1000, currency=0)
    db.add(n)
    db.flush()
    return n


# ---------------------------------------------------------------------------
# 1. Minimum 1 loss per tick for any holding fleet
# ---------------------------------------------------------------------------

class TestMinimumAttrition:

    def test_single_unit_holding_fleet_loses_1(self, db, test_nation):
        """1 unit: max(1, round(0.01)) = 1. Fleet is deleted in one tick."""
        home = _territory(db, "ha_m1_h", test_nation.id)
        dest = _territory(db, "ha_m1_d")
        fleet = _holding_fleet(db, test_nation.id, home.id, dest.id, units=1)
        fleet_id = fleet.id

        _run_tick(db)

        s = SessionLocal()
        try:
            f = s.query(Fleet).filter(Fleet.id == fleet_id).first()
            assert f is None, "1-unit holding fleet should be deleted after 1 tick"
        finally:
            s.close()

    def test_small_fleet_loses_1_per_tick(self, db, test_nation):
        """20 units: max(1, round(0.2)) = 1. Minimum kicks in."""
        home = _territory(db, "ha_m2_h", test_nation.id)
        dest = _territory(db, "ha_m2_d")
        fleet = _holding_fleet(db, test_nation.id, home.id, dest.id, units=20)

        _run_tick(db)

        s = SessionLocal()
        try:
            f = s.query(Fleet).filter(Fleet.id == fleet.id).first()
            assert f is not None
            assert f.unit_count == 19
        finally:
            s.close()

    def test_50_unit_fleet_loses_1(self, db, test_nation):
        """50 units: max(1, round(0.5)) = max(1, 0) = 1."""
        home = _territory(db, "ha_m3_h", test_nation.id)
        dest = _territory(db, "ha_m3_d")
        fleet = _holding_fleet(db, test_nation.id, home.id, dest.id, units=50)

        _run_tick(db)

        s = SessionLocal()
        try:
            f = s.query(Fleet).filter(Fleet.id == fleet.id).first()
            assert f is not None
            assert f.unit_count == 49
        finally:
            s.close()


# ---------------------------------------------------------------------------
# 2. Proportional losses for large fleets
# ---------------------------------------------------------------------------

class TestProportionalAttrition:

    def test_100_unit_fleet_loses_1(self, db, test_nation):
        """100 units: max(1, round(1.0)) = 1."""
        home = _territory(db, "ha_p1_h", test_nation.id)
        dest = _territory(db, "ha_p1_d")
        fleet = _holding_fleet(db, test_nation.id, home.id, dest.id, units=100)

        _run_tick(db)

        s = SessionLocal()
        try:
            f = s.query(Fleet).filter(Fleet.id == fleet.id).first()
            assert f.unit_count == 99
        finally:
            s.close()

    def test_200_unit_fleet_loses_2(self, db, test_nation):
        """200 units: max(1, round(2.0)) = 2."""
        home = _territory(db, "ha_p2_h", test_nation.id)
        dest = _territory(db, "ha_p2_d")
        fleet = _holding_fleet(db, test_nation.id, home.id, dest.id, units=200)

        _run_tick(db)

        s = SessionLocal()
        try:
            f = s.query(Fleet).filter(Fleet.id == fleet.id).first()
            assert f.unit_count == 198
        finally:
            s.close()

    def test_150_unit_fleet_loses_2(self, db, test_nation):
        """150 units: max(1, round(1.5)) = max(1, 2) = 2 (Python banker's rounding)."""
        home = _territory(db, "ha_p3_h", test_nation.id)
        dest = _territory(db, "ha_p3_d")
        fleet = _holding_fleet(db, test_nation.id, home.id, dest.id, units=150)

        _run_tick(db)

        s = SessionLocal()
        try:
            f = s.query(Fleet).filter(Fleet.id == fleet.id).first()
            assert f.unit_count == 148
        finally:
            s.close()


# ---------------------------------------------------------------------------
# 3. Fleet deleted when it reaches 0
# ---------------------------------------------------------------------------

class TestFleetDeletion:

    def test_1_unit_fleet_deleted_after_1_tick(self, db, test_nation):
        home = _territory(db, "ha_del_h", test_nation.id)
        dest = _territory(db, "ha_del_d")
        fleet = _holding_fleet(db, test_nation.id, home.id, dest.id, units=1)
        fleet_id = fleet.id

        _run_tick(db)

        s = SessionLocal()
        try:
            assert s.query(Fleet).filter(Fleet.id == fleet_id).first() is None
        finally:
            s.close()

    def test_destroyed_event_fired_on_deletion(self, db, test_nation):
        home = _territory(db, "ha_del2_h", test_nation.id)
        dest = _territory(db, "ha_del2_d")
        fleet = _holding_fleet(db, test_nation.id, home.id, dest.id, units=1)

        _run_tick(db)

        s = SessionLocal()
        try:
            ev = s.query(Event).filter(
                Event.type == "fleet_destroyed_by_attrition"
            ).first()
            assert ev is not None
            assert ev.payload["nation_id"] == test_nation.id
        finally:
            s.close()


# ---------------------------------------------------------------------------
# 4. Attrition event logged
# ---------------------------------------------------------------------------

class TestAttritionEvent:

    def test_attrition_event_logged_with_correct_payload(self, db, test_nation):
        home = _territory(db, "ha_ev_h", test_nation.id)
        dest = _territory(db, "ha_ev_d")
        fleet = _holding_fleet(db, test_nation.id, home.id, dest.id, units=100)

        _run_tick(db)

        s = SessionLocal()
        try:
            ev = s.query(Event).filter(
                Event.type == "holding_fleet_attrition"
            ).first()
            assert ev is not None
            assert ev.payload["fleet_id"] == fleet.id
            assert ev.payload["nation_id"] == test_nation.id
            assert ev.payload["losses"] == 1
            assert ev.payload["remaining"] == 99
        finally:
            s.close()


# ---------------------------------------------------------------------------
# 5. Non-holding fleets unaffected
# ---------------------------------------------------------------------------

class TestNonHoldingUnaffected:

    def test_stationed_fleet_not_affected(self, db, test_nation):
        home = _territory(db, "ha_nh1_h", test_nation.id)
        _fleet(db, test_nation.id, home.id, units=100, status="stationed")

        _run_tick(db)

        s = SessionLocal()
        try:
            f = s.query(Fleet).filter(Fleet.nation_id == test_nation.id,
                                      Fleet.status == "stationed").first()
            assert f is not None and f.unit_count == 100
        finally:
            s.close()

    def test_in_transit_fleet_not_affected(self, db, test_nation):
        home = _territory(db, "ha_nh2_h", test_nation.id)
        dest = _territory(db, "ha_nh2_d")
        _fleet(db, test_nation.id, home.id, units=100, status="in_transit",
               dest_id=dest.id)

        _run_tick(db)

        s = SessionLocal()
        try:
            f = s.query(Fleet).filter(Fleet.nation_id == test_nation.id,
                                      Fleet.status == "in_transit").first()
            assert f is not None and f.unit_count == 100
        finally:
            s.close()

    def test_pending_confirmation_fleet_not_affected(self, db, test_nation):
        home = _territory(db, "ha_nh3_h", test_nation.id)
        dest = _territory(db, "ha_nh3_d")
        _fleet(db, test_nation.id, home.id, units=100,
               status="pending_confirmation", dest_id=dest.id)

        _run_tick(db)

        s = SessionLocal()
        try:
            f = s.query(Fleet).filter(Fleet.nation_id == test_nation.id,
                                      Fleet.status == "pending_confirmation").first()
            assert f is not None and f.unit_count == 100
        finally:
            s.close()


# ---------------------------------------------------------------------------
# 6. Nation isolation
# ---------------------------------------------------------------------------

class TestIsolation:

    def test_each_nations_holding_fleet_attrition_is_independent(
        self, db, test_nation, other_nation
    ):
        home_a = _territory(db, "ha_iso_ha", test_nation.id)
        home_b = _territory(db, "ha_iso_hb", other_nation.id)
        dest   = _territory(db, "ha_iso_d")

        fleet_a = _holding_fleet(db, test_nation.id,  home_a.id, dest.id, units=100)
        fleet_b = _holding_fleet(db, other_nation.id, home_b.id, dest.id, units=200)

        _run_tick(db)

        s = SessionLocal()
        try:
            fa = s.query(Fleet).filter(Fleet.id == fleet_a.id).first()
            fb = s.query(Fleet).filter(Fleet.id == fleet_b.id).first()
            assert fa.unit_count == 99   # max(1, round(100*0.01)) = 1
            assert fb.unit_count == 198  # max(1, round(200*0.01)) = 2
        finally:
            s.close()
