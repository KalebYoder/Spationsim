"""
Integration tests for the dissent system tick logic.

Dissent is a per-territory integer [0, 100].  Each tick the tick worker:
  1. Adds war-wide penalty to ALL colonized territories of warring nations:
       aggressor +3, defender +2
       Multi-war rule: penalty is the MAX of any single war, not the sum.
       A nation in two wars accrues from only the worst one.
  2. Adds fleet-presence bonus to the territory under occupation:
       holding fleet +6, engaged fleet +10
  3. Applies decay (already-negative constants):
       at peace               → -3/tick
       at war, no fleet here  → -2/tick
       fleet present          →  0/tick (no natural decay)
  4. Adds propaganda-office bonus (extra decay):
       normally               → -2/tick  (stacks with base decay)
       while fleet present    → -3/tick  (amplified)
  5. Clamps result to [0, 100]
  6. Vacation-mode nations are skipped entirely — no rise, no decay
  7. Logs a dissent_threshold_crossed event when crossing 25/50/75/100

Net balance reference:
  peace, no fleet           → 0 + (-3) = -3/tick
  war defender, no fleet    → +2 + (-2) = 0  (stable)
  war defender, holding     → +2 + 6 + 0 = +8/tick
  war defender, engaged     → +2 + 10 + 0 = +12/tick
  war aggressor, no fleet   → +3 + (-2) = +1/tick
  propaganda office (peace) → 0 + (-3) + (-2) = -5/tick
  propaganda office (war, no fleet) → +2 + (-2) + (-2) = -2/tick
  propaganda office (holding fleet) → +2 + 6 + 0 + (-3) = +9/tick
  two wars, aggressor in both → max(3,3) = +3 (not +6), net +1/tick
  two wars, aggressor+defender → max(3,2) = +3 (not +5), net +1/tick
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

from app.models.diplomacy import Diplomacy
from app.models.event import Event
from app.models.fleet import Fleet
from app.models.infrastructure import Infrastructure
from app.models.nation import Nation
from app.models.player import Player
from app.models.territory import Territory
from app.models.territory_dissent import TerritoryDissent
from app.core.security import hash_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_tick(db: Session) -> None:
    db.commit()
    from app.tasks.tick import run_tick
    run_tick()


def _player(db: Session, username: str, vacation: bool = False) -> Player:
    p = Player(
        username=username,
        email=f"{username}@test.example",
        password_hash=hash_password("pw"),
        vacation_mode=vacation,
    )
    db.add(p)
    db.flush()
    return p


def _nation(db: Session, player_id: int) -> Nation:
    n = Nation(
        player_id=player_id,
        name=f"Nation-{player_id}",
        minerals=0,
        fuel=0,
        currency=0,
    )
    db.add(n)
    db.flush()
    return n


def _territory(
    db: Session,
    node_key: str,
    nation_id: int | None = None,
    *,
    colonized: bool = True,
) -> Territory:
    t = Territory(
        node_key=node_key,
        territory_type="normal",
        nation_id=nation_id,
        mineral_richness=1,
        fuel_richness=1,
        distance_from_center=1,
        is_colonized=colonized and nation_id is not None,
        colonized_at=datetime.now(timezone.utc) if (colonized and nation_id) else None,
    )
    db.add(t)
    db.flush()
    return t


def _dissent_row(db: Session, territory_id: int, dissent: int) -> TerritoryDissent:
    row = TerritoryDissent(territory_id=territory_id, dissent=dissent)
    db.add(row)
    db.flush()
    return row


def _declare_war(db: Session, nation_a: Nation, nation_b: Nation, declared_by: Nation) -> Diplomacy:
    a_id = min(nation_a.id, nation_b.id)
    b_id = max(nation_a.id, nation_b.id)
    row = Diplomacy(nation_a=a_id, nation_b=b_id, status="war", declared_by=declared_by.id)
    db.add(row)
    db.flush()
    return row


def _fleet(
    db: Session,
    nation_id: int,
    origin_territory_id: int,
    units: int,
    status: str,
    dest_id: int | None = None,
) -> Fleet:
    f = Fleet(
        nation_id=nation_id,
        origin_territory=origin_territory_id,
        destination_territory=dest_id,
        unit_count=units,
        status=status,
        standing_order="hold",
    )
    db.add(f)
    db.flush()
    return f


def _propaganda_office(db: Session, territory_id: int) -> Infrastructure:
    infra = Infrastructure(
        territory_id=territory_id,
        type="propaganda_office",
        status="active",
    )
    db.add(infra)
    db.flush()
    return infra


def _get_dissent(db: Session, territory_id: int) -> int:
    row = db.query(TerritoryDissent).filter(
        TerritoryDissent.territory_id == territory_id
    ).first()
    return row.dissent if row else 0


# ---------------------------------------------------------------------------
# Peace-state decay
# ---------------------------------------------------------------------------

def test_dissent_decays_by_3_at_peace(db):
    p = _player(db, "alpha")
    n = _nation(db, p.id)
    t = _territory(db, "0,0", n.id)
    _dissent_row(db, t.id, 40)

    _run_tick(db)

    assert _get_dissent(db, t.id) == 37


def test_dissent_clamped_at_zero_at_peace(db):
    p = _player(db, "alpha")
    n = _nation(db, p.id)
    t = _territory(db, "0,0", n.id)
    _dissent_row(db, t.id, 2)

    _run_tick(db)

    assert _get_dissent(db, t.id) == 0


def test_dissent_row_created_at_zero_for_colonized_territory(db):
    p = _player(db, "alpha")
    n = _nation(db, p.id)
    t = _territory(db, "0,0", n.id)
    # No dissent row pre-created

    _run_tick(db)

    assert _get_dissent(db, t.id) == 0


# ---------------------------------------------------------------------------
# War defender — non-frontline (net 0)
# ---------------------------------------------------------------------------

def test_war_defender_non_frontline_is_stable(db):
    p_def = _player(db, "defender")
    p_agg = _player(db, "aggressor")
    n_def = _nation(db, p_def.id)
    n_agg = _nation(db, p_agg.id)
    t = _territory(db, "0,0", n_def.id)
    _dissent_row(db, t.id, 30)
    _declare_war(db, n_def, n_agg, declared_by=n_agg)

    _run_tick(db)

    # +2 (defender war) + (-2) (war decay) = 0
    assert _get_dissent(db, t.id) == 30


# ---------------------------------------------------------------------------
# War aggressor — slow rise (+1/tick)
# ---------------------------------------------------------------------------

def test_war_aggressor_rises_1_per_tick(db):
    p_def = _player(db, "defender")
    p_agg = _player(db, "aggressor")
    n_def = _nation(db, p_def.id)
    n_agg = _nation(db, p_agg.id)
    t_agg = _territory(db, "1,0", n_agg.id)
    _dissent_row(db, t_agg.id, 20)
    _declare_war(db, n_def, n_agg, declared_by=n_agg)

    _run_tick(db)

    # +3 (aggressor war) + (-2) (war decay) = +1
    assert _get_dissent(db, t_agg.id) == 21


# ---------------------------------------------------------------------------
# Fleet presence — holding (+8/tick)
# ---------------------------------------------------------------------------

def test_holding_fleet_raises_dissent_8_per_tick(db):
    p_def = _player(db, "defender")
    p_agg = _player(db, "aggressor")
    n_def = _nation(db, p_def.id)
    n_agg = _nation(db, p_agg.id)
    t_def = _territory(db, "0,0", n_def.id)
    _dissent_row(db, t_def.id, 10)
    _declare_war(db, n_def, n_agg, declared_by=n_agg)
    # Aggressor fleet holding on defender's territory
    _fleet(db, n_agg.id, t_def.id, units=50, status="holding", dest_id=t_def.id)

    _run_tick(db)

    # +2 (defender war) + 6 (holding) + 0 (occupied decay) = +8
    assert _get_dissent(db, t_def.id) == 18


# ---------------------------------------------------------------------------
# Fleet presence — engaged (+12/tick)
# ---------------------------------------------------------------------------

def test_engaged_fleet_raises_dissent_12_per_tick(db):
    p_def = _player(db, "defender")
    p_agg = _player(db, "aggressor")
    n_def = _nation(db, p_def.id)
    n_agg = _nation(db, p_agg.id)
    t_def = _territory(db, "0,0", n_def.id)
    _dissent_row(db, t_def.id, 10)
    _declare_war(db, n_def, n_agg, declared_by=n_agg)
    _fleet(db, n_agg.id, t_def.id, units=50, status="engaged", dest_id=t_def.id)

    _run_tick(db)

    # +2 (defender war) + 10 (engaged) + 0 (occupied decay) = +12
    assert _get_dissent(db, t_def.id) == 22


# ---------------------------------------------------------------------------
# Clamping at 100
# ---------------------------------------------------------------------------

def test_dissent_clamped_at_100(db):
    p_def = _player(db, "defender")
    p_agg = _player(db, "aggressor")
    n_def = _nation(db, p_def.id)
    n_agg = _nation(db, p_agg.id)
    t_def = _territory(db, "0,0", n_def.id)
    _dissent_row(db, t_def.id, 95)
    _declare_war(db, n_def, n_agg, declared_by=n_agg)
    _fleet(db, n_agg.id, t_def.id, units=50, status="holding", dest_id=t_def.id)

    _run_tick(db)

    # Would be 95 + 8 = 103 without clamping
    assert _get_dissent(db, t_def.id) == 100


# ---------------------------------------------------------------------------
# Vacation mode bypass
# ---------------------------------------------------------------------------

def test_vacation_mode_skips_dissent_decay(db):
    p = _player(db, "vacationer", vacation=True)
    n = _nation(db, p.id)
    t = _territory(db, "0,0", n.id)
    _dissent_row(db, t.id, 50)

    _run_tick(db)

    # Vacation mode: tick frozen, dissent unchanged
    assert _get_dissent(db, t.id) == 50


def test_vacation_mode_skips_dissent_accumulation_during_war(db):
    p_vac = _player(db, "vacationer", vacation=True)
    p_agg = _player(db, "aggressor")
    n_vac = _nation(db, p_vac.id)
    n_agg = _nation(db, p_agg.id)
    t_vac = _territory(db, "0,0", n_vac.id)
    _dissent_row(db, t_vac.id, 20)
    _declare_war(db, n_vac, n_agg, declared_by=n_agg)
    _fleet(db, n_agg.id, t_vac.id, units=50, status="holding", dest_id=t_vac.id)

    _run_tick(db)

    # Even with holding fleet, vacation mode freezes all dissent changes
    assert _get_dissent(db, t_vac.id) == 20


def test_active_nation_still_accumulates_while_neighbor_vacations(db):
    p_active = _player(db, "active")
    p_vac = _player(db, "vacationer", vacation=True)
    n_active = _nation(db, p_active.id)
    n_vac = _nation(db, p_vac.id)
    t_active = _territory(db, "0,0", n_active.id)
    t_vac = _territory(db, "1,0", n_vac.id)
    _dissent_row(db, t_active.id, 40)
    _dissent_row(db, t_vac.id, 40)
    _declare_war(db, n_active, n_vac, declared_by=n_vac)

    _run_tick(db)

    # active nation (defender): +2 + (-2) = 0, stays at 40
    assert _get_dissent(db, t_active.id) == 40
    # vacation nation (aggressor): frozen, stays at 40
    assert _get_dissent(db, t_vac.id) == 40


# ---------------------------------------------------------------------------
# Propaganda Office decay bonus
# ---------------------------------------------------------------------------

def test_propaganda_office_adds_2_decay_at_peace(db):
    p = _player(db, "alpha")
    n = _nation(db, p.id)
    t = _territory(db, "0,0", n.id)
    _dissent_row(db, t.id, 40)
    _propaganda_office(db, t.id)

    _run_tick(db)

    # 0 + (-3) + (-2) = -5
    assert _get_dissent(db, t.id) == 35


def test_propaganda_office_adds_2_decay_at_war_no_fleet(db):
    p_def = _player(db, "defender")
    p_agg = _player(db, "aggressor")
    n_def = _nation(db, p_def.id)
    n_agg = _nation(db, p_agg.id)
    t_def = _territory(db, "0,0", n_def.id)
    _dissent_row(db, t_def.id, 30)
    _declare_war(db, n_def, n_agg, declared_by=n_agg)
    _propaganda_office(db, t_def.id)

    _run_tick(db)

    # +2 (defender) + (-2) (war decay) + (-2) (office normal) = -2
    assert _get_dissent(db, t_def.id) == 28


def test_propaganda_office_adds_3_decay_under_holding_fleet(db):
    p_def = _player(db, "defender")
    p_agg = _player(db, "aggressor")
    n_def = _nation(db, p_def.id)
    n_agg = _nation(db, p_agg.id)
    t_def = _territory(db, "0,0", n_def.id)
    _dissent_row(db, t_def.id, 10)
    _declare_war(db, n_def, n_agg, declared_by=n_agg)
    _fleet(db, n_agg.id, t_def.id, units=50, status="holding", dest_id=t_def.id)
    _propaganda_office(db, t_def.id)

    _run_tick(db)

    # +2 (defender) + 6 (holding) + 0 (occupied decay) + (-3) (office occupied) = +5
    assert _get_dissent(db, t_def.id) == 15


def test_propaganda_office_adds_3_decay_under_engaged_fleet(db):
    p_def = _player(db, "defender")
    p_agg = _player(db, "aggressor")
    n_def = _nation(db, p_def.id)
    n_agg = _nation(db, p_agg.id)
    t_def = _territory(db, "0,0", n_def.id)
    _dissent_row(db, t_def.id, 10)
    _declare_war(db, n_def, n_agg, declared_by=n_agg)
    _fleet(db, n_agg.id, t_def.id, units=50, status="engaged", dest_id=t_def.id)
    _propaganda_office(db, t_def.id)

    _run_tick(db)

    # +2 (defender) + 10 (engaged) + 0 (occupied decay) + (-3) (office occupied) = +9
    assert _get_dissent(db, t_def.id) == 19


# ---------------------------------------------------------------------------
# Threshold crossing events
# ---------------------------------------------------------------------------

def test_threshold_event_logged_when_dissent_rises_through_25(db):
    p_def = _player(db, "defender")
    p_agg = _player(db, "aggressor")
    n_def = _nation(db, p_def.id)
    n_agg = _nation(db, p_agg.id)
    t_def = _territory(db, "0,0", n_def.id)
    _dissent_row(db, t_def.id, 20)
    _declare_war(db, n_def, n_agg, declared_by=n_agg)
    _fleet(db, n_agg.id, t_def.id, units=50, status="holding", dest_id=t_def.id)

    _run_tick(db)

    # 20 + 8 = 28, crossed threshold 25
    event = db.query(Event).filter(
        Event.type == "dissent_threshold_crossed",
    ).first()
    assert event is not None
    assert event.payload["threshold"] == 25
    assert event.payload["direction"] == "rising"
    assert event.payload["nation_id"] == n_def.id
    assert event.payload["territory_id"] == t_def.id


def test_threshold_event_logged_when_dissent_falls_through_25(db):
    p = _player(db, "alpha")
    n = _nation(db, p.id)
    t = _territory(db, "0,0", n.id)
    _dissent_row(db, t.id, 26)  # just above 25

    _run_tick(db)

    # 26 + (-3) = 23, crossed threshold 25 downward
    event = db.query(Event).filter(
        Event.type == "dissent_threshold_crossed",
    ).first()
    assert event is not None
    assert event.payload["threshold"] == 25
    assert event.payload["direction"] == "falling"


def test_no_threshold_event_when_dissent_does_not_cross(db):
    p = _player(db, "alpha")
    n = _nation(db, p.id)
    t = _territory(db, "0,0", n.id)
    _dissent_row(db, t.id, 30)  # above 25, decays to 27 — doesn't cross

    _run_tick(db)

    count = db.query(Event).filter(Event.type == "dissent_threshold_crossed").count()
    assert count == 0


def test_multiple_threshold_crossings_in_one_tick(db):
    # Start at 22, engaged fleet (no war needed for fleet test by itself? actually need war)
    # But actually the simpler case: start at 22 with engaged fleet, crosses 25
    p_def = _player(db, "defender")
    p_agg = _player(db, "aggressor")
    n_def = _nation(db, p_def.id)
    n_agg = _nation(db, p_agg.id)
    t_def = _territory(db, "0,0", n_def.id)
    _dissent_row(db, t_def.id, 38)  # crosses 50 in one tick: 38 + 12 = 50
    _declare_war(db, n_def, n_agg, declared_by=n_agg)
    _fleet(db, n_agg.id, t_def.id, units=50, status="engaged", dest_id=t_def.id)

    _run_tick(db)

    # 38 + 12 = 50, exactly hits threshold 50 → crossing event
    events = db.query(Event).filter(Event.type == "dissent_threshold_crossed").all()
    thresholds = {e.payload["threshold"] for e in events}
    assert 50 in thresholds


# ---------------------------------------------------------------------------
# Non-colonized and void territories are not touched
# ---------------------------------------------------------------------------

def test_void_unclaimed_territory_gets_no_dissent_row(db):
    p = _player(db, "alpha")
    n = _nation(db, p.id)
    void_t = Territory(
        node_key="99,99",
        territory_type="void",
        nation_id=None,
        mineral_richness=0,
        fuel_richness=0,
        distance_from_center=10,
        is_colonized=False,
    )
    db.add(void_t)
    db.flush()

    _run_tick(db)

    row = db.query(TerritoryDissent).filter(
        TerritoryDissent.territory_id == void_t.id
    ).first()
    assert row is None


def test_owned_but_uncolonized_territory_not_processed(db):
    p = _player(db, "alpha")
    n = _nation(db, p.id)
    # Claimed (nation_id set) but is_colonized=False — should not be processed
    t = Territory(
        node_key="5,5",
        territory_type="void",
        nation_id=n.id,
        mineral_richness=0,
        fuel_richness=0,
        distance_from_center=3,
        is_colonized=False,
    )
    db.add(t)
    db.flush()

    _run_tick(db)

    row = db.query(TerritoryDissent).filter(
        TerritoryDissent.territory_id == t.id
    ).first()
    assert row is None


# ---------------------------------------------------------------------------
# Nation isolation — only the affected nation's territories change
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Multi-war cap — each planet uses the single highest war contribution
# ---------------------------------------------------------------------------

def test_two_wars_as_aggressor_not_stacked(db):
    """Nation aggressor in two simultaneous wars: penalty is max(3,3)=3, not 6."""
    p_agg = _player(db, "aggressor")
    p_d1 = _player(db, "defender1")
    p_d2 = _player(db, "defender2")
    n_agg = _nation(db, p_agg.id)
    n_d1 = _nation(db, p_d1.id)
    n_d2 = _nation(db, p_d2.id)
    t_agg = _territory(db, "0,0", n_agg.id)
    _dissent_row(db, t_agg.id, 20)
    _declare_war(db, n_agg, n_d1, declared_by=n_agg)
    _declare_war(db, n_agg, n_d2, declared_by=n_agg)

    _run_tick(db)

    # max(3, 3) + (-2 war decay) = +1
    assert _get_dissent(db, t_agg.id) == 21


def test_two_wars_aggressor_and_defender_uses_higher(db):
    """Nation is aggressor (+3) in war A and defender (+2) in war B: penalty is max(3,2)=3."""
    p_a = _player(db, "mixed")
    p_b = _player(db, "enemy1")
    p_c = _player(db, "enemy2")
    n_a = _nation(db, p_a.id)
    n_b = _nation(db, p_b.id)
    n_c = _nation(db, p_c.id)
    t_a = _territory(db, "0,0", n_a.id)
    _dissent_row(db, t_a.id, 20)
    _declare_war(db, n_a, n_b, declared_by=n_a)   # n_a is aggressor → +3
    _declare_war(db, n_a, n_c, declared_by=n_c)   # n_a is defender  → +2

    _run_tick(db)

    # max(3, 2) + (-2 war decay) = +1
    assert _get_dissent(db, t_a.id) == 21


def test_two_wars_both_as_defender_not_stacked(db):
    """Nation is defender in two wars: penalty is max(2,2)=2 (stable, not +4)."""
    p_def = _player(db, "defender")
    p_a1 = _player(db, "aggressor1")
    p_a2 = _player(db, "aggressor2")
    n_def = _nation(db, p_def.id)
    n_a1 = _nation(db, p_a1.id)
    n_a2 = _nation(db, p_a2.id)
    t_def = _territory(db, "0,0", n_def.id)
    _dissent_row(db, t_def.id, 30)
    _declare_war(db, n_def, n_a1, declared_by=n_a1)
    _declare_war(db, n_def, n_a2, declared_by=n_a2)

    _run_tick(db)

    # max(2, 2) + (-2 war decay) = 0, stable
    assert _get_dissent(db, t_def.id) == 30


def test_war_dissent_applies_only_to_territories_of_warring_nations(db):
    p_a = _player(db, "nation_a")
    p_b = _player(db, "nation_b")
    p_c = _player(db, "nation_c")
    n_a = _nation(db, p_a.id)
    n_b = _nation(db, p_b.id)
    n_c = _nation(db, p_c.id)
    t_a = _territory(db, "0,0", n_a.id)
    t_c = _territory(db, "5,5", n_c.id)
    _dissent_row(db, t_a.id, 30)
    _dissent_row(db, t_c.id, 30)
    _declare_war(db, n_a, n_b, declared_by=n_b)

    _run_tick(db)

    # Nation A (defender): +2 - 2 = 0 (stable)
    assert _get_dissent(db, t_a.id) == 30
    # Nation C (at peace): -3 decay
    assert _get_dissent(db, t_c.id) == 27
