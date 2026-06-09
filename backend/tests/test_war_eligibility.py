"""
Integration tests for war eligibility gates in the diplomacy router.

Two gates are tested:
  1. 7-day new player protection  (target < 7 days old, attacker >= 7 days old → 409)
  2. 3:1 territory ratio          (attacker.max > 3 × defender.max → 409)

Additional tests cover:
  - max_colonized_territory_count tracking (nation creation, claim, conquer)
  - Peak count does NOT decrease after territory loss
  - Ratio gate uses peak count, not current ownership count

Endpoint under test: PUT /api/diplomacy/{target_nation_id}  body: {"status": "war"}
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
from app.db.database import get_db
from app.models.diplomacy import Diplomacy
from app.models.fleet import Fleet
from app.models.nation import Nation
from app.models.player import Player
from app.models.territory import Territory
from app.models.territory_dissent import TerritoryDissent
from app.models.territory_population import TerritoryPopulation
from app.core.security import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Low-level helpers (mirror pattern from test_dissent.py)
# ---------------------------------------------------------------------------

def _player(db: Session, username: str, *, vacation: bool = False) -> Player:
    p = Player(
        username=username,
        email=f"{username}@test.example",
        password_hash=hash_password("testpw"),
        vacation_mode=vacation,
    )
    db.add(p)
    db.flush()
    return p


def _nation(
    db: Session,
    player_id: int,
    *,
    name: str | None = None,
    max_count: int = 1,
    created_at: datetime | None = None,
) -> Nation:
    nation = Nation(
        player_id=player_id,
        name=name or f"Nation-{player_id}",
        minerals=500,
        fuel=500,
        currency=500,
        max_colonized_territory_count=max_count,
    )
    db.add(nation)
    db.flush()
    if created_at is not None:
        # Override server_default with an explicit timestamp
        nation.created_at = created_at
        db.flush()
    return nation


def _territory(
    db: Session,
    node_key: str,
    nation_id: int | None = None,
    *,
    colonized: bool = True,
    territory_type: str = "normal",
) -> Territory:
    t = Territory(
        node_key=node_key,
        territory_type=territory_type,
        nation_id=nation_id,
        mineral_richness=1.0,
        fuel_richness=1.0,
        distance_from_center=1,
        is_owned=colonized and nation_id is not None,
        owned_at=datetime.now(timezone.utc) if (colonized and nation_id) else None,
    )
    db.add(t)
    db.flush()
    return t


def _override_factory(session: Session):
    def _override():
        yield session
    return _override


def _make_client(db: Session, player: Player) -> TestClient:
    """Return a TestClient authenticated as *player*, sharing the test DB session."""
    token = create_access_token(player.id)
    app.dependency_overrides[get_db] = _override_factory(db)
    client = TestClient(app, raise_server_exceptions=True)
    client.cookies.set("session", token)
    return client


# ---------------------------------------------------------------------------
# Helpers to set an explicit age on a Nation row
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)
_EIGHT_DAYS_AGO = _NOW - timedelta(days=8)
_THREE_DAYS_AGO = _NOW - timedelta(days=3)


# ---------------------------------------------------------------------------
# 7-day new player protection — HTTP-layer tests
# ---------------------------------------------------------------------------

class TestNewPlayerProtection:
    """Gate 1: older attacker cannot declare war on a nation founded < 7 days ago."""

    def test_old_attacker_cannot_attack_new_player(self, db: Session):
        """Attacker is ≥7 days old, target is <7 days old → 409."""
        try:
            p_att = _player(db, "old_attacker")
            p_def = _player(db, "new_defender")

            n_att = _nation(db, p_att.id, name="Old Nation", created_at=_EIGHT_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="New Nation", created_at=_THREE_DAYS_AGO)

            client = _make_client(db, p_att)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            assert resp.status_code == 409
            assert "new player protection" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_two_new_players_can_fight_each_other(self, db: Session):
        """Both attacker and target are <7 days old → protection does not apply → 200."""
        try:
            p_att = _player(db, "new_attacker")
            p_def = _player(db, "new_defender2")

            n_att = _nation(db, p_att.id, name="New Attacker Nation", created_at=_THREE_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="New Defender Nation", created_at=_THREE_DAYS_AGO)

            client = _make_client(db, p_att)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            # Both new → protection doesn't block; ratio 1:1 passes too
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_old_attacker_can_attack_old_defender(self, db: Session):
        """Both nations are ≥7 days old → no protection → 200."""
        try:
            p_att = _player(db, "old_att2")
            p_def = _player(db, "old_def2")

            n_att = _nation(db, p_att.id, name="Ancient Attacker", created_at=_EIGHT_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="Ancient Defender", created_at=_EIGHT_DAYS_AGO)

            client = _make_client(db, p_att)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_new_attacker_can_attack_old_defender(self, db: Session):
        """Attacker is <7 days old, target is ≥7 days old → protection only shields defender → 200."""
        try:
            p_att = _player(db, "new_att3")
            p_def = _player(db, "old_def3")

            # New attacker, old defender — guard only applies when attacker is old & defender is new
            n_att = _nation(db, p_att.id, name="Young Aggressor", created_at=_THREE_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="Veteran Defender", created_at=_EIGHT_DAYS_AGO)

            client = _make_client(db, p_att)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            # New attacker vs old defender — only the defender benefits from protection, not attacker
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 3:1 territory ratio gate — HTTP-layer tests
# ---------------------------------------------------------------------------

class TestTerritoryRatioGate:
    """Gate 2: attacker's peak territory count must not exceed 3× the defender's peak count."""

    def test_ratio_4_to_1_blocked(self, db: Session):
        """Attacker max=4, defender max=1 → 4 > 3×1 → 409."""
        try:
            p_att = _player(db, "big_attacker")
            p_def = _player(db, "tiny_defender")

            n_att = _nation(db, p_att.id, name="Big Empire", max_count=4,
                            created_at=_EIGHT_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="Tiny Nation", max_count=1,
                            created_at=_EIGHT_DAYS_AGO)

            client = _make_client(db, p_att)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            assert resp.status_code == 409
            assert "territory ratio" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_ratio_3_to_1_allowed(self, db: Session):
        """Attacker max=3, defender max=1 → 3 ≤ 3×1 → 200."""
        try:
            p_att = _player(db, "med_attacker")
            p_def = _player(db, "small_def")

            n_att = _nation(db, p_att.id, name="Medium Empire", max_count=3,
                            created_at=_EIGHT_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="Small Nation", max_count=1,
                            created_at=_EIGHT_DAYS_AGO)

            client = _make_client(db, p_att)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_ratio_4_to_2_allowed(self, db: Session):
        """Attacker max=4, defender max=2 → 4 ≤ 3×2 → 200."""
        try:
            p_att = _player(db, "large_att")
            p_def = _player(db, "medium_def")

            n_att = _nation(db, p_att.id, name="Large Empire", max_count=4,
                            created_at=_EIGHT_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="Medium Nation", max_count=2,
                            created_at=_EIGHT_DAYS_AGO)

            client = _make_client(db, p_att)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_ratio_1_to_1_default_allowed(self, db: Session):
        """Both nations at default max=1 (fresh nations) → 1 ≤ 3×1 → 200."""
        try:
            p_att = _player(db, "fresh_att")
            p_def = _player(db, "fresh_def")

            n_att = _nation(db, p_att.id, name="Fresh Attacker", max_count=1,
                            created_at=_EIGHT_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="Fresh Defender", max_count=1,
                            created_at=_EIGHT_DAYS_AGO)

            client = _make_client(db, p_att)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_ratio_boundary_exactly_3x_is_allowed(self, db: Session):
        """Attacker max=9, defender max=3 → 9 = 3×3 (not strictly greater) → 200."""
        try:
            p_att = _player(db, "exact_att")
            p_def = _player(db, "exact_def")

            n_att = _nation(db, p_att.id, name="Nine Territory Empire", max_count=9,
                            created_at=_EIGHT_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="Three Territory Nation", max_count=3,
                            created_at=_EIGHT_DAYS_AGO)

            client = _make_client(db, p_att)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_ratio_10_to_3_blocked(self, db: Session):
        """Attacker max=10, defender max=3 → 10 > 3×3 → 409."""
        try:
            p_att = _player(db, "huge_att")
            p_def = _player(db, "triple_def")

            n_att = _nation(db, p_att.id, name="Vast Empire", max_count=10,
                            created_at=_EIGHT_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="Triple Nation", max_count=3,
                            created_at=_EIGHT_DAYS_AGO)

            client = _make_client(db, p_att)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            assert resp.status_code == 409
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# max_colonized_territory_count tracking — direct ORM + HTTP tests
# ---------------------------------------------------------------------------

class TestMaxColonizedTerritoryCountTracking:
    """Verify the max_colonized_territory_count column is maintained correctly."""

    def test_nation_creation_sets_max_to_1(self, db: Session):
        """POST /api/nations with a valid home territory results in max_count == 1."""
        try:
            p = _player(db, "new_nation_player")
            token = create_access_token(p.id)
            app.dependency_overrides[get_db] = _override_factory(db)

            # Create a home territory that can be claimed
            home_t = _territory(db, "10,10", nation_id=None, colonized=False)

            client = TestClient(app, raise_server_exceptions=True)
            client.cookies.set("session", token)
            resp = client.post("/api/nations", json={
                "name": "Brand New Nation",
                "currency_name": "Credits",
                "flag_color": "#FF0000",
                "home_territory_id": home_t.id,
                "home_planet_name": "New Home",
            })
            assert resp.status_code == 201

            db.expire_all()
            nation = db.query(Nation).filter(Nation.player_id == p.id).first()
            assert nation is not None
            assert nation.max_colonized_territory_count == 1
        finally:
            app.dependency_overrides.clear()

    def test_claim_territory_increments_max_count(self, db: Session):
        """After claiming a 2nd territory via /fleets/{id}/claim, max rises to 2."""
        try:
            p = _player(db, "claimer")
            n = _nation(db, p.id, name="Expanding Nation", max_count=1,
                        created_at=_EIGHT_DAYS_AGO)

            home_t = _territory(db, "0,0", n.id, colonized=True)
            unclaimed_t = _territory(db, "1,0", nation_id=None, colonized=False)

            # Station a fleet at the unclaimed territory (simulate arrival)
            fleet = Fleet(
                nation_id=n.id,
                origin_territory=unclaimed_t.id,
                unit_count=5,
                status="stationed",
                standing_order="hold",
            )
            db.add(fleet)
            db.flush()

            client = _make_client(db, p)
            resp = client.post(f"/api/military/fleets/{fleet.id}/claim")
            assert resp.status_code == 200

            db.expire_all()
            db.refresh(n)
            assert n.max_colonized_territory_count == 2
        finally:
            app.dependency_overrides.clear()

    def test_max_count_does_not_decrease_after_territory_loss(self, db: Session):
        """
        Peak count is immutable downward.
        Manually reassign a territory away from the nation; max_count stays at its peak.
        """
        p = _player(db, "loser")
        # Nation that once had 3 territories — peak is 3
        n = _nation(db, p.id, name="Former Empire", max_count=3,
                    created_at=_EIGHT_DAYS_AGO)

        # Create 3 colonized territories, then transfer one away
        t1 = _territory(db, "0,0", n.id, colonized=True)
        t2 = _territory(db, "1,0", n.id, colonized=True)
        t3 = _territory(db, "2,0", n.id, colonized=True)

        # Simulate losing t3 — nation_id set to None (uncolonized or taken)
        t3.nation_id = None
        t3.is_owned = False
        db.flush()

        db.refresh(n)
        # max_count must remain at 3 (not drop to 2)
        assert n.max_colonized_territory_count == 3

    def test_max_count_does_not_decrease_when_conquered_by_enemy(self, db: Session):
        """
        Conquest sets territory.nation_id to attacker; the original owner's max_count stays put.
        """
        p_owner = _player(db, "original_owner")
        p_conqueror = _player(db, "conqueror_player")

        n_owner = _nation(db, p_owner.id, name="Conquered Empire", max_count=3,
                          created_at=_EIGHT_DAYS_AGO)
        n_conqueror = _nation(db, p_conqueror.id, name="Expanding Conqueror", max_count=1,
                              created_at=_EIGHT_DAYS_AGO)

        t1 = _territory(db, "0,0", n_owner.id, colonized=True)
        t2 = _territory(db, "1,0", n_owner.id, colonized=True)
        t3 = _territory(db, "2,0", n_owner.id, colonized=True)

        # Simulate conquest: transfer t3 to conqueror
        t3.nation_id = n_conqueror.id
        db.flush()

        db.refresh(n_owner)
        assert n_owner.max_colonized_territory_count == 3  # unchanged


# ---------------------------------------------------------------------------
# Combined scenario: ratio gate uses peak count, not current count
# ---------------------------------------------------------------------------

class TestRatioGateUsesPeakCount:
    """
    The ratio gate must use max_colonized_territory_count (peak),
    not the live count of currently-owned territories.

    Scenario: attacker had max=4, now owns only 1 territory after losing 3.
    If the gate checked live count (1), the attack on a max=1 defender would pass.
    If the gate checks peak count (4 > 3×1 = 3), it must block with 409.
    """

    def test_ratio_gate_uses_peak_not_current(self, db: Session):
        """
        Attacker: max_colonized_territory_count=4 but currently owns 1.
        Defender: max=1.
        Attack must be blocked (peak 4 > 3×1) even though current count is 1.
        """
        try:
            p_att = _player(db, "shrunken_att")
            p_def = _player(db, "small_def2")

            # Attacker still has max=4 recorded from peak expansion
            n_att = _nation(db, p_att.id, name="Shrunken Empire", max_count=4,
                            created_at=_EIGHT_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="Small Defender Nation", max_count=1,
                            created_at=_EIGHT_DAYS_AGO)

            # Attacker now only holds 1 territory (lost the other 3)
            home = _territory(db, "0,0", n_att.id, colonized=True)
            # Territories that were lost — now unowned
            _territory(db, "1,0", nation_id=None, colonized=False)
            _territory(db, "2,0", nation_id=None, colonized=False)
            _territory(db, "3,0", nation_id=None, colonized=False)

            client = _make_client(db, p_att)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            # Peak count 4 > 3×1, must be blocked
            assert resp.status_code == 409
            assert "territory ratio" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_both_gates_blocked_simultaneously_returns_409(self, db: Session):
        """
        When both gates would fire, the response is still 409.
        Implementation may check either gate first; we just assert rejection.
        """
        try:
            p_att = _player(db, "double_blocked_att")
            p_def = _player(db, "double_blocked_def")

            # Attacker is old, very large empire; defender is new AND tiny
            n_att = _nation(db, p_att.id, name="Huge Old Empire", max_count=10,
                            created_at=_EIGHT_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="Brand New Tiny", max_count=1,
                            created_at=_THREE_DAYS_AGO)

            client = _make_client(db, p_att)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            assert resp.status_code == 409
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Vacation mode gate (pre-existing, confirm it still works alongside new gates)
# ---------------------------------------------------------------------------

class TestVacationModeWarGate:
    """Vacation mode players cannot be targeted — this gate predates the two new gates."""

    def test_cannot_declare_war_on_vacation_player(self, db: Session):
        """Target player in vacation mode → 409 regardless of age or size."""
        try:
            p_att = _player(db, "vac_attacker")
            p_def = _player(db, "vacationing", vacation=True)

            n_att = _nation(db, p_att.id, name="War Hungry", max_count=1,
                            created_at=_EIGHT_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="On Holiday", max_count=1,
                            created_at=_EIGHT_DAYS_AGO)

            client = _make_client(db, p_att)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            assert resp.status_code == 409
            assert "vacation" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_vacation_mode_checked_before_ratio_gate(self, db: Session):
        """
        When target is in vacation mode AND ratio would also block,
        the vacation block fires first (per implementation order).
        Either way the result must be 409 with a vacation-related message.
        """
        try:
            p_att = _player(db, "vac_ratio_att")
            p_def = _player(db, "vac_ratio_def", vacation=True)

            # Big attacker, tiny defender on vacation
            n_att = _nation(db, p_att.id, name="Giant Bully", max_count=10,
                            created_at=_EIGHT_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="Resting Nation", max_count=1,
                            created_at=_EIGHT_DAYS_AGO)

            client = _make_client(db, p_att)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            assert resp.status_code == 409
            assert "vacation" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------

class TestAuthEnforcement:
    """Unauthenticated requests to the diplomacy set_relation endpoint return 401."""

    def test_unauthenticated_war_declaration_returns_401(self, db: Session):
        try:
            p = _player(db, "auth_target")
            n = _nation(db, p.id, name="Auth Target Nation", created_at=_EIGHT_DAYS_AGO)

            app.dependency_overrides[get_db] = _override_factory(db)
            client = TestClient(app, raise_server_exceptions=True)
            # No session cookie set
            resp = client.put(f"/api/diplomacy/{n.id}", json={"status": "war"})
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Self-declaration guard
# ---------------------------------------------------------------------------

class TestSelfDeclaration:
    """A nation cannot declare war on itself."""

    def test_cannot_declare_war_on_self(self, db: Session):
        try:
            p = _player(db, "self_war_player")
            n = _nation(db, p.id, name="Self War Nation", created_at=_EIGHT_DAYS_AGO)

            client = _make_client(db, p)
            resp = client.put(f"/api/diplomacy/{n.id}", json={"status": "war"})
            assert resp.status_code == 409
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Target not found
# ---------------------------------------------------------------------------

class TestTargetNotFound:
    """Requesting war against a non-existent nation returns 404."""

    def test_war_on_nonexistent_nation_returns_404(self, db: Session):
        try:
            p = _player(db, "lonely_attacker")
            n = _nation(db, p.id, name="Lonely Empire", created_at=_EIGHT_DAYS_AGO)

            client = _make_client(db, p)
            resp = client.put("/api/diplomacy/999999", json={"status": "war"})
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# War declaration produces war_pending status and event log entry
# ---------------------------------------------------------------------------

class TestWarDeclarationStateTransition:
    """
    A successful war declaration should:
    - Set the diplomacy row to 'war_pending' (not immediately 'war')
    - Log a 'war_declared' event
    - Set war_starts_at to approximately NOW + 4 hours
    """

    def test_successful_declaration_creates_war_pending_status(self, db: Session):
        try:
            p_att = _player(db, "state_att")
            p_def = _player(db, "state_def")

            n_att = _nation(db, p_att.id, name="State Attacker", max_count=1,
                            created_at=_EIGHT_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="State Defender", max_count=1,
                            created_at=_EIGHT_DAYS_AGO)

            client = _make_client(db, p_att)
            before = datetime.now(timezone.utc)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            after = datetime.now(timezone.utc)

            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "war_pending"

            # Verify DB state
            db.expire_all()
            a_id, b_id = min(n_att.id, n_def.id), max(n_att.id, n_def.id)
            row = db.query(Diplomacy).filter(
                Diplomacy.nation_a == a_id,
                Diplomacy.nation_b == b_id,
            ).first()
            assert row is not None
            assert row.status == "war_pending"
            assert row.declared_by == n_att.id

            # war_starts_at should be ~4 hours from now
            assert row.war_starts_at is not None
            expected_low = before + timedelta(hours=4) - timedelta(seconds=5)
            expected_high = after + timedelta(hours=4) + timedelta(seconds=5)
            assert expected_low <= row.war_starts_at <= expected_high
        finally:
            app.dependency_overrides.clear()

    def test_successful_declaration_logs_war_declared_event(self, db: Session):
        try:
            from app.models.event import Event

            p_att = _player(db, "event_att")
            p_def = _player(db, "event_def")

            n_att = _nation(db, p_att.id, name="Event Attacker", max_count=1,
                            created_at=_EIGHT_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="Event Defender", max_count=1,
                            created_at=_EIGHT_DAYS_AGO)

            client = _make_client(db, p_att)
            resp = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            assert resp.status_code == 200

            db.expire_all()
            event = db.query(Event).filter(Event.type == "war_declared").first()
            assert event is not None
            assert event.payload["declaring_nation_id"] == n_att.id
            assert event.payload["target_nation_id"] == n_def.id
        finally:
            app.dependency_overrides.clear()

    def test_redeclaring_war_on_already_war_pending_nation_is_idempotent(self, db: Session):
        """
        Submitting a second war declaration against a nation already at war_pending
        should return 200 with the current status (not error, not double-apply).
        """
        try:
            p_att = _player(db, "idem_att")
            p_def = _player(db, "idem_def")

            n_att = _nation(db, p_att.id, name="Idem Attacker", max_count=1,
                            created_at=_EIGHT_DAYS_AGO)
            n_def = _nation(db, p_def.id, name="Idem Defender", max_count=1,
                            created_at=_EIGHT_DAYS_AGO)

            client = _make_client(db, p_att)
            resp1 = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            assert resp1.status_code == 200

            resp2 = client.put(f"/api/diplomacy/{n_def.id}", json={"status": "war"})
            assert resp2.status_code == 200
            # Should still be war_pending (not duplicated into war or error state)
            assert resp2.json()["status"] in ("war_pending", "war")
        finally:
            app.dependency_overrides.clear()
