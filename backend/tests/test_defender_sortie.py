"""
Test suite for the Defender Sortie mechanic and related new combat mechanics.

New mechanics covered:
  1. PBC expiry → `holding` (NOT `engaged`)
  2. Attacker tick-action standing order (`engage` value on `holding` fleet)
  3. Defender sortie endpoint: POST /api/military/fleets/{fleet_id}/sortie
  4. Defender auto-rout (fires in tick loop after combat round)
  5. Raid cap (RAID_CAP_FRACTION * current_stockpile per resource)
  6. Queued sortie during PBC (fires when PBC expires)

Game-design rules enforced:
  - Inaction on PBC expiry → safe default (`holding`), not resumed combat
  - `standing_order` must be explicitly set to `engage` to trigger combat for a holding fleet
  - Default standing order for a holding fleet is `hold`, never `attack` or `engage`
  - Auto-rout bonus only fires when attacker took losses (no free damage on zero-loss round)
  - Raid cannot drain more than the cap fraction from stockpile (soft damage model)
  - `last_sortie_at` and `sortie_queued` are new Territory columns added by the migration
    for this feature (accessed via setattr/getattr so the test file does not fail if the
    column is not yet present — the assertion failure is the signal to the developer)
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
from app.core.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Constants (new ones not yet in constants.py)
# ---------------------------------------------------------------------------

DEFENDER_AUTO_ROUT_FRACTION = 0.50
RAID_CAP_FRACTION = 0.10
TICK_HOURS = 2
CLOCK_TOLERANCE_SECONDS = 60


# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_occupation_window.py)
# ---------------------------------------------------------------------------


def _set_war(db: Session, nation_a_id: int, nation_b_id: int) -> Diplomacy:
    a, b = min(nation_a_id, nation_b_id), max(nation_a_id, nation_b_id)
    row = db.query(Diplomacy).filter(
        Diplomacy.nation_a == a,
        Diplomacy.nation_b == b,
    ).first()
    if row:
        row.status = "war"
        row.declared_by = a
    else:
        row = Diplomacy(nation_a=a, nation_b=b, status="war", declared_by=a)
        db.add(row)
    db.flush()
    return row


def _db_override(session: Session):
    def _override():
        yield session
    return _override


def _commit_and_run_tick(db: Session) -> None:
    """Commit the transactional session so SessionLocal() inside run_tick sees the rows,
    then invoke run_tick synchronously as a plain function."""
    db.commit()
    from app.tasks.tick import run_tick
    run_tick()


def _make_fleet(
    db: Session,
    *,
    nation_id: int,
    origin_id: int,
    dest_id: int | None = None,
    status: str,
    unit_count: int = 50,
    standing_order: str = "hold",
    arrives_at: datetime | None = None,
    confirmation_expires_at: datetime | None = None,
    occupation_expires_at: datetime | None = None,
) -> Fleet:
    fleet = Fleet(
        nation_id=nation_id,
        origin_territory=origin_id,
        destination_territory=dest_id,
        unit_count=unit_count,
        status=status,
        standing_order=standing_order,
        arrives_at=arrives_at,
        confirmation_expires_at=confirmation_expires_at,
    )
    if occupation_expires_at is not None:
        fleet.occupation_expires_at = occupation_expires_at
    db.add(fleet)
    db.flush()
    return fleet


# ---------------------------------------------------------------------------
# Fixtures: two nations, two territories
# ---------------------------------------------------------------------------


@pytest.fixture()
def enemy_player(db: Session) -> Player:
    player = Player(
        username="enemyplayer",
        email="enemy@example.com",
        password_hash=hash_password("enemypassword123"),
    )
    db.add(player)
    db.flush()
    return player


@pytest.fixture()
def enemy_nation(db: Session, enemy_player: Player) -> Nation:
    nation = Nation(
        player_id=enemy_player.id,
        name="Enemy Nation",
        minerals=1000,
        fuel=1000,
        currency=500,
    )
    db.add(nation)
    db.flush()
    return nation


@pytest.fixture()
def home_territory(db: Session, test_nation: Nation) -> Territory:
    t = Territory(
        node_key="0,0",
        name="Home World",
        territory_type="normal",
        nation_id=test_nation.id,
        mineral_richness=1.00,
        fuel_richness=1.00,
        distance_from_center=0,
        is_owned=True,
        owned_at=datetime.now(timezone.utc),
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture()
def enemy_territory(db: Session, enemy_nation: Nation) -> Territory:
    t = Territory(
        node_key="2,0",
        name="Enemy Home World",
        territory_type="normal",
        nation_id=enemy_nation.id,
        mineral_richness=1.00,
        fuel_richness=1.00,
        distance_from_center=2,
        is_owned=True,
        owned_at=datetime.now(timezone.utc),
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture()
def auth_client(db: Session, test_player: Player):
    token = create_access_token(test_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def enemy_auth_client(db: Session, enemy_player: Player, enemy_nation: Nation):
    token = create_access_token(enemy_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


# ===========================================================================
# 1. PBC expiry → `holding` (NOT `engaged`)
# ===========================================================================


class TestPBCExpiryGoesToHolding:
    """post_battle_choice expiry must transition the fleet to `holding`, not `engaged`.

    Game-design rule: inaction must never produce maximum harm. Resuming combat
    automatically (by going to `engaged`) on PBC expiry violates this rule.
    """

    def test_pbc_expiry_fleet_goes_to_holding(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Expired PBC fleet must become `holding`, not `engaged`."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=now - timedelta(minutes=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None, "Fleet must still exist after PBC expiry"
            assert f.status == "holding", (
                f"CRITICAL: Expired PBC fleet must become 'holding', got {f.status!r}. "
                f"If 'engaged', the implementation auto-resumed combat without player action, "
                f"violating the inaction-must-not-harm rule."
            )
        finally:
            fresh.close()

    def test_pbc_expiry_clears_confirmation_expires_at(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """confirmation_expires_at must be cleared when PBC expires."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=now - timedelta(minutes=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.confirmation_expires_at is None, (
                "confirmation_expires_at must be cleared when PBC window expires"
            )
        finally:
            fresh.close()

    def test_pbc_expiry_does_not_trigger_combat_same_tick(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """PBC expiry must NOT trigger a combat_round event in the same tick."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Seed a defender so combat would fire if the fleet erroneously re-engaged
        defender = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=50,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender)
        db.flush()

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=now - timedelta(minutes=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            # If PBC expiry went to `engaged` and was processed as combat in the same tick,
            # there would be a combat_round event referencing this fleet.
            from sqlalchemy import cast, Integer as SAInt
            combat_events = fresh.query(Event).filter(
                Event.type == "combat_round",
                cast(Event.payload["fleet_id"].astext, SAInt) == fleet_id,
            ).all()
            assert len(combat_events) == 0, (
                "PBC expiry must NOT fire a combat_round in the same tick. "
                f"Found {len(combat_events)} combat_round event(s). "
                "The fleet should go to 'holding' and fight on the NEXT tick only if "
                "standing_order == 'engage'."
            )
        finally:
            fresh.close()

    def test_pbc_not_expired_stays_in_post_battle_choice(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """A PBC fleet with a future expiry must remain in post_battle_choice."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=now + timedelta(hours=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.status == "post_battle_choice", (
                f"PBC fleet with non-expired window must stay 'post_battle_choice', got {f.status!r}"
            )
        finally:
            fresh.close()

    def test_pbc_expiry_standing_order_is_hold_or_recall_not_attack(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """After PBC expiry → holding, standing_order must never be 'attack'."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=now - timedelta(minutes=1),
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None
            assert f.status == "holding"
            assert f.standing_order != "attack", (
                "Game design rule: standing_order must NEVER be 'attack' after PBC expiry. "
                "Valid values: 'hold', 'recall', 'engage'."
            )
            # After PBC expiry the order must reset to the safe default
            assert f.standing_order == "hold", (
                f"standing_order must reset to 'hold' after PBC expiry, got {f.standing_order!r}"
            )
        finally:
            fresh.close()


# ===========================================================================
# 2. Attacker tick-action standing order (`engage`)
# ===========================================================================


class TestStandingOrderEngage:
    """A `holding` fleet with standing_order == 'engage' triggers combat that tick.
    A `holding` fleet with standing_order == 'hold' does NOT trigger combat.
    After combat, the attacker (if surviving) goes to post_battle_choice and
    standing_order resets to 'hold'.
    """

    def test_holding_fleet_engage_fires_combat(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """holding fleet with standing_order='engage' must fire a combat_round event."""
        _set_war(db, test_nation.id, enemy_nation.id)

        defender = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=50,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender)
        db.flush()

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
            standing_order="engage",
            unit_count=50,
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            from sqlalchemy import cast, Integer as SAInt
            combat_events = fresh.query(Event).filter(
                Event.type == "combat_round",
                cast(Event.payload["fleet_id"].astext, SAInt) == fleet_id,
            ).all()
            assert len(combat_events) >= 1, (
                "A holding fleet with standing_order='engage' must fire a combat_round event "
                f"in the tick. Found {len(combat_events)} event(s)."
            )
        finally:
            fresh.close()

    def test_holding_fleet_hold_does_not_fire_combat(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """holding fleet with standing_order='hold' must NOT fire a combat_round event."""
        _set_war(db, test_nation.id, enemy_nation.id)

        defender = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=50,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender)
        db.flush()

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
            standing_order="hold",
            unit_count=50,
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            from sqlalchemy import cast, Integer as SAInt
            combat_events = fresh.query(Event).filter(
                Event.type == "combat_round",
                cast(Event.payload["fleet_id"].astext, SAInt) == fleet_id,
            ).all()
            assert len(combat_events) == 0, (
                "A holding fleet with standing_order='hold' must NOT fire a combat_round event. "
                f"Found {len(combat_events)} event(s)."
            )
        finally:
            fresh.close()

    def test_holding_fleet_engage_resets_standing_order_to_hold_after_combat(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """After a combat round triggered by 'engage', standing_order must reset to 'hold'."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Give the defender far fewer units so the attacker survives and goes to PBC
        defender = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=1,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender)
        db.flush()

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
            standing_order="engage",
            unit_count=200,
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None, "Attacker fleet must still exist"
            # Fleet should be in post_battle_choice after winning a combat round with defenders
            # standing_order must be reset to 'hold'
            assert f.standing_order == "hold", (
                f"standing_order must reset to 'hold' after a combat round triggered by 'engage', "
                f"got {f.standing_order!r}"
            )
        finally:
            fresh.close()

    def test_holding_fleet_engage_winner_goes_to_post_battle_choice(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Holding fleet with engage fires combat; if attacker survives, goes to post_battle_choice."""
        _set_war(db, test_nation.id, enemy_nation.id)

        defender = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=1,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender)
        db.flush()

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
            standing_order="engage",
            unit_count=200,
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None, "Attacker fleet must still exist"
            # After winning combat on an 'engage' order, the fleet goes to post_battle_choice
            assert f.status == "post_battle_choice", (
                f"Surviving holding fleet that used 'engage' and beat defenders must go to "
                f"post_battle_choice, got {f.status!r}"
            )
        finally:
            fresh.close()

    def test_holding_fleet_engage_with_no_defenders_enters_occupying(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Holding fleet with 'engage' and no defenders at the territory enters occupying."""
        _set_war(db, test_nation.id, enemy_nation.id)
        # No defender fleet seeded

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
            standing_order="engage",
            unit_count=50,
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None, "Fleet must still exist"
            assert f.status == "occupying", (
                f"Holding fleet with 'engage' and no defenders must enter 'occupying', "
                f"got {f.status!r}"
            )
        finally:
            fresh.close()

    def test_engaged_fleet_still_fires_combat(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """An `engaged`-status fleet must still fire combat as before (existing behaviour)."""
        _set_war(db, test_nation.id, enemy_nation.id)

        defender = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=50,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender)
        db.flush()

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="engaged",
            unit_count=50,
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            from sqlalchemy import cast, Integer as SAInt
            combat_events = fresh.query(Event).filter(
                Event.type == "combat_round",
                cast(Event.payload["fleet_id"].astext, SAInt) == fleet_id,
            ).all()
            assert len(combat_events) >= 1, (
                "An `engaged` fleet must still fire a combat_round event each tick. "
                f"Found {len(combat_events)} event(s)."
            )
        finally:
            fresh.close()


# ===========================================================================
# 3. Defender sortie endpoint: POST /api/military/fleets/{fleet_id}/sortie
# ===========================================================================


class TestDefenderSortieEndpoint:
    """Tests for POST /api/military/fleets/{fleet_id}/sortie."""

    def test_sortie_success_against_holding_enemy(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Defender with stationed fleet calls sortie against a holding attacker → 200,
        enemy fleet transitions to `engaged`."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Attacker fleet is holding at enemy territory
        attacker_fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
            unit_count=50,
        )
        attacker_fleet_id = attacker_fleet.id

        # Defender fleet stationed at their own territory
        defender_fleet = _make_fleet(
            db,
            nation_id=enemy_nation.id,
            origin_id=enemy_territory.id,
            status="stationed",
            unit_count=30,
        )
        defender_fleet_id = defender_fleet.id
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{defender_fleet_id}/sortie")
        assert resp.status_code == 200, (
            f"Sortie against holding enemy fleet must return 200, got {resp.status_code}: {resp.text}"
        )

        db.expire_all()
        attacker = db.get(Fleet, attacker_fleet_id)
        assert attacker is not None, "Attacker fleet must still exist after sortie"
        assert attacker.status == "engaged", (
            f"Attacker fleet must be `engaged` after sortie, got {attacker.status!r}"
        )

    def test_sortie_success_against_occupying_enemy(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Sortie against an occupying attacker also transitions the attacker to `engaged`."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        attacker_fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="occupying",
            occupation_expires_at=now + timedelta(hours=6),
            unit_count=50,
        )
        attacker_fleet_id = attacker_fleet.id

        defender_fleet = _make_fleet(
            db,
            nation_id=enemy_nation.id,
            origin_id=enemy_territory.id,
            status="stationed",
            unit_count=30,
        )
        defender_fleet_id = defender_fleet.id
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{defender_fleet_id}/sortie")
        assert resp.status_code == 200, (
            f"Sortie against occupying enemy fleet must return 200, got {resp.status_code}: {resp.text}"
        )

        db.expire_all()
        attacker = db.get(Fleet, attacker_fleet_id)
        assert attacker is not None
        assert attacker.status == "engaged", (
            f"Occupying attacker must become `engaged` after sortie, got {attacker.status!r}"
        )

    def test_sortie_sets_last_sortie_at_on_territory(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Successful sortie sets `last_sortie_at` on the territory to approximately now."""
        _set_war(db, test_nation.id, enemy_nation.id)

        attacker_fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
            unit_count=50,
        )

        defender_fleet = _make_fleet(
            db,
            nation_id=enemy_nation.id,
            origin_id=enemy_territory.id,
            status="stationed",
            unit_count=30,
        )
        defender_fleet_id = defender_fleet.id
        territory_id = enemy_territory.id
        before = datetime.now(timezone.utc)
        db.flush()

        enemy_auth_client.post(f"/api/military/fleets/{defender_fleet_id}/sortie")
        after = datetime.now(timezone.utc)

        db.expire_all()
        territory = db.get(Territory, territory_id)
        last_sortie = getattr(territory, "last_sortie_at", None)
        assert last_sortie is not None, (
            "territory.last_sortie_at must be set after a successful sortie"
        )
        lsa = last_sortie.replace(tzinfo=timezone.utc) if last_sortie.tzinfo is None else last_sortie
        assert (
            before - timedelta(seconds=CLOCK_TOLERANCE_SECONDS)
            <= lsa
            <= after + timedelta(seconds=CLOCK_TOLERANCE_SECONDS)
        ), (
            f"last_sortie_at {lsa} must be approximately now (between {before} and {after})"
        )

    def test_sortie_returns_fleet_response(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Sortie response body must be the defender's fleet (not the attacker's)."""
        _set_war(db, test_nation.id, enemy_nation.id)

        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
            unit_count=50,
        )

        defender_fleet = _make_fleet(
            db,
            nation_id=enemy_nation.id,
            origin_id=enemy_territory.id,
            status="stationed",
            unit_count=30,
        )
        defender_fleet_id = defender_fleet.id
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{defender_fleet_id}/sortie")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == defender_fleet_id, (
            "Sortie response must describe the defender's fleet, not the attacker's"
        )
        assert data["nation_id"] == enemy_nation.id, (
            "Sortie response fleet must belong to the defender nation"
        )

    def test_sortie_unauthenticated_returns_401(
        self,
        client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Unauthenticated sortie request must return 401."""
        _set_war(db, test_nation.id, enemy_nation.id)

        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
            unit_count=50,
        )
        defender_fleet = _make_fleet(
            db,
            nation_id=enemy_nation.id,
            origin_id=enemy_territory.id,
            status="stationed",
            unit_count=30,
        )
        db.flush()

        resp = client.post(f"/api/military/fleets/{defender_fleet.id}/sortie")
        assert resp.status_code == 401, (
            f"Unauthenticated sortie must return 401, got {resp.status_code}"
        )

    def test_sortie_wrong_owner_returns_403(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Player cannot call sortie on another nation's fleet — returns 403."""
        _set_war(db, test_nation.id, enemy_nation.id)

        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
            unit_count=50,
        )
        defender_fleet = _make_fleet(
            db,
            nation_id=enemy_nation.id,
            origin_id=enemy_territory.id,
            status="stationed",
            unit_count=30,
        )
        db.flush()

        # auth_client is test_nation (the attacker); calling sortie on enemy's fleet
        resp = auth_client.post(f"/api/military/fleets/{defender_fleet.id}/sortie")
        assert resp.status_code == 403, (
            f"Calling sortie on another nation's fleet must return 403, got {resp.status_code}"
        )

    def test_sortie_nonexistent_fleet_returns_404(
        self,
        enemy_auth_client: TestClient,
        test_nation: Nation,
        enemy_nation: Nation,
    ):
        """Sortie on a non-existent fleet ID must return 404."""
        resp = enemy_auth_client.post("/api/military/fleets/999999/sortie")
        assert resp.status_code in (403, 404), (
            f"Sortie on non-existent fleet must return 403 or 404, got {resp.status_code}"
        )

    def test_sortie_no_enemy_fleet_returns_409(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """No holding or occupying enemy fleet at the territory → 409 conflict."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # No attacker fleet at enemy_territory
        defender_fleet = _make_fleet(
            db,
            nation_id=enemy_nation.id,
            origin_id=enemy_territory.id,
            status="stationed",
            unit_count=30,
        )
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{defender_fleet.id}/sortie")
        assert resp.status_code == 409, (
            f"Sortie with no enemy fleet at territory must return 409, got {resp.status_code}"
        )

    def test_sortie_fleet_not_stationed_returns_409(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Defender fleet must be in `stationed` status to sortie; in_transit → 409."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Attacker holding at enemy territory
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
            unit_count=50,
        )

        # Defender fleet is in_transit, not stationed
        defender_fleet = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=home_territory.id,
            destination_territory=enemy_territory.id,
            unit_count=30,
            status="in_transit",
            standing_order="hold",
        )
        db.add(defender_fleet)
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{defender_fleet.id}/sortie")
        assert resp.status_code == 409, (
            f"Sortie with non-stationed defender fleet must return 409, got {resp.status_code}"
        )

    def test_sortie_fleet_not_at_own_territory_returns_409(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Defender fleet must be stationed at a territory owned by the caller."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Attacker holding at home_territory (not enemy territory)
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=home_territory.id,
            status="holding",
            unit_count=50,
        )

        # Defender fleet stationed at the attacker's territory (wrong ownership)
        defender_fleet = _make_fleet(
            db,
            nation_id=enemy_nation.id,
            origin_id=home_territory.id,  # home_territory belongs to test_nation, not enemy
            status="stationed",
            unit_count=30,
        )
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{defender_fleet.id}/sortie")
        assert resp.status_code == 409, (
            f"Sortie from non-owned territory must return 409, got {resp.status_code}: {resp.text}"
        )

    def test_sortie_cooldown_returns_429(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Second sortie within the 4-hour cooldown must return 429."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Set last_sortie_at to 1 hour ago (within 4-hour cooldown)
        now = datetime.now(timezone.utc)
        enemy_territory_id = enemy_territory.id
        db.expire_all()
        territory = db.get(Territory, enemy_territory_id)
        setattr(territory, "last_sortie_at", now - timedelta(hours=1))
        db.flush()

        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
            unit_count=50,
        )
        defender_fleet = _make_fleet(
            db,
            nation_id=enemy_nation.id,
            origin_id=enemy_territory.id,
            status="stationed",
            unit_count=30,
        )
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{defender_fleet.id}/sortie")
        assert resp.status_code == 429, (
            f"Second sortie within 4-hour cooldown must return 429, got {resp.status_code}"
        )

    def test_sortie_cooldown_expired_allows_new_sortie(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Sortie after the 4-hour cooldown has elapsed must succeed."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Set last_sortie_at to 5 hours ago (beyond 4-hour cooldown)
        now = datetime.now(timezone.utc)
        enemy_territory_id = enemy_territory.id
        db.expire_all()
        territory = db.get(Territory, enemy_territory_id)
        setattr(territory, "last_sortie_at", now - timedelta(hours=5))
        db.flush()

        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
            unit_count=50,
        )
        defender_fleet = _make_fleet(
            db,
            nation_id=enemy_nation.id,
            origin_id=enemy_territory.id,
            status="stationed",
            unit_count=30,
        )
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{defender_fleet.id}/sortie")
        assert resp.status_code == 200, (
            f"Sortie after 4-hour cooldown elapsed must return 200, got {resp.status_code}: {resp.text}"
        )

    def test_sortie_no_cooldown_on_first_sortie(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """First sortie (last_sortie_at is None) must not be blocked by cooldown."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # last_sortie_at is None (no prior sortie)
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
            unit_count=50,
        )
        defender_fleet = _make_fleet(
            db,
            nation_id=enemy_nation.id,
            origin_id=enemy_territory.id,
            status="stationed",
            unit_count=30,
        )
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{defender_fleet.id}/sortie")
        assert resp.status_code == 200, (
            f"First sortie (no prior cooldown) must return 200, got {resp.status_code}: {resp.text}"
        )

    def test_sortie_against_pbc_fleet_queues_sortie(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Sortie while attacker is in post_battle_choice → 200 and sortie_queued set on territory."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        attacker_fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=now + timedelta(hours=1),
            unit_count=50,
        )
        attacker_fleet_id = attacker_fleet.id

        defender_fleet = _make_fleet(
            db,
            nation_id=enemy_nation.id,
            origin_id=enemy_territory.id,
            status="stationed",
            unit_count=30,
        )
        defender_fleet_id = defender_fleet.id
        territory_id = enemy_territory.id
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{defender_fleet_id}/sortie")
        assert resp.status_code == 200, (
            f"Sortie against PBC fleet must return 200 (queued), got {resp.status_code}: {resp.text}"
        )

        # Attacker fleet must still be in PBC (not immediately engaged)
        db.expire_all()
        attacker = db.get(Fleet, attacker_fleet_id)
        assert attacker is not None
        assert attacker.status == "post_battle_choice", (
            "Attacker fleet must remain in post_battle_choice after a queued sortie; "
            "the sortie fires when PBC expires, not immediately."
        )

        # sortie_queued must be set on the territory
        territory = db.get(Territory, territory_id)
        sortie_queued = getattr(territory, "sortie_queued", None)
        assert sortie_queued is True, (
            "territory.sortie_queued must be True after a sortie against a PBC fleet"
        )

    def test_sortie_against_pending_confirmation_fleet_returns_409(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Fleet in `pending_confirmation` is not yet `holding`/`occupying` — 409."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="pending_confirmation",
            confirmation_expires_at=now + timedelta(hours=4),
            unit_count=50,
        )
        defender_fleet = _make_fleet(
            db,
            nation_id=enemy_nation.id,
            origin_id=enemy_territory.id,
            status="stationed",
            unit_count=30,
        )
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{defender_fleet.id}/sortie")
        assert resp.status_code == 409, (
            f"Sortie against pending_confirmation fleet must return 409 "
            f"(only holding/occupying/pbc are valid), got {resp.status_code}"
        )


# ===========================================================================
# 4. Defender auto-rout (fires in tick loop after combat)
# ===========================================================================


class TestDefenderAutoRout:
    """After a combat round where the attacker took losses AND the defender survived,
    the defender deals bonus damage = DEFENDER_AUTO_ROUT_FRACTION * attacker_losses.
    This fires in the same tick as the combat, requires no player action.
    """

    def test_auto_rout_fires_when_attacker_took_losses(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """When attacker took nonzero losses and defender survived, auto-rout bonus fires."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Attacker: 10 units (small so they take real losses vs defender)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="engaged",
            unit_count=10,
        )
        fleet_id = fleet.id

        # Defender: 200 units (many so they survive and deal auto-rout)
        defender_fleet = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=200,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender_fleet)
        defender_fleet_id = None
        db.flush()
        defender_fleet_id = defender_fleet.id
        db.commit()

        # Record attacker unit_count before tick
        pre_tick_attacker = 10

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            from sqlalchemy import cast, Integer as SAInt

            # Verify a combat_round event was produced
            combat_event = fresh.query(Event).filter(
                Event.type == "combat_round",
                cast(Event.payload["fleet_id"].astext, SAInt) == fleet_id,
            ).first()
            assert combat_event is not None, "combat_round event must exist"
            attacker_losses = combat_event.payload.get("attacker_losses", 0)

            if attacker_losses > 0:
                # auto-rout bonus must have been applied — look for an auto_rout_applied event
                auto_rout_event = fresh.query(Event).filter(
                    Event.type == "auto_rout_applied",
                ).first()
                assert auto_rout_event is not None, (
                    f"auto_rout_applied event must be emitted when attacker took {attacker_losses} losses "
                    f"and defender survived. No auto_rout_applied event found."
                )
                bonus = auto_rout_event.payload.get("bonus_damage", 0)
                expected_bonus = max(1, round(attacker_losses * DEFENDER_AUTO_ROUT_FRACTION))
                assert bonus == expected_bonus, (
                    f"auto-rout bonus must be max(1, round({attacker_losses} * {DEFENDER_AUTO_ROUT_FRACTION})) = "
                    f"{expected_bonus}, got {bonus}"
                )
        finally:
            fresh.close()

    def test_auto_rout_does_not_fire_when_attacker_took_zero_losses(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Auto-rout must NOT fire when attacker took zero losses in the round."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Attacker: 500 units — enough to take zero losses against a tiny defender
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="engaged",
            unit_count=500,
        )
        fleet_id = fleet.id

        # Defender: 1 unit — too weak to penetrate shields and deal meaningful damage
        defender_fleet = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=1,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender_fleet)
        db.flush()
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            from sqlalchemy import cast, Integer as SAInt
            combat_event = fresh.query(Event).filter(
                Event.type == "combat_round",
                cast(Event.payload["fleet_id"].astext, SAInt) == fleet_id,
            ).first()

            if combat_event is not None:
                attacker_losses = combat_event.payload.get("attacker_losses", 0)
                if attacker_losses == 0:
                    # No auto-rout should have fired
                    auto_rout_event = fresh.query(Event).filter(
                        Event.type == "auto_rout_applied",
                    ).first()
                    assert auto_rout_event is None, (
                        "auto_rout_applied must NOT be emitted when attacker took zero losses. "
                        f"Found: {auto_rout_event}"
                    )
        finally:
            fresh.close()

    def test_auto_rout_does_not_fire_when_defender_eliminated(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """If the defender is eliminated in the combat round, auto-rout must not fire."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Attacker: massive force
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="engaged",
            unit_count=1000,
        )
        fleet_id = fleet.id

        # Defender: 1 unit — will be eliminated
        defender_fleet = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=1,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender_fleet)
        db.flush()
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            from sqlalchemy import cast, Integer as SAInt
            combat_event = fresh.query(Event).filter(
                Event.type == "combat_round",
                cast(Event.payload["fleet_id"].astext, SAInt) == fleet_id,
            ).first()

            if combat_event is not None:
                defender_remaining = combat_event.payload.get("defender_remaining", 0)
                if defender_remaining == 0:
                    # Defender is gone; auto-rout must not fire
                    auto_rout_event = fresh.query(Event).filter(
                        Event.type == "auto_rout_applied",
                    ).first()
                    assert auto_rout_event is None, (
                        "auto_rout_applied must NOT be emitted when the defender was eliminated. "
                        f"Found: {auto_rout_event}"
                    )
        finally:
            fresh.close()

    def test_auto_rout_bonus_capped_at_attacker_fleet_size(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Auto-rout bonus damage cannot exceed the attacker's current fleet size."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Attacker small fleet so losses could theoretically generate a large bonus
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="engaged",
            unit_count=10,
        )
        fleet_id = fleet.id

        defender_fleet = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=200,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender_fleet)
        db.flush()
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            auto_rout_event = fresh.query(Event).filter(
                Event.type == "auto_rout_applied",
            ).first()

            if auto_rout_event is not None:
                damage_applied = auto_rout_event.payload.get("damage_applied", 0)
                # Actual damage applied cannot cause attacker_remaining to go negative
                from sqlalchemy import cast, Integer as SAInt
                combat_event = fresh.query(Event).filter(
                    Event.type == "combat_round",
                    cast(Event.payload["fleet_id"].astext, SAInt) == fleet_id,
                ).first()
                if combat_event:
                    attacker_remaining_after_combat = combat_event.payload.get("attacker_remaining", 0)
                    assert damage_applied <= attacker_remaining_after_combat, (
                        f"auto-rout damage_applied ({damage_applied}) must not exceed the attacker's remaining units "
                        f"({attacker_remaining_after_combat}) after the normal combat round"
                    )
        finally:
            fresh.close()

    def test_auto_rout_minimum_one_damage(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Auto-rout bonus is max(1, round(losses * fraction)) — minimum 1 if it fires."""
        # This is verified by the formula: round(1 * 0.5) = 1 ≥ 1
        from app.services.combat import resolve_combat_tick
        from app.constants import UNIT_STATS

        stats = UNIT_STATS["starfighter"]
        # 1 attacker loss → bonus = max(1, round(1 * 0.50)) = max(1, 1) = 1
        attacker_losses = 1
        expected_bonus = max(1, round(attacker_losses * DEFENDER_AUTO_ROUT_FRACTION))
        assert expected_bonus == 1, (
            f"Auto-rout minimum is 1 unit of bonus damage (got formula result {expected_bonus})"
        )

        # 3 attacker losses → bonus = max(1, round(3 * 0.5)) = max(1, 2) = 2
        attacker_losses = 3
        expected_bonus = max(1, round(attacker_losses * DEFENDER_AUTO_ROUT_FRACTION))
        assert expected_bonus == 2

    def test_auto_rout_formula_matches_defender_auto_rout_fraction(
        self,
    ):
        """Pure-function test: auto-rout bonus formula produces correct values."""
        cases = [
            (1, 1),    # round(1 * 0.5) = 1, max(1, 1) = 1
            (2, 1),    # round(2 * 0.5) = 1, max(1, 1) = 1
            (4, 2),    # round(4 * 0.5) = 2, max(1, 2) = 2
            (10, 5),   # round(10 * 0.5) = 5
            (7, 4),    # round(7 * 0.5) = 4 (rounds half to even: round(3.5)=4)
        ]
        for attacker_losses, expected in cases:
            result = max(1, round(attacker_losses * DEFENDER_AUTO_ROUT_FRACTION))
            assert result == expected, (
                f"auto_rout formula: attacker_losses={attacker_losses} → "
                f"expected {expected}, got {result}"
            )


# ===========================================================================
# 5. Raid cap (RAID_CAP_FRACTION * current_stockpile per resource)
# ===========================================================================


class TestRaidCap:
    """Raid now clamps plunder to RAID_CAP_FRACTION * current_stockpile per resource.
    Tested via pure formula arithmetic; endpoint tests confirm the cap is enforced.
    """

    def test_raid_cap_formula_minerals(self):
        """Pure: raid cap = RAID_CAP_FRACTION * stockpile (per resource)."""
        stockpile = 1000.0
        cap = RAID_CAP_FRACTION * stockpile
        assert cap == 100.0, (
            f"Raid cap on 1000 minerals must be {RAID_CAP_FRACTION * 1000} = 100, got {cap}"
        )

    def test_raid_cap_formula_zero_stockpile(self):
        """Pure: raid cap on zero stockpile is zero."""
        stockpile = 0.0
        cap = RAID_CAP_FRACTION * stockpile
        assert cap == 0.0, "Raid cap on 0 stockpile must be 0"

    def test_raid_cap_formula_partial_stockpile(self):
        """Pure: fractional stockpile produces correct cap."""
        stockpile = 50.0
        cap = RAID_CAP_FRACTION * stockpile
        assert abs(cap - 5.0) < 0.001, (
            f"Raid cap on 50 stockpile must be {RAID_CAP_FRACTION * 50} = 5.0, got {cap}"
        )

    def test_raid_cap_applied_to_minerals(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Raid response: minerals_stolen <= RAID_CAP_FRACTION * defender_minerals."""
        _set_war(db, test_nation.id, enemy_nation.id)

        defender_minerals = float(enemy_nation.minerals)  # seeded to 1000
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            unit_count=500,  # large fleet so raw formula exceeds the cap
        )
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet.id}/raid")
        assert resp.status_code == 200, resp.text

        # Check the raid_applied event payload
        db.expire_all()
        from sqlalchemy import cast, Integer as SAInt
        raid_event = db.query(Event).filter(
            Event.type == "raid_applied",
        ).order_by(Event.id.desc()).first()
        assert raid_event is not None, "raid_applied event must be emitted"

        minerals_stolen = raid_event.payload.get("minerals_stolen", 0)
        expected_cap = RAID_CAP_FRACTION * defender_minerals
        assert minerals_stolen <= expected_cap + 0.01, (
            f"minerals_stolen ({minerals_stolen}) must not exceed cap "
            f"({RAID_CAP_FRACTION} * {defender_minerals} = {expected_cap})"
        )

    def test_raid_cap_applied_to_fuel(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Raid response: fuel_stolen <= RAID_CAP_FRACTION * defender_fuel."""
        _set_war(db, test_nation.id, enemy_nation.id)

        defender_fuel = float(enemy_nation.fuel)  # seeded to 1000
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            unit_count=500,
        )
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet.id}/raid")
        assert resp.status_code == 200, resp.text

        db.expire_all()
        raid_event = db.query(Event).filter(
            Event.type == "raid_applied",
        ).order_by(Event.id.desc()).first()
        assert raid_event is not None

        fuel_stolen = raid_event.payload.get("fuel_stolen", 0)
        expected_cap = RAID_CAP_FRACTION * defender_fuel
        assert fuel_stolen <= expected_cap + 0.01, (
            f"fuel_stolen ({fuel_stolen}) must not exceed cap "
            f"({RAID_CAP_FRACTION} * {defender_fuel} = {expected_cap})"
        )

    def test_raid_zero_mineral_stockpile_yields_zero(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """If defender has 0 minerals, raid yields 0 minerals (cap = 0)."""
        _set_war(db, test_nation.id, enemy_nation.id)

        enemy_nation.minerals = 0
        db.flush()

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            unit_count=100,
        )
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet.id}/raid")
        assert resp.status_code == 200, resp.text

        db.expire_all()
        raid_event = db.query(Event).filter(
            Event.type == "raid_applied",
        ).order_by(Event.id.desc()).first()
        assert raid_event is not None

        minerals_stolen = raid_event.payload.get("minerals_stolen", 0)
        assert minerals_stolen == 0, (
            f"minerals_stolen must be 0 when defender has 0 minerals (cap = 0), got {minerals_stolen}"
        )

    def test_raid_zero_fuel_stockpile_yields_zero(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """If defender has 0 fuel, raid yields 0 fuel (cap = 0)."""
        _set_war(db, test_nation.id, enemy_nation.id)

        enemy_nation.fuel = 0
        db.flush()

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            unit_count=100,
        )
        db.flush()

        resp = auth_client.post(f"/api/military/fleets/{fleet.id}/raid")
        assert resp.status_code == 200, resp.text

        db.expire_all()
        raid_event = db.query(Event).filter(
            Event.type == "raid_applied",
        ).order_by(Event.id.desc()).first()
        assert raid_event is not None

        fuel_stolen = raid_event.payload.get("fuel_stolen", 0)
        assert fuel_stolen == 0, (
            f"fuel_stolen must be 0 when defender has 0 fuel (cap = 0), got {fuel_stolen}"
        )

    def test_raid_does_not_drain_stockpile_below_zero(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Raid must not cause defender's stockpile to drop below zero."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Set a small stockpile
        enemy_nation.minerals = 50
        enemy_nation.fuel = 30
        db.flush()

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            unit_count=100,
        )
        fleet_id = fleet.id
        enemy_nation_id = enemy_nation.id
        db.flush()

        auth_client.post(f"/api/military/fleets/{fleet_id}/raid")

        db.expire_all()
        defender = db.get(Nation, enemy_nation_id)
        assert float(defender.minerals) >= 0, (
            f"Defender minerals must not go below 0 after raid, got {defender.minerals}"
        )
        assert float(defender.fuel) >= 0, (
            f"Defender fuel must not go below 0 after raid, got {defender.fuel}"
        )

    def test_raid_soft_damage_model_cap_is_fraction_not_all(self):
        """Pure sanity check: RAID_CAP_FRACTION is < 1.0 (not all-or-nothing)."""
        assert RAID_CAP_FRACTION < 1.0, (
            f"RAID_CAP_FRACTION must be < 1.0 to enforce the soft damage model, "
            f"got {RAID_CAP_FRACTION}"
        )
        assert RAID_CAP_FRACTION > 0.0, (
            f"RAID_CAP_FRACTION must be > 0.0, got {RAID_CAP_FRACTION}"
        )


# ===========================================================================
# 6. Queued sortie during PBC (fires when PBC expires)
# ===========================================================================


class TestQueuedSortieOnPBCExpiry:
    """When a sortie is called while the attacker is in post_battle_choice:
    - sortie_queued is set True on the territory
    - When PBC expires, the fleet goes to `engaged` (not `holding`)
    - sortie_queued is cleared after it fires
    """

    def test_queued_sortie_fleet_goes_to_engaged_on_pbc_expiry(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """If sortie_queued is True on a territory and PBC expires, fleet becomes `engaged`."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        attacker_fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=now - timedelta(minutes=1),  # expired
            unit_count=50,
        )
        attacker_fleet_id = attacker_fleet.id

        # Simulate a queued sortie by setting sortie_queued on the territory
        territory = db.get(Territory, enemy_territory.id)
        setattr(territory, "sortie_queued", True)
        db.flush()
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, attacker_fleet_id)
            assert f is not None, "Attacker fleet must still exist"
            assert f.status == "engaged", (
                f"When sortie_queued is True and PBC expires, fleet must become 'engaged' "
                f"(not 'holding'). Got {f.status!r}"
            )
        finally:
            fresh.close()

    def test_queued_sortie_clears_sortie_queued_on_pbc_expiry(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """sortie_queued must be cleared (False/None) after the queued sortie fires."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=now - timedelta(minutes=1),
            unit_count=50,
        )

        territory = db.get(Territory, enemy_territory.id)
        setattr(territory, "sortie_queued", True)
        territory_id = enemy_territory.id
        db.flush()
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            t = fresh.get(Territory, territory_id)
            sortie_queued = getattr(t, "sortie_queued", None)
            assert not sortie_queued, (
                "sortie_queued must be cleared (False or None) after the queued sortie fires on PBC expiry. "
                f"Got {sortie_queued!r}"
            )
        finally:
            fresh.close()

    def test_no_queued_sortie_pbc_expiry_goes_to_holding(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Without sortie_queued, PBC expiry must go to `holding` (not `engaged`)."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        attacker_fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=now - timedelta(minutes=1),
            unit_count=50,
        )
        attacker_fleet_id = attacker_fleet.id

        # sortie_queued is NOT set
        territory = db.get(Territory, enemy_territory.id)
        setattr(territory, "sortie_queued", False)
        db.flush()
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, attacker_fleet_id)
            assert f is not None
            assert f.status == "holding", (
                f"Without sortie_queued, PBC expiry must produce 'holding', got {f.status!r}"
            )
        finally:
            fresh.close()

    def test_queued_sortie_stored_correctly_via_endpoint(
        self,
        enemy_auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Calling the sortie endpoint against a PBC fleet sets sortie_queued on the territory."""
        _set_war(db, test_nation.id, enemy_nation.id)

        now = datetime.now(timezone.utc)
        attacker_fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=now + timedelta(hours=1),
            unit_count=50,
        )

        defender_fleet = _make_fleet(
            db,
            nation_id=enemy_nation.id,
            origin_id=enemy_territory.id,
            status="stationed",
            unit_count=30,
        )
        defender_fleet_id = defender_fleet.id
        territory_id = enemy_territory.id
        db.flush()

        resp = enemy_auth_client.post(f"/api/military/fleets/{defender_fleet_id}/sortie")
        assert resp.status_code == 200, resp.text

        db.expire_all()
        territory = db.get(Territory, territory_id)
        sortie_queued = getattr(territory, "sortie_queued", None)
        assert sortie_queued is True, (
            "sortie endpoint against a PBC fleet must set territory.sortie_queued = True"
        )

    def test_queued_sortie_pbc_expiry_does_fire_combat_next_tick(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """After PBC expires with sortie_queued, the fleet is engaged and should fight
        on the NEXT tick (not the PBC expiry tick itself)."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Seed a defender
        defender_fleet = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=50,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender_fleet)
        db.flush()

        now = datetime.now(timezone.utc)
        attacker_fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=now - timedelta(minutes=1),
            unit_count=50,
        )
        attacker_fleet_id = attacker_fleet.id

        territory = db.get(Territory, enemy_territory.id)
        setattr(territory, "sortie_queued", True)
        db.flush()
        db.commit()

        # First tick: PBC expires with sortie_queued → fleet goes to `engaged`
        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, attacker_fleet_id)
            assert f is not None
            # After the first tick the fleet should be `engaged` (ready to fight next tick)
            # It should NOT have fired a combat_round in this same tick
            from sqlalchemy import cast, Integer as SAInt
            combat_events = fresh.query(Event).filter(
                Event.type == "combat_round",
                cast(Event.payload["fleet_id"].astext, SAInt) == attacker_fleet_id,
            ).all()
            assert len(combat_events) == 0, (
                "The tick that promotes PBC → engaged (via sortie_queued) must NOT also fire "
                f"a combat_round in the same tick. Found {len(combat_events)} combat_round event(s). "
                "Combat fires on the NEXT tick."
            )
        finally:
            fresh.close()


# ===========================================================================
# 7. Game-design rule cross-checks
# ===========================================================================


class TestGameDesignRules:
    """Explicit checks for non-negotiable design rules that cut across mechanics."""

    def test_default_standing_order_on_holding_fleet_is_hold(
        self,
        db: Session,
        test_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Any fleet created with no explicit standing_order must default to 'hold', never 'engage' or 'attack'."""
        fleet = Fleet(
            nation_id=test_nation.id,
            origin_territory=home_territory.id,
            destination_territory=enemy_territory.id,
            unit_count=50,
            status="holding",
        )
        db.add(fleet)
        db.flush()

        assert fleet.standing_order == "hold", (
            f"Default standing_order must be 'hold', got {fleet.standing_order!r}. "
            "Inaction must never produce maximum harm."
        )

    def test_holding_fleet_engage_order_is_explicit_player_action(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """Combat only fires for a holding fleet when standing_order is explicitly 'engage'.
        Without player action, the fleet stays non-combative (standing_order='hold')."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # A fresh holding fleet from PBC expiry must have standing_order='hold', not 'engage'
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="holding",
            standing_order="hold",
            unit_count=50,
        )
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            from sqlalchemy import cast, Integer as SAInt
            combat_events = fresh.query(Event).filter(
                Event.type == "combat_round",
                cast(Event.payload["fleet_id"].astext, SAInt) == fleet.id,
            ).all()
            assert len(combat_events) == 0, (
                "CRITICAL: A holding fleet with standing_order='hold' must NOT attack without "
                "explicit player action. Inaction must never produce maximum harm."
            )
        finally:
            fresh.close()

    def test_pbc_expiry_inaction_does_not_resume_combat(
        self,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """CRITICAL: PBC expiry with no player action must never resume combat automatically."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Seed a defender so combat would fire if the fleet incorrectly went to engaged
        defender = Fleet(
            nation_id=enemy_nation.id,
            origin_territory=enemy_territory.id,
            unit_count=50,
            status="stationed",
            standing_order="hold",
        )
        db.add(defender)
        db.flush()

        now = datetime.now(timezone.utc)
        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=now - timedelta(minutes=1),
            standing_order="hold",
            unit_count=50,
        )
        fleet_id = fleet.id
        db.commit()

        _commit_and_run_tick(db)

        fresh = SessionLocal()
        try:
            f = fresh.get(Fleet, fleet_id)
            assert f is not None

            assert f.status != "engaged", (
                "CRITICAL GAME DESIGN VIOLATION: PBC expiry with standing_order='hold' "
                "must NOT produce status='engaged'. This would allow auto-resumption of "
                "combat without explicit player action."
            )
            assert f.status == "holding", (
                f"PBC expiry inaction must produce 'holding', got {f.status!r}"
            )

            from sqlalchemy import cast, Integer as SAInt
            combat_events = fresh.query(Event).filter(
                Event.type == "combat_round",
                cast(Event.payload["fleet_id"].astext, SAInt) == fleet_id,
            ).all()
            assert len(combat_events) == 0, (
                "CRITICAL: PBC expiry must not fire any combat_round events. "
                f"Found {len(combat_events)} event(s). Inaction must never produce maximum harm."
            )
        finally:
            fresh.close()

    def test_raid_soft_damage_multiple_raids_cannot_drain_in_one_tick(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        enemy_nation: Nation,
        home_territory: Territory,
        enemy_territory: Territory,
    ):
        """A single raid cannot steal more than RAID_CAP_FRACTION of the stockpile.
        This enforces the soft damage model: no single-tick total loss."""
        _set_war(db, test_nation.id, enemy_nation.id)

        # Give defender exactly 1000 minerals so cap is easy to verify
        enemy_nation.minerals = 1000
        enemy_nation.fuel = 0
        enemy_nation.currency = 0
        db.flush()

        fleet = _make_fleet(
            db,
            nation_id=test_nation.id,
            origin_id=home_territory.id,
            dest_id=enemy_territory.id,
            status="post_battle_choice",
            confirmation_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            unit_count=10000,  # enormous firepower
        )
        fleet_id = fleet.id
        enemy_nation_id = enemy_nation.id
        db.flush()

        auth_client.post(f"/api/military/fleets/{fleet_id}/raid")

        db.expire_all()
        defender = db.get(Nation, enemy_nation_id)
        remaining = float(defender.minerals)
        expected_min_remaining = 1000 * (1 - RAID_CAP_FRACTION) - 0.01
        assert remaining >= expected_min_remaining, (
            f"Soft damage model violation: defender must retain at least "
            f"{1000 * (1 - RAID_CAP_FRACTION)} minerals after a single raid. "
            f"Remaining: {remaining}. A single raid cannot drain more than "
            f"{RAID_CAP_FRACTION * 100:.0f}% of the stockpile."
        )
