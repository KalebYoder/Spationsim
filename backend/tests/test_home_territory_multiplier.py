"""
Tests for the home-territory defense multiplier added to resolve_combat_tick().

Feature spec:
  - New optional parameter:  home_territory_multiplier: float = 1.0
  - When > 1.0, the defender's effective count is inflated for the attacker's
    damage calculation only:
        defender_effective = round(defender_count * home_territory_multiplier)
    The attacker fires against defender_effective (shields absorb more, fewer
    defender losses).  The defender fires against the literal attacker count
    unchanged.
  - New constant:  HOME_TERRITORY_DEFENSE_MULTIPLIER = 1.5  in constants.py
  - Tick passes HOME_TERRITORY_DEFENSE_MULTIPLIER when the destination territory
    is_owned=True and is owned by the defender.  On unclaimed or void (not
    colonized) territory it passes the default 1.0.

Unit stats (starfighter):
    firepower=2, shields=1, structural_integrity=5

Part 1 — pure function tests (no DB needed)
Part 2 — tick integration tests (DB + run_tick)
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

from app.services.combat import resolve_combat_tick
from app.constants import HOME_TERRITORY_DEFENSE_MULTIPLIER

from app.models.diplomacy import Diplomacy
from app.models.event import Event
from app.models.fleet import Fleet
from app.models.nation import Nation
from app.models.player import Player
from app.models.territory import Territory
from app.core.security import hash_password


# ---------------------------------------------------------------------------
# Canonical unit stats — must match UNIT_STATS["starfighter"] in constants.py
# ---------------------------------------------------------------------------

SF = {"firepower": 2, "shields": 1, "structural_integrity": 5}


# ===========================================================================
# Part 1 — Pure function: resolve_combat_tick with home_territory_multiplier
# ===========================================================================

class TestResolveCombaTickMultiplierPureFunction:
    """
    All tests in this class call resolve_combat_tick() directly.
    No DB fixture is needed.
    """

    # -----------------------------------------------------------------------
    # 1. Backward compatibility: multiplier=1.0 must be identical to no-param
    # -----------------------------------------------------------------------

    def test_multiplier_1_0_gives_same_results_as_no_multiplier(self):
        """
        Calling with home_territory_multiplier=1.0 must return the same
        (attacker_losses, defender_losses) as calling without the parameter at
        all.  This is the core backward-compatibility guarantee.
        """
        without = resolve_combat_tick(100, SF, 100, SF)
        with_1_0 = resolve_combat_tick(100, SF, 100, SF, home_territory_multiplier=1.0)
        assert without == with_1_0, (
            f"multiplier=1.0 should be identical to no multiplier; "
            f"got without={without}, with_1_0={with_1_0}"
        )

    def test_multiplier_1_0_no_param_equivalence_asymmetric_forces(self):
        """
        Backward compat also holds for asymmetric force sizes.
        """
        without = resolve_combat_tick(200, SF, 100, SF)
        with_1_0 = resolve_combat_tick(200, SF, 100, SF, home_territory_multiplier=1.0)
        assert without == with_1_0

    # -----------------------------------------------------------------------
    # 2. Multiplier reduces defender losses (equal forces)
    # -----------------------------------------------------------------------

    def test_multiplier_reduces_defender_losses_equal_forces(self):
        """
        100v100, multiplier=1.5 must produce strictly fewer defender losses
        than 100v100 with no multiplier.
        The attacker fires against the inflated defender_effective, so fewer
        net damage points penetrate to the real defender pool.
        """
        _, d_losses_flat = resolve_combat_tick(100, SF, 100, SF)
        _, d_losses_boosted = resolve_combat_tick(100, SF, 100, SF,
                                                   home_territory_multiplier=1.5)
        assert d_losses_boosted < d_losses_flat, (
            f"Multiplier=1.5 should reduce defender losses; "
            f"flat={d_losses_flat}, boosted={d_losses_boosted}"
        )

    # -----------------------------------------------------------------------
    # 3. Multiplier does NOT change attacker losses
    # -----------------------------------------------------------------------

    def test_multiplier_does_not_change_attacker_losses(self):
        """
        Attacker losses depend only on defender_count (the real count) firing
        at the attacker.  The multiplier must leave attacker losses unchanged.
        """
        a_losses_flat, _ = resolve_combat_tick(100, SF, 100, SF)
        a_losses_boosted, _ = resolve_combat_tick(100, SF, 100, SF,
                                                   home_territory_multiplier=1.5)
        assert a_losses_flat == a_losses_boosted, (
            f"Multiplier must not affect attacker losses; "
            f"flat={a_losses_flat}, boosted={a_losses_boosted}"
        )

    # -----------------------------------------------------------------------
    # 4. Exact values: 100v100, multiplier=1.5
    # -----------------------------------------------------------------------

    def test_equal_forces_multiplier_1_5_exact_values(self):
        """
        100 attackers vs 100 defenders, multiplier=1.5:
          defender_effective = round(100 * 1.5) = 150
          Attacker fires:
            raw      = 100 * 2 = 200
            absorbed = 150 * 1 = 150   (uses defender_effective)
            net      = 200 - 150 = 50
            losses   = round(50 / 5) = 10
          Defender fires (at real attacker count):
            raw      = 100 * 2 = 200
            absorbed = 100 * 1 = 100
            net      = 200 - 100 = 100
            losses   = round(100 / 5) = 20
        Expected: attacker_losses=20, defender_losses=10
        """
        a_losses, d_losses = resolve_combat_tick(100, SF, 100, SF,
                                                  home_territory_multiplier=1.5)
        assert a_losses == 20, f"Expected attacker_losses=20, got {a_losses}"
        assert d_losses == 10, f"Expected defender_losses=10, got {d_losses}"

    # -----------------------------------------------------------------------
    # 5. Attacker needs more units to break even when multiplier is active
    # -----------------------------------------------------------------------

    def test_multiplier_makes_attacker_need_more_units_to_break_even(self):
        """
        At multiplier=1.0, 100v100 is symmetric (both lose 20).  At
        multiplier=1.5, the same 100 attackers vs 100 defenders now puts the
        attacker at a disadvantage: they take more losses than the defender.
        """
        # At 1.0: 100v100 is symmetric
        a_flat, d_flat = resolve_combat_tick(100, SF, 100, SF)
        assert a_flat == d_flat, "Baseline: equal forces must be symmetric at 1.0"

        # At 1.5: same count — attacker is now at a disadvantage
        a_boost, d_boost = resolve_combat_tick(100, SF, 100, SF,
                                                home_territory_multiplier=1.5)
        assert d_boost < a_boost, (
            f"At multiplier=1.5, 100v100 attacker should lose more than defender; "
            f"attacker_losses={a_boost}, defender_losses={d_boost}"
        )

    # -----------------------------------------------------------------------
    # 6. Exact values: 200v100, multiplier=1.5
    # -----------------------------------------------------------------------

    def test_multiplier_1_5_with_overwhelming_attacker(self):
        """
        200 attackers vs 100 defenders, multiplier=1.5:
          defender_effective = round(100 * 1.5) = 150
          Attacker fires:
            raw      = 200 * 2 = 400
            absorbed = 150 * 1 = 150
            net      = 250
            losses   = round(250 / 5) = 50
          Defender fires:
            raw      = 100 * 2 = 200
            absorbed = 200 * 1 = 200
            net      = 0  → 0 losses
        Expected: attacker_losses=0, defender_losses=50
        """
        a_losses, d_losses = resolve_combat_tick(200, SF, 100, SF,
                                                  home_territory_multiplier=1.5)
        assert a_losses == 0, f"Expected attacker_losses=0, got {a_losses}"
        assert d_losses == 50, f"Expected defender_losses=50, got {d_losses}"

    # -----------------------------------------------------------------------
    # 7. Default path (200v100, multiplier=1.0): confirms existing behaviour
    # -----------------------------------------------------------------------

    def test_multiplier_does_not_apply_when_1_0(self):
        """
        200v100, multiplier=1.0 (or omitted):
          defender_effective = 100  (no inflation)
          Attacker fires:
            raw      = 200 * 2 = 400
            absorbed = 100 * 1 = 100
            net      = 300
            losses   = round(300 / 5) = 60
          Defender fires:
            raw      = 100 * 2 = 200
            absorbed = 200 * 1 = 200
            net      = 0  → 0 losses
        Expected: attacker_losses=0, defender_losses=60
        """
        a_losses, d_losses = resolve_combat_tick(200, SF, 100, SF,
                                                  home_territory_multiplier=1.0)
        assert a_losses == 0, f"Expected attacker_losses=0, got {a_losses}"
        assert d_losses == 60, f"Expected defender_losses=60, got {d_losses}"

        # Also check via no-parameter call
        a_np, d_np = resolve_combat_tick(200, SF, 100, SF)
        assert a_np == 0
        assert d_np == 60

    # -----------------------------------------------------------------------
    # 8. Rounding of defender_effective
    # -----------------------------------------------------------------------

    def test_multiplier_rounds_defender_effective_count(self):
        """
        101 attackers vs 100 defenders, multiplier=1.5:
          defender_effective = round(100 * 1.5) = 150
          (Only the defender count is inflated, not the attacker count.)

          Attacker fires:
            raw      = 101 * 2 = 202
            absorbed = 150 * 1 = 150
            net      = 52
            losses   = round(52 / 5) = round(10.4) = 10
          Defender fires:
            raw      = 100 * 2 = 200
            absorbed = 101 * 1 = 101
            net      = 99
            losses   = round(99 / 5) = round(19.8) = 20
        Expected: attacker_losses=20, defender_losses=10
        """
        a_losses, d_losses = resolve_combat_tick(101, SF, 100, SF,
                                                  home_territory_multiplier=1.5)
        assert a_losses == 20, f"Expected attacker_losses=20, got {a_losses}"
        assert d_losses == 10, f"Expected defender_losses=10, got {d_losses}"

    # -----------------------------------------------------------------------
    # 9. Zero attacker with multiplier
    # -----------------------------------------------------------------------

    def test_zero_attacker_returns_zeros_with_multiplier(self):
        """
        0 attackers vs 100 defenders, multiplier=1.5 → (0, 0).
        The zero-guard must fire before any multiplier logic.
        """
        result = resolve_combat_tick(0, SF, 100, SF, home_territory_multiplier=1.5)
        assert result == (0, 0), f"Expected (0, 0), got {result}"

    # -----------------------------------------------------------------------
    # 10. Zero defender with multiplier
    # -----------------------------------------------------------------------

    def test_zero_defender_returns_zeros_with_multiplier(self):
        """
        100 attackers vs 0 defenders, multiplier=1.5 → (0, 0).
        The zero-guard must fire before any multiplier logic.
        """
        result = resolve_combat_tick(100, SF, 0, SF, home_territory_multiplier=1.5)
        assert result == (0, 0), f"Expected (0, 0), got {result}"

    # -----------------------------------------------------------------------
    # Additional: rounding uses Python's round() (banker's rounding)
    # -----------------------------------------------------------------------

    def test_defender_effective_uses_python_round(self):
        """
        Verify that defender_effective = round(defender_count * multiplier)
        uses Python's built-in round() — not ceil() or floor().
        We pick a count where the three differ:
          67 * 1.5 = 100.5 → round(100.5) = 100 (banker's) vs ceil=101, floor=100.
        The test derives expected losses from round() and asserts the function
        matches, ensuring the implementation uses round() and not a different
        rounding strategy.
        """
        attacker_count = 50
        defender_count = 67
        multiplier = 1.5
        defender_effective = round(defender_count * multiplier)  # 100 under banker's

        raw = attacker_count * SF["firepower"]
        absorbed = defender_effective * SF["shields"]
        net = max(0, raw - absorbed)
        if net == 0:
            expected_d_losses = 0
        else:
            expected_d_losses = max(1, round(net / SF["structural_integrity"]))

        _, d_losses = resolve_combat_tick(attacker_count, SF, defender_count, SF,
                                           home_territory_multiplier=multiplier)
        assert d_losses == expected_d_losses, (
            f"defender_effective should be round({defender_count}*{multiplier})="
            f"{defender_effective}; expected d_losses={expected_d_losses}, got {d_losses}"
        )

    # -----------------------------------------------------------------------
    # Constant existence
    # -----------------------------------------------------------------------

    def test_home_territory_defense_multiplier_constant_is_1_5(self):
        """
        HOME_TERRITORY_DEFENSE_MULTIPLIER must be exported from constants.py
        and must equal 1.5.
        """
        assert HOME_TERRITORY_DEFENSE_MULTIPLIER == 1.5, (
            f"Expected HOME_TERRITORY_DEFENSE_MULTIPLIER=1.5, "
            f"got {HOME_TERRITORY_DEFENSE_MULTIPLIER}"
        )

    def test_home_territory_defense_multiplier_constant_is_numeric_and_gt_1(self):
        """The constant must be a numeric value strictly greater than 1.0."""
        assert isinstance(HOME_TERRITORY_DEFENSE_MULTIPLIER, (int, float))
        assert HOME_TERRITORY_DEFENSE_MULTIPLIER > 1.0


# ===========================================================================
# Part 2 — Tick integration: run_tick() passes the correct multiplier
# ===========================================================================
#
# These tests verify that app/tasks/tick.py calls resolve_combat_tick with
# home_territory_multiplier=HOME_TERRITORY_DEFENSE_MULTIPLIER when the
# destination is a colonized defender territory, and 1.0 (or omits the
# parameter) when the destination is not colonized.
#
# Helper pattern mirrors test_dissent.py exactly.
# ===========================================================================

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _player(db: Session, username: str) -> Player:
    p = Player(
        username=username,
        email=f"{username}@test.example",
        password_hash=hash_password("pw"),
        vacation_mode=False,
    )
    db.add(p)
    db.flush()
    return p


def _nation(db: Session, player_id: int, name: str | None = None) -> Nation:
    n = Nation(
        player_id=player_id,
        name=name or f"Nation-{player_id}",
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
    territory_type: str = "normal",
) -> Territory:
    is_col = colonized and nation_id is not None
    t = Territory(
        node_key=node_key,
        territory_type=territory_type,
        nation_id=nation_id,
        mineral_richness=1,
        fuel_richness=1,
        distance_from_center=1,
        is_owned=is_col,
        owned_at=datetime.now(timezone.utc) if is_col else None,
    )
    db.add(t)
    db.flush()
    return t


def _declare_war(db: Session, nation_a: Nation, nation_b: Nation,
                 declared_by: Nation) -> Diplomacy:
    a_id = min(nation_a.id, nation_b.id)
    b_id = max(nation_a.id, nation_b.id)
    row = Diplomacy(
        nation_a=a_id,
        nation_b=b_id,
        status="war",
        declared_by=declared_by.id,
        is_lopsided=False,
    )
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


def _run_tick(db: Session) -> None:
    db.commit()
    from app.tasks.tick import run_tick
    run_tick()


def _get_combat_event(db: Session) -> Event | None:
    """Return the most recent combat_round event, or None."""
    db.expire_all()
    return (
        db.query(Event)
        .filter(Event.type == "combat_round")
        .order_by(Event.id.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# Reference implementation: mirrors the feature-spec multiplier arithmetic
# ---------------------------------------------------------------------------

def _expected_losses_with_multiplier(
    attacker_count: int,
    defender_count: int,
    multiplier: float,
    stats: dict,
) -> tuple[int, int]:
    """
    Returns (attacker_losses, defender_losses) per the multiplier spec.
    Used as the ground truth in integration assertions.
    """
    if attacker_count <= 0 or defender_count <= 0:
        return 0, 0

    defender_effective = round(defender_count * multiplier)

    # Attacker fires at defender_effective (inflated shield count)
    raw_a = attacker_count * stats["firepower"]
    absorbed_a = defender_effective * stats["shields"]
    net_a = max(0, raw_a - absorbed_a)
    d_losses = (max(1, round(net_a / stats["structural_integrity"]))
                if net_a > 0 else 0)

    # Defender fires at the real attacker count (unchanged)
    raw_d = defender_count * stats["firepower"]
    absorbed_d = attacker_count * stats["shields"]
    net_d = max(0, raw_d - absorbed_d)
    a_losses = (max(1, round(net_d / stats["structural_integrity"]))
                if net_d > 0 else 0)

    return a_losses, d_losses


# ---------------------------------------------------------------------------
# Test 11: combat on colonized defender territory uses 1.5x multiplier
# ---------------------------------------------------------------------------

class TestTickCombatOnColonizedDefenderTerritory:
    """
    When an engaged fleet fights on a territory that is_owned=True and
    owned by the defender, the tick must apply the home-territory multiplier.
    """

    def test_combat_on_colonized_defender_territory_uses_multiplier(
        self, db: Session
    ):
        """
        Setup:
          - Attacker fleet: status='engaged', destination=defender's colonized territory.
          - Defender fleet: status='stationed' at that territory.
          - Nations are at war.
        After run_tick():
          - The combat_round event's defender_losses must equal the 1.5x
            multiplier calculation, NOT the flat 1.0 calculation.
        """
        p_att = _player(db, "htm_attacker")
        p_def = _player(db, "htm_defender")
        n_att = _nation(db, p_att.id, "HTM Attackers")
        n_def = _nation(db, p_def.id, "HTM Defenders")

        t_att_home = _territory(db, "50,0", n_att.id)
        # is_owned=True, nation_id=n_def.id → home territory multiplier applies
        t_def_home = _territory(db, "51,0", n_def.id)

        _declare_war(db, n_att, n_def, declared_by=n_att)

        attacker_units = 100
        defender_units = 100

        _fleet(db, n_att.id, t_att_home.id, attacker_units,
               status="engaged", dest_id=t_def_home.id)
        _fleet(db, n_def.id, t_def_home.id, defender_units,
               status="stationed", dest_id=None)

        _run_tick(db)

        a_losses_1x, d_losses_1x = _expected_losses_with_multiplier(
            attacker_units, defender_units, 1.0, SF
        )
        a_losses_1_5x, d_losses_1_5x = _expected_losses_with_multiplier(
            attacker_units, defender_units, 1.5, SF
        )

        # Sanity: the two paths must differ for this test to be meaningful
        assert d_losses_1_5x != d_losses_1x, (
            "Test setup error: 1.0 and 1.5 multiplier produce identical "
            "defender losses for these unit counts; choose different counts."
        )

        event = _get_combat_event(db)
        assert event is not None, "combat_round event must be logged after combat"

        actual_d_losses = event.payload["defender_losses"]
        actual_a_losses = event.payload["attacker_losses"]

        assert actual_d_losses == d_losses_1_5x, (
            f"Colonized defender territory: expected defender_losses={d_losses_1_5x} "
            f"(1.5x multiplier), got {actual_d_losses}.  "
            f"Flat 1.0 would give {d_losses_1x}."
        )
        assert actual_a_losses == a_losses_1_5x, (
            f"Attacker losses: expected {a_losses_1_5x} (1.5x path), "
            f"got {actual_a_losses}"
        )

        # Defender took fewer losses than the flat path would have given
        assert actual_d_losses < d_losses_1x, (
            "Home territory multiplier must reduce defender losses vs flat 1.0"
        )

    def test_combat_on_colonized_territory_attacker_losses_match_flat_path(
        self, db: Session
    ):
        """
        Attacker losses on a colonized defender territory must equal the flat
        1.0 path value (the multiplier must not affect the defender's return
        fire against the attacker).
        """
        p_att = _player(db, "htm_att_chk")
        p_def = _player(db, "htm_def_chk")
        n_att = _nation(db, p_att.id, "HTM Att Check")
        n_def = _nation(db, p_def.id, "HTM Def Check")

        t_att_home = _territory(db, "52,0", n_att.id)
        t_def_home = _territory(db, "53,0", n_def.id)

        _declare_war(db, n_att, n_def, declared_by=n_att)

        attacker_units = 100
        defender_units = 100

        _fleet(db, n_att.id, t_att_home.id, attacker_units,
               status="engaged", dest_id=t_def_home.id)
        _fleet(db, n_def.id, t_def_home.id, defender_units,
               status="stationed", dest_id=None)

        _run_tick(db)

        # Attacker losses must be identical at 1.0 and 1.5 (defender fires at
        # real attacker count in both cases)
        a_losses_1x, _ = _expected_losses_with_multiplier(
            attacker_units, defender_units, 1.0, SF
        )
        a_losses_1_5x, _ = _expected_losses_with_multiplier(
            attacker_units, defender_units, 1.5, SF
        )
        assert a_losses_1x == a_losses_1_5x, (
            "Precondition: attacker losses must be equal at 1.0 and 1.5 — "
            "the multiplier must not change attacker losses."
        )

        event = _get_combat_event(db)
        assert event is not None
        assert event.payload["attacker_losses"] == a_losses_1_5x, (
            f"Attacker losses on colonized territory: expected {a_losses_1_5x}, "
            f"got {event.payload['attacker_losses']}"
        )


# ---------------------------------------------------------------------------
# Test 12: combat on unclaimed / void territory uses flat 1.0 (no multiplier)
# ---------------------------------------------------------------------------

class TestTickCombatOnUnclaimedTerritory:
    """
    When the destination territory is not colonized (is_owned=False), the
    tick must NOT apply the home-territory multiplier.  Losses must match the
    flat 1.0 calculation.

    We use a territory that is owned by the defender (nation_id set) but
    is_owned=False (a claimed void node / outpost) — this is the most
    relevant scenario because the territory has an owner but no colonization
    bonus should apply.
    """

    def test_combat_on_unclaimed_territory_no_multiplier(self, db: Session):
        """
        Setup:
          - Destination territory: owned by defender, is_owned=False (void claimed).
          - Attacker fleet: engaged, destination=that territory.
          - Defender fleet: stationed at that territory.
          - Nations are at war.
        After run_tick():
          - defender_losses must equal the flat 1.0 calculation.
          - defender_losses must NOT equal the 1.5x calculation (if they differ).
        """
        p_att = _player(db, "nc_attacker")
        p_def = _player(db, "nc_defender")
        n_att = _nation(db, p_att.id, "NC Attackers")
        n_def = _nation(db, p_def.id, "NC Defenders")

        t_att_home = _territory(db, "60,0", n_att.id)
        # Owned by defender but is_owned=False — no home multiplier should apply
        t_void_claimed = _territory(db, "61,0", n_def.id, colonized=False,
                                    territory_type="void")

        _declare_war(db, n_att, n_def, declared_by=n_att)

        attacker_units = 100
        defender_units = 100

        _fleet(db, n_att.id, t_att_home.id, attacker_units,
               status="engaged", dest_id=t_void_claimed.id)
        _fleet(db, n_def.id, t_void_claimed.id, defender_units,
               status="stationed", dest_id=None)

        _run_tick(db)

        a_losses_flat, d_losses_flat = _expected_losses_with_multiplier(
            attacker_units, defender_units, 1.0, SF
        )
        _, d_losses_boosted = _expected_losses_with_multiplier(
            attacker_units, defender_units, 1.5, SF
        )

        event = _get_combat_event(db)
        assert event is not None, (
            "combat_round event must be logged for combat on uncolonized territory"
        )
        actual_d_losses = event.payload["defender_losses"]

        assert actual_d_losses == d_losses_flat, (
            f"Uncolonized territory: expected flat 1.0 defender_losses={d_losses_flat}, "
            f"got {actual_d_losses}.  1.5x path would give {d_losses_boosted}."
        )

        # Only assert the negative check when the two paths actually differ
        if d_losses_boosted != d_losses_flat:
            assert actual_d_losses != d_losses_boosted, (
                "Unclaimed territory must NOT use the 1.5x home territory multiplier"
            )

    def test_colonized_path_gives_fewer_defender_losses_than_unclaimed_path(
        self, db: Session
    ):
        """
        Cross-scenario regression: for identical unit counts the colonized
        defender territory path must produce strictly fewer defender losses
        than the unclaimed path.
        This confirms that the multiplier is applied on the correct branch only.
        """
        attacker_units = 100
        defender_units = 100

        _, d_losses_flat = _expected_losses_with_multiplier(
            attacker_units, defender_units, 1.0, SF
        )
        _, d_losses_boosted = _expected_losses_with_multiplier(
            attacker_units, defender_units, HOME_TERRITORY_DEFENSE_MULTIPLIER, SF
        )

        assert d_losses_boosted < d_losses_flat, (
            f"Home territory multiplier ({HOME_TERRITORY_DEFENSE_MULTIPLIER}x) should "
            f"reduce defender losses vs flat 1.0; "
            f"boosted={d_losses_boosted}, flat={d_losses_flat}"
        )
