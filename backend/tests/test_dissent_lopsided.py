"""
Test suite for two dissent mechanics added on top of the base dissent system:

1. Lopsided-war dissent multiplier
   - War declaration marks diplomacy.is_lopsided = True when aggressor has
     strictly more than 3x the defender's military strength (total fleet unit_count).
   - During each dissent tick, lopsided wars apply
     DISSENT_WAR_AGGRESSOR * DISSENT_LOPSIDED_MULTIPLIER to aggressor territories
     instead of the flat DISSENT_WAR_AGGRESSOR.
   - Defender dissent and the multi-war MAX cap are not affected.

2. Propaganda Office bonus cap during active aggression
   - When a territory's nation is the declared_by party in any active war
     (diplomacy.status == 'war'), the PO decay bonus is capped at
     DISSENT_OFFICE_BONUS_AGGRESSOR (= 1) instead of DISSENT_OFFICE_BONUS_NORMAL (= 2).
   - Defender territories still receive DISSENT_OFFICE_BONUS_NORMAL.
   - The cap only applies during status == 'war', NOT during 'war_pending'.

New constants expected in backend/app/constants.py:
    DISSENT_LOPSIDED_WAR_RATIO    = 3
    DISSENT_LOPSIDED_MULTIPLIER   = 1.5
    DISSENT_OFFICE_BONUS_AGGRESSOR = 1

New pure-service functions expected:
    backend/app/services/power.py
        military_strength(db: Session, nation_id: int) -> int

    backend/app/services/dissent.py
        compute_territory_dissent_delta(
            *,
            at_war: bool,
            is_aggressor: bool,
            is_lopsided_aggressor: bool,
            fleet_status: str | None,   # "holding" | "engaged" | None
            has_propaganda_office: bool,
            is_aggressor_in_any_active_war: bool,
        ) -> int

New DB column expected on Diplomacy:
    is_lopsided = Column(Boolean, default=False, nullable=False)

The developer must also add is_lopsided to the Diplomacy SQLAlchemy model.
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
from app.models.fleet import Fleet
from app.models.infrastructure import Infrastructure
from app.models.nation import Nation
from app.models.player import Player
from app.models.territory import Territory
from app.models.territory_dissent import TerritoryDissent
from app.core.security import hash_password


# ---------------------------------------------------------------------------
# Constants that the new implementation must expose
# ---------------------------------------------------------------------------

from app.constants import (
    DISSENT_WAR_AGGRESSOR,
    DISSENT_WAR_DEFENDER,
    DISSENT_DECAY_PEACE,
    DISSENT_DECAY_WAR,
    DISSENT_DECAY_OCCUPIED,
    DISSENT_FLEET_HOLDING,
    DISSENT_FLEET_ENGAGED,
    DISSENT_OFFICE_BONUS_NORMAL,
    DISSENT_OFFICE_BONUS_OCCUPIED,
    DISSENT_LOPSIDED_WAR_RATIO,
    DISSENT_LOPSIDED_MULTIPLIER,
    DISSENT_OFFICE_BONUS_AGGRESSOR,
)

# ---------------------------------------------------------------------------
# Service-function imports (these modules do not exist yet — the developer
# must create them).  Importing here fails fast during collection if the
# modules are missing, which is the intended TDD behaviour.
# ---------------------------------------------------------------------------

from app.services.power import military_strength
from app.services.dissent import compute_territory_dissent_delta


# ---------------------------------------------------------------------------
# DB helpers (mirror the pattern used in test_dissent.py)
# ---------------------------------------------------------------------------

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
        is_owned=colonized and nation_id is not None,
        owned_at=datetime.now(timezone.utc) if (colonized and nation_id) else None,
    )
    db.add(t)
    db.flush()
    return t


def _fleet(
    db: Session,
    nation_id: int,
    territory_id: int,
    units: int,
    status: str = "stationed",
    dest_id: int | None = None,
) -> Fleet:
    f = Fleet(
        nation_id=nation_id,
        origin_territory=territory_id,
        destination_territory=dest_id,
        unit_count=units,
        status=status,
        standing_order="hold",
    )
    db.add(f)
    db.flush()
    return f


def _declare_war(
    db: Session,
    nation_a: Nation,
    nation_b: Nation,
    declared_by: Nation,
    *,
    status: str = "war",
    is_lopsided: bool = False,
) -> Diplomacy:
    a_id = min(nation_a.id, nation_b.id)
    b_id = max(nation_a.id, nation_b.id)
    row = Diplomacy(
        nation_a=a_id,
        nation_b=b_id,
        status=status,
        declared_by=declared_by.id,
        is_lopsided=is_lopsided,
    )
    db.add(row)
    db.flush()
    return row


def _dissent_row(db: Session, territory_id: int, dissent: int) -> TerritoryDissent:
    row = TerritoryDissent(territory_id=territory_id, dissent=dissent)
    db.add(row)
    db.flush()
    return row


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


def _run_tick(db: Session) -> None:
    db.commit()
    from app.tasks.tick import run_tick
    run_tick()


# ===========================================================================
# Part 1 — military_strength service function (pure DB query, no tick needed)
# ===========================================================================

class TestMilitaryStrengthService:
    """Tests for app.services.power.military_strength(db, nation_id)."""

    def test_no_fleets_returns_zero(self, db: Session):
        """A nation with zero fleets must return military_strength = 0."""
        p = _player(db, "nofleet")
        n = _nation(db, p.id)
        db.flush()

        result = military_strength(db, n.id)

        assert result == 0

    def test_single_fleet_returns_unit_count(self, db: Session):
        """A nation with one fleet returns exactly that fleet's unit_count."""
        p = _player(db, "onefleet")
        n = _nation(db, p.id)
        t = _territory(db, "0,0", n.id)
        _fleet(db, n.id, t.id, units=42)
        db.flush()

        result = military_strength(db, n.id)

        assert result == 42

    def test_multiple_fleets_sums_all_unit_counts(self, db: Session):
        """unit_count values across all fleets owned by the nation are summed."""
        p = _player(db, "multifleet")
        n = _nation(db, p.id)
        t = _territory(db, "1,0", n.id)
        _fleet(db, n.id, t.id, units=10, status="stationed")
        _fleet(db, n.id, t.id, units=20, status="in_transit")
        _fleet(db, n.id, t.id, units=5,  status="holding")
        db.flush()

        result = military_strength(db, n.id)

        assert result == 35

    def test_all_fleet_statuses_counted(self, db: Session):
        """Fleets in every meaningful status (stationed, in_transit, holding, engaged,
        pending_confirmation) all contribute to military_strength."""
        p = _player(db, "allstatuses")
        n = _nation(db, p.id)
        t = _territory(db, "2,0", n.id)
        for status, units in [
            ("stationed", 3),
            ("in_transit", 3),
            ("holding", 3),
            ("engaged", 3),
            ("pending_confirmation", 3),
        ]:
            _fleet(db, n.id, t.id, units=units, status=status)
        db.flush()

        result = military_strength(db, n.id)

        assert result == 15

    def test_other_nation_fleets_not_counted(self, db: Session):
        """Fleets belonging to a different nation must not affect the result."""
        p1 = _player(db, "ms_nation1")
        p2 = _player(db, "ms_nation2")
        n1 = _nation(db, p1.id)
        n2 = _nation(db, p2.id)
        t1 = _territory(db, "3,0", n1.id)
        t2 = _territory(db, "4,0", n2.id)
        _fleet(db, n1.id, t1.id, units=7)
        _fleet(db, n2.id, t2.id, units=99)
        db.flush()

        result = military_strength(db, n1.id)

        assert result == 7

    def test_nation_with_zero_unit_fleet_returns_zero(self, db: Session):
        """A fleet row with unit_count=0 contributes 0 (no crash, no negative value)."""
        p = _player(db, "zerounit")
        n = _nation(db, p.id)
        t = _territory(db, "5,0", n.id)
        _fleet(db, n.id, t.id, units=0)
        db.flush()

        result = military_strength(db, n.id)

        assert result == 0


# ===========================================================================
# Part 2 — is_lopsided flag at war declaration (DB-state tests)
# ===========================================================================

class TestLopsidedFlagAtWarDeclaration:
    """
    The war declaration endpoint (or service) must set is_lopsided on the
    Diplomacy row based on the military strength ratio at declaration time.

    These tests seed fleet state, trigger war declaration via the endpoint, then
    inspect the resulting diplomacy row directly in the DB.

    Threshold: aggressor_strength > DISSENT_LOPSIDED_WAR_RATIO × defender_strength
    The ratio constant is 3, and the comparison is STRICTLY GREATER THAN.
    """

    # The war declaration endpoint path based on existing test_war.py
    WAR_ENDPOINT = "/api/diplomacy/war"

    def _war_client(self, db: Session, player: Player):
        """Return an auth client for the given player, wired to the test session."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.db.database import get_db
        from app.core.security import create_access_token

        def _override():
            yield db

        token = create_access_token(player.id)
        app.dependency_overrides[get_db] = _override
        c = TestClient(app, raise_server_exceptions=True)
        c.cookies.set("session", token)
        return c, app

    def _get_war_row(self, db: Session, n1: Nation, n2: Nation) -> Diplomacy | None:
        a, b = min(n1.id, n2.id), max(n1.id, n2.id)
        return db.query(Diplomacy).filter(
            Diplomacy.nation_a == a,
            Diplomacy.nation_b == b,
        ).first()

    def test_lopsided_true_when_aggressor_4x_defender(self, db: Session):
        """
        Aggressor has 4× more units than defender (4 > 3× threshold).
        is_lopsided must be set to True on the diplomacy row.
        """
        p_agg = _player(db, "agg_4x")
        p_def = _player(db, "def_4x")
        n_agg = _nation(db, p_agg.id)
        n_def = _nation(db, p_def.id)
        t_agg = _territory(db, "10,0", n_agg.id)
        t_def = _territory(db, "10,1", n_def.id)
        # Aggressor: 400 units, Defender: 100 units → 400 > 3×100 → lopsided
        _fleet(db, n_agg.id, t_agg.id, units=400)
        _fleet(db, n_def.id, t_def.id, units=100)
        db.commit()

        c, app_ = self._war_client(db, p_agg)
        try:
            resp = c.post(self.WAR_ENDPOINT, json={"target_nation_id": n_def.id})
            assert resp.status_code in (200, 201), resp.text
        finally:
            app_.dependency_overrides.clear()

        db.expire_all()
        row = self._get_war_row(db, n_agg, n_def)
        assert row is not None, "Diplomacy row must exist after war declaration"
        assert row.is_lopsided is True, (
            f"Expected is_lopsided=True for 400 vs 100 units "
            f"(ratio {400 / 100} > {DISSENT_LOPSIDED_WAR_RATIO}×), got {row.is_lopsided}"
        )

    def test_lopsided_false_when_aggressor_exactly_3x_defender(self, db: Session):
        """
        Aggressor has exactly 3× more units than defender.
        Threshold is STRICTLY GREATER THAN, so 3× must NOT be lopsided.
        is_lopsided must be False.
        """
        p_agg = _player(db, "agg_3x")
        p_def = _player(db, "def_3x")
        n_agg = _nation(db, p_agg.id)
        n_def = _nation(db, p_def.id)
        t_agg = _territory(db, "11,0", n_agg.id)
        t_def = _territory(db, "11,1", n_def.id)
        # 300 vs 100 → exactly 3× → NOT lopsided
        _fleet(db, n_agg.id, t_agg.id, units=300)
        _fleet(db, n_def.id, t_def.id, units=100)
        db.commit()

        c, app_ = self._war_client(db, p_agg)
        try:
            resp = c.post(self.WAR_ENDPOINT, json={"target_nation_id": n_def.id})
            assert resp.status_code in (200, 201), resp.text
        finally:
            app_.dependency_overrides.clear()

        db.expire_all()
        row = self._get_war_row(db, n_agg, n_def)
        assert row is not None
        assert row.is_lopsided is False, (
            f"Expected is_lopsided=False for 300 vs 100 (ratio exactly {DISSENT_LOPSIDED_WAR_RATIO}×), "
            f"got {row.is_lopsided}"
        )

    def test_lopsided_false_when_aggressor_less_than_3x_defender(self, db: Session):
        """
        Aggressor has less than 3× — the war is not lopsided.
        """
        p_agg = _player(db, "agg_2x")
        p_def = _player(db, "def_2x")
        n_agg = _nation(db, p_agg.id)
        n_def = _nation(db, p_def.id)
        t_agg = _territory(db, "12,0", n_agg.id)
        t_def = _territory(db, "12,1", n_def.id)
        # 200 vs 100 → 2× → not lopsided
        _fleet(db, n_agg.id, t_agg.id, units=200)
        _fleet(db, n_def.id, t_def.id, units=100)
        db.commit()

        c, app_ = self._war_client(db, p_agg)
        try:
            resp = c.post(self.WAR_ENDPOINT, json={"target_nation_id": n_def.id})
            assert resp.status_code in (200, 201), resp.text
        finally:
            app_.dependency_overrides.clear()

        db.expire_all()
        row = self._get_war_row(db, n_agg, n_def)
        assert row is not None
        assert row.is_lopsided is False, (
            f"Expected is_lopsided=False for 200 vs 100, got {row.is_lopsided}"
        )

    def test_lopsided_false_when_both_sides_have_zero_units(self, db: Session):
        """
        Both sides have 0 units.  0 > 3×0 is False.
        is_lopsided must be False (no division-by-zero crash, no incorrect True).
        """
        p_agg = _player(db, "agg_0")
        p_def = _player(db, "def_0")
        n_agg = _nation(db, p_agg.id)
        n_def = _nation(db, p_def.id)
        # No fleets at all for either nation
        db.commit()

        c, app_ = self._war_client(db, p_agg)
        try:
            resp = c.post(self.WAR_ENDPOINT, json={"target_nation_id": n_def.id})
            assert resp.status_code in (200, 201), resp.text
        finally:
            app_.dependency_overrides.clear()

        db.expire_all()
        row = self._get_war_row(db, n_agg, n_def)
        assert row is not None
        assert row.is_lopsided is False, (
            "0 > 3×0 is False; is_lopsided must not be True when both sides have 0 units"
        )

    def test_lopsided_false_when_aggressor_has_zero_units_defender_nonzero(self, db: Session):
        """
        Aggressor with 0 units vs defender with units → 0 > 3×N is always False.
        """
        p_agg = _player(db, "agg_0_vs_def")
        p_def = _player(db, "def_0_vs_def")
        n_agg = _nation(db, p_agg.id)
        n_def = _nation(db, p_def.id)
        t_def = _territory(db, "13,1", n_def.id)
        _fleet(db, n_def.id, t_def.id, units=50)
        db.commit()

        c, app_ = self._war_client(db, p_agg)
        try:
            resp = c.post(self.WAR_ENDPOINT, json={"target_nation_id": n_def.id})
            assert resp.status_code in (200, 201), resp.text
        finally:
            app_.dependency_overrides.clear()

        db.expire_all()
        row = self._get_war_row(db, n_agg, n_def)
        assert row is not None
        assert row.is_lopsided is False


# ===========================================================================
# Part 3 — Pure-function dissent arithmetic (compute_territory_dissent_delta)
# ===========================================================================
#
# These tests exercise the arithmetic without any DB or tick runner.
# The service function must accept keyword-only arguments describing the
# territory's situation and return the integer delta for one tick.
#
# Expected signature (see module docstring at top of file for full spec):
#
#   compute_territory_dissent_delta(
#       *,
#       at_war: bool,
#       is_aggressor: bool,
#       is_lopsided_aggressor: bool,
#       fleet_status: str | None,
#       has_propaganda_office: bool,
#       is_aggressor_in_any_active_war: bool,
#   ) -> int
#
# Note: `is_lopsided_aggressor` is only meaningful when at_war=True,
# is_aggressor=True, and the specific war is_lopsided=True.
# `is_aggressor_in_any_active_war` controls the PO bonus cap.
# ===========================================================================

class TestComputeDissentDeltaPureFunction:
    """
    Unit tests for compute_territory_dissent_delta.
    No DB, no tick runner — pure arithmetic verification.
    """

    # --- Baseline (non-lopsided) cases to confirm existing behaviour preserved ---

    def test_peace_no_fleet_no_office_baseline(self):
        """At peace, no fleet, no office: delta = DISSENT_DECAY_PEACE (= -3)."""
        delta = compute_territory_dissent_delta(
            at_war=False,
            is_aggressor=False,
            is_lopsided_aggressor=False,
            fleet_status=None,
            has_propaganda_office=False,
            is_aggressor_in_any_active_war=False,
        )
        assert delta == DISSENT_DECAY_PEACE

    def test_war_aggressor_non_lopsided_no_fleet_no_office(self):
        """
        Non-lopsided aggressor, no fleet, no office.
        delta = DISSENT_WAR_AGGRESSOR + DISSENT_DECAY_WAR = 3 + (-2) = +1
        """
        delta = compute_territory_dissent_delta(
            at_war=True,
            is_aggressor=True,
            is_lopsided_aggressor=False,
            fleet_status=None,
            has_propaganda_office=False,
            is_aggressor_in_any_active_war=True,
        )
        assert delta == DISSENT_WAR_AGGRESSOR + DISSENT_DECAY_WAR

    def test_war_defender_no_fleet_no_office_baseline(self):
        """
        Defender, no fleet, no office.
        delta = DISSENT_WAR_DEFENDER + DISSENT_DECAY_WAR = 2 + (-2) = 0
        """
        delta = compute_territory_dissent_delta(
            at_war=True,
            is_aggressor=False,
            is_lopsided_aggressor=False,
            fleet_status=None,
            has_propaganda_office=False,
            is_aggressor_in_any_active_war=False,
        )
        assert delta == DISSENT_WAR_DEFENDER + DISSENT_DECAY_WAR

    # --- Lopsided aggressor: 1.5× war penalty ---

    def test_lopsided_aggressor_no_fleet_no_office(self):
        """
        Lopsided aggressor, no fleet, no office.
        war_contribution = round(DISSENT_WAR_AGGRESSOR * DISSENT_LOPSIDED_MULTIPLIER)
        delta = war_contribution + DISSENT_DECAY_WAR
        """
        expected_war = round(DISSENT_WAR_AGGRESSOR * DISSENT_LOPSIDED_MULTIPLIER)  # round(3*1.5)=5 (not 4.5)
        expected_delta = expected_war + DISSENT_DECAY_WAR
        delta = compute_territory_dissent_delta(
            at_war=True,
            is_aggressor=True,
            is_lopsided_aggressor=True,
            fleet_status=None,
            has_propaganda_office=False,
            is_aggressor_in_any_active_war=True,
        )
        assert delta == expected_delta, (
            f"Lopsided aggressor war delta should be {expected_delta} "
            f"(war={expected_war} + decay={DISSENT_DECAY_WAR}), got {delta}"
        )

    def test_lopsided_multiplier_is_strictly_greater_than_normal(self):
        """
        The lopsided aggressor delta must be strictly larger than the
        non-lopsided aggressor delta (the multiplier must actually matter).
        """
        normal = compute_territory_dissent_delta(
            at_war=True,
            is_aggressor=True,
            is_lopsided_aggressor=False,
            fleet_status=None,
            has_propaganda_office=False,
            is_aggressor_in_any_active_war=True,
        )
        lopsided = compute_territory_dissent_delta(
            at_war=True,
            is_aggressor=True,
            is_lopsided_aggressor=True,
            fleet_status=None,
            has_propaganda_office=False,
            is_aggressor_in_any_active_war=True,
        )
        assert lopsided > normal, (
            f"Lopsided aggressor delta ({lopsided}) must exceed normal aggressor delta ({normal})"
        )

    def test_lopsided_flag_does_not_affect_defender(self):
        """
        If the nation is the DEFENDER in a lopsided war, their delta is the same
        as in a non-lopsided war.  is_lopsided_aggressor=True only matters when
        is_aggressor=True.
        """
        non_lopsided_def = compute_territory_dissent_delta(
            at_war=True,
            is_aggressor=False,
            is_lopsided_aggressor=False,
            fleet_status=None,
            has_propaganda_office=False,
            is_aggressor_in_any_active_war=False,
        )
        lopsided_def = compute_territory_dissent_delta(
            at_war=True,
            is_aggressor=False,
            is_lopsided_aggressor=True,   # flag present but irrelevant for defender
            fleet_status=None,
            has_propaganda_office=False,
            is_aggressor_in_any_active_war=False,
        )
        assert lopsided_def == non_lopsided_def, (
            "Defender dissent delta must not change because the war is flagged lopsided"
        )

    def test_non_lopsided_aggressor_uses_flat_war_constant(self):
        """
        Non-lopsided war: aggressor's war contribution is exactly DISSENT_WAR_AGGRESSOR
        (no multiplier applied).
        """
        delta = compute_territory_dissent_delta(
            at_war=True,
            is_aggressor=True,
            is_lopsided_aggressor=False,
            fleet_status=None,
            has_propaganda_office=False,
            is_aggressor_in_any_active_war=True,
        )
        # war contribution should be exactly DISSENT_WAR_AGGRESSOR (not the multiplied version)
        assert delta == DISSENT_WAR_AGGRESSOR + DISSENT_DECAY_WAR

    # --- PO bonus cap during active aggression ---

    def test_po_bonus_capped_at_aggressor_value_when_aggressor_at_peace_context(self):
        """
        Territory at peace with PO but the nation is the declared aggressor in an
        active war elsewhere.  PO bonus uses DISSENT_OFFICE_BONUS_AGGRESSOR (= 1)
        instead of DISSENT_OFFICE_BONUS_NORMAL (= 2).
        """
        delta = compute_territory_dissent_delta(
            at_war=False,       # this territory itself is not in a war context
            is_aggressor=False,
            is_lopsided_aggressor=False,
            fleet_status=None,
            has_propaganda_office=True,
            is_aggressor_in_any_active_war=True,  # nation is aggressor in some war
        )
        # decay = DISSENT_DECAY_PEACE + DISSENT_OFFICE_BONUS_AGGRESSOR (cap applied)
        expected = DISSENT_DECAY_PEACE - DISSENT_OFFICE_BONUS_AGGRESSOR
        assert delta == expected, (
            f"Aggressor PO bonus should be capped at {DISSENT_OFFICE_BONUS_AGGRESSOR}, "
            f"expected delta={expected}, got {delta}"
        )

    def test_po_bonus_normal_when_not_aggressor(self):
        """
        At peace with PO, nation is NOT the aggressor in any active war.
        PO bonus uses DISSENT_OFFICE_BONUS_NORMAL (= 2).
        """
        delta = compute_territory_dissent_delta(
            at_war=False,
            is_aggressor=False,
            is_lopsided_aggressor=False,
            fleet_status=None,
            has_propaganda_office=True,
            is_aggressor_in_any_active_war=False,
        )
        expected = DISSENT_DECAY_PEACE - DISSENT_OFFICE_BONUS_NORMAL
        assert delta == expected

    def test_po_bonus_aggressor_is_strictly_less_than_normal(self):
        """
        The aggressor PO bonus is smaller (less decay) than the normal bonus.
        DISSENT_OFFICE_BONUS_AGGRESSOR < DISSENT_OFFICE_BONUS_NORMAL must hold.
        """
        assert DISSENT_OFFICE_BONUS_AGGRESSOR < DISSENT_OFFICE_BONUS_NORMAL, (
            f"DISSENT_OFFICE_BONUS_AGGRESSOR ({DISSENT_OFFICE_BONUS_AGGRESSOR}) must be "
            f"less than DISSENT_OFFICE_BONUS_NORMAL ({DISSENT_OFFICE_BONUS_NORMAL})"
        )

    def test_defender_po_bonus_unaffected_by_lopsided_flag(self):
        """
        Defender territory with PO still gets DISSENT_OFFICE_BONUS_NORMAL regardless
        of whether the war is lopsided.
        """
        delta = compute_territory_dissent_delta(
            at_war=True,
            is_aggressor=False,
            is_lopsided_aggressor=False,
            fleet_status=None,
            has_propaganda_office=True,
            is_aggressor_in_any_active_war=False,
        )
        # +2 (defender) + (-2) (war decay) + (-2) (normal PO bonus) = -2
        expected = DISSENT_WAR_DEFENDER + DISSENT_DECAY_WAR - DISSENT_OFFICE_BONUS_NORMAL
        assert delta == expected

    def test_aggressor_war_with_po_uses_capped_bonus(self):
        """
        Aggressor territory during active war with PO: PO bonus is AGGRESSOR-capped.
        delta = DISSENT_WAR_AGGRESSOR + DISSENT_DECAY_WAR - DISSENT_OFFICE_BONUS_AGGRESSOR
        """
        delta = compute_territory_dissent_delta(
            at_war=True,
            is_aggressor=True,
            is_lopsided_aggressor=False,
            fleet_status=None,
            has_propaganda_office=True,
            is_aggressor_in_any_active_war=True,
        )
        expected = DISSENT_WAR_AGGRESSOR + DISSENT_DECAY_WAR - DISSENT_OFFICE_BONUS_AGGRESSOR
        assert delta == expected, (
            f"Aggressor at war with PO: expected {expected}, got {delta}"
        )

    def test_lopsided_aggressor_with_po_uses_capped_bonus(self):
        """
        Lopsided aggressor with PO: both the multiplied war penalty AND the
        aggressor PO cap apply simultaneously.
        """
        lopsided_war = round(DISSENT_WAR_AGGRESSOR * DISSENT_LOPSIDED_MULTIPLIER)
        expected = lopsided_war + DISSENT_DECAY_WAR - DISSENT_OFFICE_BONUS_AGGRESSOR
        delta = compute_territory_dissent_delta(
            at_war=True,
            is_aggressor=True,
            is_lopsided_aggressor=True,
            fleet_status=None,
            has_propaganda_office=True,
            is_aggressor_in_any_active_war=True,
        )
        assert delta == expected, (
            f"Lopsided aggressor with PO: expected {expected}, got {delta}"
        )

    # --- PO cap does NOT apply during war_pending, only war ---
    # The pure function itself receives pre-resolved flags, so we test the
    # flag interpretation: when war_pending is the status, the caller must
    # NOT pass is_aggressor_in_any_active_war=True.
    # We verify this via the tick-level integration test below.

    def test_holding_fleet_territory_no_po_baseline(self):
        """Holding fleet on defender territory: +6 (holding) + 0 (occupied decay) + war penalty."""
        delta = compute_territory_dissent_delta(
            at_war=True,
            is_aggressor=False,
            is_lopsided_aggressor=False,
            fleet_status="holding",
            has_propaganda_office=False,
            is_aggressor_in_any_active_war=False,
        )
        expected = DISSENT_WAR_DEFENDER + DISSENT_FLEET_HOLDING + DISSENT_DECAY_OCCUPIED
        assert delta == expected


# ===========================================================================
# Part 4 — Tick-level integration tests for lopsided dissent
# ===========================================================================

class TestLopsidedDissentTick:
    """
    Full run_tick() integration tests that verify lopsided wars produce the
    correct per-tick dissent increment on the aggressor's territories.
    """

    def test_lopsided_war_aggressor_accrues_multiplied_dissent(self, db: Session):
        """
        Aggressor in a lopsided war accrues DISSENT_WAR_AGGRESSOR * DISSENT_LOPSIDED_MULTIPLIER
        (rounded to int) + DISSENT_DECAY_WAR per tick, not the flat DISSENT_WAR_AGGRESSOR.
        """
        p_agg = _player(db, "agg_tick_lopsided")
        p_def = _player(db, "def_tick_lopsided")
        n_agg = _nation(db, p_agg.id)
        n_def = _nation(db, p_def.id)
        t_agg = _territory(db, "20,0", n_agg.id)
        _dissent_row(db, t_agg.id, 20)
        # Mark the war as lopsided directly (as if the declaration service already evaluated it)
        _declare_war(db, n_agg, n_def, declared_by=n_agg, is_lopsided=True)

        _run_tick(db)

        lopsided_war_contribution = round(DISSENT_WAR_AGGRESSOR * DISSENT_LOPSIDED_MULTIPLIER)
        expected = 20 + lopsided_war_contribution + DISSENT_DECAY_WAR
        assert _get_dissent(db, t_agg.id) == expected, (
            f"Lopsided aggressor: expected dissent {expected}, "
            f"got {_get_dissent(db, t_agg.id)}"
        )

    def test_non_lopsided_war_aggressor_accrues_flat_dissent(self, db: Session):
        """
        Aggressor in a non-lopsided war accrues the flat DISSENT_WAR_AGGRESSOR,
        not the multiplied value.
        """
        p_agg = _player(db, "agg_tick_flat")
        p_def = _player(db, "def_tick_flat")
        n_agg = _nation(db, p_agg.id)
        n_def = _nation(db, p_def.id)
        t_agg = _territory(db, "21,0", n_agg.id)
        _dissent_row(db, t_agg.id, 20)
        # is_lopsided defaults to False
        _declare_war(db, n_agg, n_def, declared_by=n_agg, is_lopsided=False)

        _run_tick(db)

        expected = 20 + DISSENT_WAR_AGGRESSOR + DISSENT_DECAY_WAR
        assert _get_dissent(db, t_agg.id) == expected, (
            f"Non-lopsided aggressor: expected dissent {expected}, "
            f"got {_get_dissent(db, t_agg.id)}"
        )

    def test_lopsided_war_defender_dissent_unaffected(self, db: Session):
        """
        In a lopsided war, the DEFENDER's dissent tick is unchanged — still
        DISSENT_WAR_DEFENDER + DISSENT_DECAY_WAR (= 0, stable).
        """
        p_agg = _player(db, "agg_def_unchanged")
        p_def = _player(db, "def_def_unchanged")
        n_agg = _nation(db, p_agg.id)
        n_def = _nation(db, p_def.id)
        t_def = _territory(db, "22,0", n_def.id)
        _dissent_row(db, t_def.id, 30)
        _declare_war(db, n_agg, n_def, declared_by=n_agg, is_lopsided=True)

        _run_tick(db)

        # defender stable: +2 + (-2) = 0
        expected = 30 + DISSENT_WAR_DEFENDER + DISSENT_DECAY_WAR
        assert _get_dissent(db, t_def.id) == expected, (
            f"Lopsided war defender: expected dissent {expected}, "
            f"got {_get_dissent(db, t_def.id)}"
        )

    def test_lopsided_and_non_lopsided_wars_max_cap_uses_lopsided_value(self, db: Session):
        """
        A nation is aggressor in two wars: one lopsided, one not.
        The multi-war MAX cap must pick up the lopsided (higher) value.
        delta = max(lopsided_war, normal_war) + DISSENT_DECAY_WAR
        """
        p_agg = _player(db, "agg_two_wars")
        p_d1  = _player(db, "def_two_wars_1")
        p_d2  = _player(db, "def_two_wars_2")
        n_agg = _nation(db, p_agg.id)
        n_d1  = _nation(db, p_d1.id)
        n_d2  = _nation(db, p_d2.id)
        t_agg = _territory(db, "23,0", n_agg.id)
        _dissent_row(db, t_agg.id, 20)
        # War 1: lopsided → multiplied penalty
        _declare_war(db, n_agg, n_d1, declared_by=n_agg, is_lopsided=True)
        # War 2: non-lopsided → flat penalty
        _declare_war(db, n_agg, n_d2, declared_by=n_agg, is_lopsided=False)

        _run_tick(db)

        lopsided_contribution = round(DISSENT_WAR_AGGRESSOR * DISSENT_LOPSIDED_MULTIPLIER)
        flat_contribution = DISSENT_WAR_AGGRESSOR
        expected = 20 + max(lopsided_contribution, flat_contribution) + DISSENT_DECAY_WAR
        assert _get_dissent(db, t_agg.id) == expected, (
            f"Two wars (lopsided + normal): expected dissent {expected}, "
            f"got {_get_dissent(db, t_agg.id)}"
        )


# ===========================================================================
# Part 5 — Tick-level integration tests for PO aggressor cap
# ===========================================================================

class TestPOAggressorCapTick:
    """
    Full run_tick() integration tests verifying that the PO bonus is capped
    for aggressor nations and uncapped for defenders.
    """

    def test_aggressor_territory_with_po_uses_aggressor_cap(self, db: Session):
        """
        Aggressor nation at war with PO on their territory.
        PO bonus = DISSENT_OFFICE_BONUS_AGGRESSOR (1) not DISSENT_OFFICE_BONUS_NORMAL (2).
        delta = DISSENT_WAR_AGGRESSOR + DISSENT_DECAY_WAR - DISSENT_OFFICE_BONUS_AGGRESSOR
        """
        p_agg = _player(db, "po_agg")
        p_def = _player(db, "po_def")
        n_agg = _nation(db, p_agg.id)
        n_def = _nation(db, p_def.id)
        t_agg = _territory(db, "30,0", n_agg.id)
        _dissent_row(db, t_agg.id, 30)
        _propaganda_office(db, t_agg.id)
        _declare_war(db, n_agg, n_def, declared_by=n_agg)

        _run_tick(db)

        expected = 30 + DISSENT_WAR_AGGRESSOR + DISSENT_DECAY_WAR - DISSENT_OFFICE_BONUS_AGGRESSOR
        assert _get_dissent(db, t_agg.id) == expected, (
            f"Aggressor with PO: expected {expected}, got {_get_dissent(db, t_agg.id)}"
        )

    def test_defender_territory_with_po_uses_normal_bonus(self, db: Session):
        """
        Defender nation at war with PO on their territory.
        PO bonus = DISSENT_OFFICE_BONUS_NORMAL (2), not the aggressor cap.
        delta = DISSENT_WAR_DEFENDER + DISSENT_DECAY_WAR - DISSENT_OFFICE_BONUS_NORMAL
        """
        p_agg = _player(db, "po_agg2")
        p_def = _player(db, "po_def2")
        n_agg = _nation(db, p_agg.id)
        n_def = _nation(db, p_def.id)
        t_def = _territory(db, "31,0", n_def.id)
        _dissent_row(db, t_def.id, 30)
        _propaganda_office(db, t_def.id)
        _declare_war(db, n_agg, n_def, declared_by=n_agg)

        _run_tick(db)

        expected = 30 + DISSENT_WAR_DEFENDER + DISSENT_DECAY_WAR - DISSENT_OFFICE_BONUS_NORMAL
        assert _get_dissent(db, t_def.id) == expected, (
            f"Defender with PO: expected {expected}, got {_get_dissent(db, t_def.id)}"
        )

    def test_aggressor_po_cap_only_during_war_not_war_pending(self, db: Session):
        """
        The aggressor PO cap applies only when diplomacy.status == 'war'.
        During 'war_pending' the aggressor is not yet in active war, so the cap
        must NOT apply — PO bonus should be DISSENT_OFFICE_BONUS_NORMAL.
        """
        p_agg = _player(db, "po_pending_agg")
        p_def = _player(db, "po_pending_def")
        n_agg = _nation(db, p_agg.id)
        n_def = _nation(db, p_def.id)
        t_agg = _territory(db, "32,0", n_agg.id)
        _dissent_row(db, t_agg.id, 30)
        _propaganda_office(db, t_agg.id)
        # war_pending: not yet active war
        _declare_war(db, n_agg, n_def, declared_by=n_agg, status="war_pending")

        _run_tick(db)

        # During war_pending the aggressor is treated as at peace for dissent purposes.
        # PO uses DISSENT_OFFICE_BONUS_NORMAL (not capped).
        expected_at_peace_normal_po = 30 + DISSENT_DECAY_PEACE - DISSENT_OFFICE_BONUS_NORMAL
        assert _get_dissent(db, t_agg.id) == expected_at_peace_normal_po, (
            f"war_pending should not trigger PO cap. "
            f"Expected {expected_at_peace_normal_po}, got {_get_dissent(db, t_agg.id)}"
        )

    def test_aggressor_cap_does_not_apply_after_war_ends(self, db: Session):
        """
        After a war ends (status == 'neutral'), the nation is no longer an active
        aggressor and its PO bonus reverts to DISSENT_OFFICE_BONUS_NORMAL.
        """
        p1 = _player(db, "po_post_war1")
        p2 = _player(db, "po_post_war2")
        n1 = _nation(db, p1.id)
        n2 = _nation(db, p2.id)
        t1 = _territory(db, "33,0", n1.id)
        _dissent_row(db, t1.id, 30)
        _propaganda_office(db, t1.id)
        # No active war — peace
        db.flush()

        _run_tick(db)

        # At peace with PO: uses normal bonus
        expected = 30 + DISSENT_DECAY_PEACE - DISSENT_OFFICE_BONUS_NORMAL
        assert _get_dissent(db, t1.id) == expected

    def test_aggressor_po_cap_does_not_affect_occupied_bonus_tier(self, db: Session):
        """
        The aggressor PO cap is about DISSENT_OFFICE_BONUS_NORMAL vs
        DISSENT_OFFICE_BONUS_AGGRESSOR.  When a fleet is occupying the
        territory (fleet_status in holding/engaged), the DISSENT_OFFICE_BONUS_OCCUPIED
        tier kicks in instead — the aggressor cap test should not apply there since
        occupied territories belong to the DEFENDER, not the aggressor.

        This test confirms the occupied PO tier is unaffected: a defending territory
        with a holding fleet and PO still uses DISSENT_OFFICE_BONUS_OCCUPIED.
        """
        p_agg = _player(db, "po_occ_agg")
        p_def = _player(db, "po_occ_def")
        n_agg = _nation(db, p_agg.id)
        n_def = _nation(db, p_def.id)
        t_def = _territory(db, "34,0", n_def.id)
        _dissent_row(db, t_def.id, 10)
        _propaganda_office(db, t_def.id)
        _declare_war(db, n_agg, n_def, declared_by=n_agg)
        # Aggressor's fleet holding on the defender's territory
        _fleet(db, n_agg.id, t_def.id, units=50, status="holding", dest_id=t_def.id)

        _run_tick(db)

        # Defender territory + holding fleet + PO:
        # +2 (defender) + 6 (holding) + 0 (occupied decay) - 3 (occupied PO) = +5
        expected = 10 + DISSENT_WAR_DEFENDER + DISSENT_FLEET_HOLDING + DISSENT_DECAY_OCCUPIED - DISSENT_OFFICE_BONUS_OCCUPIED
        assert _get_dissent(db, t_def.id) == expected, (
            f"Occupied defender with PO: expected {expected}, got {_get_dissent(db, t_def.id)}"
        )
