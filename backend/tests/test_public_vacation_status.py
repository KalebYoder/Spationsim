"""
Test suite for vacation mode fields on the Public Nation Profile endpoint.

Covers the addition of two fields to GET /api/nations/{nation_id}:

    vacation_mode: bool
        Whether the nation's owner is currently in vacation mode.

    vacation_since: str | None
        ISO 8601 timestamp of when vacation started, or null if not in vacation mode.

These fields require a JOIN from Nation.player_id -> Player to retrieve
player.vacation_mode and player.vacation_since.

The schema being augmented is PublicNationResponse in app/schemas/nation.py.

Tests are written BEFORE implementation and are expected to fail until:
  1. PublicNationResponse gains the two new fields.
  2. get_nation_public() joins through to the Player row and populates them.

NOTE: test_public_nation_profile.py section 3 (TestResponseShape) contains
test_response_does_not_include_private_fields which currently asserts vacation_mode
and vacation_since are absent.  That test must be updated by the developer as part
of implementing this feature — it was written before the feature existed.
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
from app.models.nation import Nation
from app.models.player import Player
from app.core.security import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _db_override(session: Session):
    def _override():
        yield session
    return _override


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Local fixtures
#
# The conftest auth_client/test_player pair is used for the "own nation"
# viewing tests and acts as the authenticated viewer in cross-nation tests.
#
# A separate other_player / other_nation pair is used to test viewing a
# DIFFERENT player's nation that is (or is not) in vacation mode.
# ---------------------------------------------------------------------------


@pytest.fixture()
def other_player(db: Session) -> Player:
    """A second player whose vacation state we can manipulate independently."""
    player = Player(
        username="vacationplayer",
        email="vacation@example.com",
        password_hash=hash_password("vacationpassword123"),
        vacation_mode=False,
        vacation_since=None,
    )
    db.add(player)
    db.flush()
    return player


@pytest.fixture()
def other_nation(db: Session, other_player: Player) -> Nation:
    nation = Nation(
        player_id=other_player.id,
        name="Vacation Nation",
        flag_color="#00FF00",
        currency_name="VacationBucks",
        minerals=500,
        fuel=500,
    )
    db.add(nation)
    db.flush()
    return nation


@pytest.fixture()
def auth_client(db: Session, test_player: Player) -> TestClient:
    """Authenticated client for test_player — shadows the conftest fixture so
    both auth_client and the session use the same transactional db session."""
    token = create_access_token(test_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


# ===========================================================================
# 1. FIELD PRESENCE — vacation_mode
# ===========================================================================


class TestVacationModeFieldPresence:
    """vacation_mode must appear in PublicNationResponse for every valid request."""

    def test_vacation_mode_key_is_present_in_response(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """GET /api/nations/{id} must include a 'vacation_mode' key."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "vacation_mode" in data, (
            "PublicNationResponse must include a 'vacation_mode' field; it was absent"
        )

    def test_vacation_mode_is_boolean_type_not_string(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """vacation_mode must be serialized as a JSON boolean, not a string."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "vacation_mode" in data, "vacation_mode key missing from response"
        assert isinstance(data["vacation_mode"], bool), (
            f"vacation_mode must be a bool, got {type(data['vacation_mode'])!r} "
            f"with value {data['vacation_mode']!r}"
        )

    def test_vacation_mode_false_when_player_not_in_vacation(
        self,
        auth_client: TestClient,
        test_nation: Nation,
        test_player: Player,
        db: Session,
    ):
        """vacation_mode must be False for a player whose vacation_mode=False."""
        # Confirm the fixture state is not in vacation
        assert test_player.vacation_mode is False, "test_player fixture must start with vacation_mode=False"

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["vacation_mode"] is False, (
            f"vacation_mode must be False for a non-vacationing player, got {data['vacation_mode']!r}"
        )

    def test_vacation_mode_true_when_player_is_in_vacation(
        self,
        auth_client: TestClient,
        db: Session,
        other_player: Player,
        other_nation: Nation,
    ):
        """vacation_mode must be True when the nation's owner has vacation_mode=True."""
        other_player.vacation_mode = True
        other_player.vacation_since = _utcnow()
        db.flush()

        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["vacation_mode"] is True, (
            f"vacation_mode must be True when player.vacation_mode=True, got {data['vacation_mode']!r}"
        )

    def test_vacation_mode_remains_false_when_vacation_since_is_none(
        self,
        auth_client: TestClient,
        db: Session,
        other_player: Player,
        other_nation: Nation,
    ):
        """vacation_mode=False and vacation_since=None is the canonical non-vacation state."""
        # Explicitly ensure no vacation state
        other_player.vacation_mode = False
        other_player.vacation_since = None
        db.flush()

        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["vacation_mode"] is False, (
            f"vacation_mode must be False when player has no vacation state, got {data['vacation_mode']!r}"
        )


# ===========================================================================
# 2. FIELD PRESENCE — vacation_since
# ===========================================================================


class TestVacationSinceFieldPresence:
    """vacation_since must appear in PublicNationResponse and honour nullability."""

    def test_vacation_since_key_is_present_in_response(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """GET /api/nations/{id} must include a 'vacation_since' key."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "vacation_since" in data, (
            "PublicNationResponse must include a 'vacation_since' field; it was absent"
        )

    def test_vacation_since_is_null_when_not_in_vacation_mode(
        self,
        auth_client: TestClient,
        db: Session,
        other_player: Player,
        other_nation: Nation,
    ):
        """vacation_since must be null (JSON null / Python None) when vacation_mode=False."""
        other_player.vacation_mode = False
        other_player.vacation_since = None
        db.flush()

        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["vacation_since"] is None, (
            f"vacation_since must be null when not in vacation mode, got {data['vacation_since']!r}"
        )

    def test_vacation_since_is_non_null_string_when_in_vacation(
        self,
        auth_client: TestClient,
        db: Session,
        other_player: Player,
        other_nation: Nation,
    ):
        """vacation_since must be a non-null, non-empty string when vacation_mode=True."""
        other_player.vacation_mode = True
        other_player.vacation_since = _utcnow()
        db.flush()

        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["vacation_since"] is not None, (
            "vacation_since must not be null when the player is in vacation mode"
        )
        assert isinstance(data["vacation_since"], str), (
            f"vacation_since must be a string when set, got {type(data['vacation_since'])!r}"
        )
        assert len(data["vacation_since"]) > 0, (
            "vacation_since string must not be empty"
        )

    def test_vacation_since_is_valid_iso8601_when_set(
        self,
        auth_client: TestClient,
        db: Session,
        other_player: Player,
        other_nation: Nation,
    ):
        """vacation_since must be parseable as an ISO 8601 datetime string."""
        vacation_time = _utcnow()
        other_player.vacation_mode = True
        other_player.vacation_since = vacation_time
        db.flush()

        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        raw = data["vacation_since"]
        assert raw is not None, "vacation_since must not be null when vacation_mode=True"

        try:
            # fromisoformat handles the full ISO 8601 format Python produces
            parsed = datetime.fromisoformat(raw)
        except (ValueError, TypeError) as exc:
            pytest.fail(
                f"vacation_since {raw!r} is not a valid ISO 8601 datetime string: {exc}"
            )

        # Must be timezone-aware (offset present)
        assert parsed.tzinfo is not None, (
            f"vacation_since datetime must be timezone-aware, got tzinfo=None for {raw!r}"
        )

    def test_vacation_since_value_matches_time_vacation_was_entered(
        self,
        auth_client: TestClient,
        db: Session,
        other_player: Player,
        other_nation: Nation,
    ):
        """vacation_since value must be within a few seconds of the time vacation was set."""
        vacation_time = _utcnow()
        other_player.vacation_mode = True
        other_player.vacation_since = vacation_time
        db.flush()

        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        raw = data["vacation_since"]
        parsed = datetime.fromisoformat(raw)

        # Normalise to UTC for comparison
        if parsed.tzinfo is not None:
            parsed_utc = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            parsed_utc = parsed

        vacation_utc = vacation_time.replace(tzinfo=None)
        delta = abs((parsed_utc - vacation_utc).total_seconds())

        assert delta < 5, (
            f"vacation_since must be within 5 seconds of the stored value. "
            f"Expected ~{vacation_time.isoformat()}, got {raw!r} "
            f"(delta={delta:.2f}s)"
        )

    def test_vacation_since_null_for_own_nation_not_in_vacation(
        self,
        auth_client: TestClient,
        test_nation: Nation,
        test_player: Player,
    ):
        """Viewing your own nation when not in vacation returns vacation_since=null."""
        # test_player.vacation_mode is False by fixture default
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["vacation_since"] is None, (
            f"vacation_since must be null for non-vacationing player, got {data['vacation_since']!r}"
        )


# ===========================================================================
# 3. INTERACTION WITH EXISTING FIELDS
# ===========================================================================


class TestExistingFieldsUnaffected:
    """Adding vacation fields must not remove or corrupt the existing public fields."""

    def test_id_field_still_present_alongside_vacation_fields(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """'id' must still be present after vacation fields are added."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "id" in data, "'id' must remain present in PublicNationResponse"
        assert data["id"] == test_nation.id

    def test_name_field_still_present_alongside_vacation_fields(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """'name' must still be present after vacation fields are added."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "name" in data, "'name' must remain present in PublicNationResponse"
        assert data["name"] == test_nation.name

    def test_territory_count_still_present_alongside_vacation_fields(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """'territory_count' must still be present after vacation fields are added."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "territory_count" in data, (
            "'territory_count' must remain present in PublicNationResponse"
        )
        assert isinstance(data["territory_count"], int)

    def test_military_field_still_present_alongside_vacation_fields(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """'military' must still be present after vacation fields are added."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "military" in data, "'military' must remain present in PublicNationResponse"
        assert isinstance(data["military"], dict)
        assert "starfighter" in data["military"], (
            "'military.starfighter' must still be present after vacation fields are added"
        )

    def test_private_resource_fields_still_absent(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """Adding vacation fields must not accidentally expose private resource fields."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        for field in ("minerals", "fuel", "currency"):
            assert field not in data, (
                f"Private field '{field}' must NOT be present in PublicNationResponse"
            )

    def test_aggression_lockout_until_still_absent(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """aggression_lockout_until is a private field and must remain absent."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "aggression_lockout_until" not in data, (
            "'aggression_lockout_until' is private and must NOT appear in PublicNationResponse"
        )

    def test_home_territory_id_still_absent(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """home_territory_id is a private field and must remain absent."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "home_territory_id" not in data, (
            "'home_territory_id' is private and must NOT appear in PublicNationResponse"
        )

    def test_probes_reserve_still_absent(
        self,
        auth_client: TestClient,
        test_nation: Nation,
    ):
        """probes_reserve is a private field and must remain absent."""
        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "probes_reserve" not in data, (
            "'probes_reserve' is private and must NOT appear in PublicNationResponse"
        )

    def test_all_six_public_fields_present_simultaneously(
        self,
        auth_client: TestClient,
        db: Session,
        other_player: Player,
        other_nation: Nation,
    ):
        """All six public fields must coexist in a single response."""
        other_player.vacation_mode = True
        other_player.vacation_since = _utcnow()
        db.flush()

        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        expected_fields = ("id", "name", "flag_color", "currency_name",
                           "territory_count", "military",
                           "vacation_mode", "vacation_since")
        missing = [f for f in expected_fields if f not in data]
        assert not missing, (
            f"The following fields are missing from PublicNationResponse: {missing}"
        )


# ===========================================================================
# 4. OWN NATION — VACATION STATE VISIBLE ON SELF-VIEW
# ===========================================================================


class TestOwnNationVacationVisibility:
    """A player viewing their own nation via the public endpoint must see their own vacation state."""

    def test_own_nation_vacation_mode_false_when_not_in_vacation(
        self,
        auth_client: TestClient,
        test_nation: Nation,
        test_player: Player,
    ):
        """Viewing own nation: vacation_mode must be False when player is not vacationing."""
        assert test_player.vacation_mode is False

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["vacation_mode"] is False, (
            "Viewing own nation: vacation_mode must be False when not vacationing, "
            f"got {data['vacation_mode']!r}"
        )

    def test_own_nation_vacation_mode_true_when_player_is_vacationing(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        test_player: Player,
    ):
        """Viewing own nation: vacation_mode must be True when the viewing player is vacationing."""
        test_player.vacation_mode = True
        test_player.vacation_since = _utcnow()
        db.flush()

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["vacation_mode"] is True, (
            "Viewing own nation while in vacation: vacation_mode must be True, "
            f"got {data['vacation_mode']!r}"
        )

    def test_own_nation_vacation_since_set_when_player_is_vacationing(
        self,
        auth_client: TestClient,
        db: Session,
        test_nation: Nation,
        test_player: Player,
    ):
        """Viewing own nation: vacation_since must be non-null when vacationing."""
        vacation_time = _utcnow()
        test_player.vacation_mode = True
        test_player.vacation_since = vacation_time
        db.flush()

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["vacation_since"] is not None, (
            "Viewing own nation while vacationing: vacation_since must not be null"
        )
        # Also verify it parses correctly
        try:
            datetime.fromisoformat(data["vacation_since"])
        except (ValueError, TypeError) as exc:
            pytest.fail(
                f"Own nation vacation_since {data['vacation_since']!r} is not valid ISO 8601: {exc}"
            )


# ===========================================================================
# 5. CROSS-PLAYER VACATION VISIBILITY
# ===========================================================================


class TestCrossPlayerVacationVisibility:
    """Player A viewing Player B's nation must see Player B's vacation state, not Player A's."""

    def test_viewer_in_vacation_does_not_bleed_into_viewed_nation(
        self,
        auth_client: TestClient,
        db: Session,
        test_player: Player,
        other_player: Player,
        other_nation: Nation,
    ):
        """When viewer (test_player) is in vacation but subject (other_player) is not,
        the response must show vacation_mode=False for the viewed nation."""
        test_player.vacation_mode = True
        test_player.vacation_since = _utcnow()
        other_player.vacation_mode = False
        other_player.vacation_since = None
        db.flush()

        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["vacation_mode"] is False, (
            "vacation_mode must reflect the VIEWED nation's owner, not the viewer. "
            f"Viewer is vacationing but viewed player is not; expected False, got {data['vacation_mode']!r}"
        )
        assert data["vacation_since"] is None, (
            "vacation_since must be null because the VIEWED player is not in vacation. "
            f"Got {data['vacation_since']!r}"
        )

    def test_viewer_not_in_vacation_subject_is_in_vacation(
        self,
        auth_client: TestClient,
        db: Session,
        test_player: Player,
        other_player: Player,
        other_nation: Nation,
    ):
        """When viewer is NOT in vacation but subject IS, vacation_mode must be True."""
        assert test_player.vacation_mode is False  # viewer not in vacation

        vacation_time = _utcnow()
        other_player.vacation_mode = True
        other_player.vacation_since = vacation_time
        db.flush()

        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["vacation_mode"] is True, (
            "vacation_mode must be True because the viewed nation's owner is in vacation. "
            f"Got {data['vacation_mode']!r}"
        )
        assert data["vacation_since"] is not None, (
            "vacation_since must not be null because the viewed nation's owner is in vacation"
        )

    def test_both_players_in_vacation_shows_subject_vacation(
        self,
        auth_client: TestClient,
        db: Session,
        test_player: Player,
        other_player: Player,
        other_nation: Nation,
    ):
        """Both viewer and subject in vacation — response must reflect the SUBJECT's vacation_since."""
        viewer_vacation_time = _utcnow() - timedelta(hours=10)
        subject_vacation_time = _utcnow() - timedelta(hours=3)

        test_player.vacation_mode = True
        test_player.vacation_since = viewer_vacation_time
        other_player.vacation_mode = True
        other_player.vacation_since = subject_vacation_time
        db.flush()

        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["vacation_mode"] is True

        raw = data["vacation_since"]
        assert raw is not None
        parsed = datetime.fromisoformat(raw)
        parsed_utc = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        subject_utc = subject_vacation_time.replace(tzinfo=None)

        # Must match subject, not viewer (viewer started 10h ago, subject 3h ago)
        viewer_utc = viewer_vacation_time.replace(tzinfo=None)
        delta_from_subject = abs((parsed_utc - subject_utc).total_seconds())
        delta_from_viewer = abs((parsed_utc - viewer_utc).total_seconds())

        assert delta_from_subject < 5, (
            f"vacation_since must reflect the VIEWED player's vacation time (subject), "
            f"not the viewer's. Delta from subject={delta_from_subject:.2f}s, "
            f"delta from viewer={delta_from_viewer:.2f}s. Got {raw!r}"
        )


# ===========================================================================
# 6. EDGE CASES
# ===========================================================================


class TestEdgeCases:
    """Edge cases for the vacation fields on the public profile endpoint."""

    def test_vacation_mode_field_not_present_on_404(
        self,
        auth_client: TestClient,
    ):
        """A 404 for a non-existent nation must not return vacation_mode."""
        resp = auth_client.get("/api/nations/999999")
        assert resp.status_code == 404
        data = resp.json()
        # 404 body is an error envelope; it must not accidentally contain vacation_mode
        assert "vacation_mode" not in data or resp.status_code == 404, (
            "A 404 response must not include vacation_mode"
        )

    def test_vacation_mode_false_is_actual_false_not_falsy(
        self,
        auth_client: TestClient,
        test_nation: Nation,
        test_player: Player,
    ):
        """vacation_mode=False must be the boolean False, not 0 or null or empty string."""
        assert test_player.vacation_mode is False

        resp = auth_client.get(f"/api/nations/{test_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        # Python's `is False` enforces type, ruling out 0, None, ""
        assert data["vacation_mode"] is False, (
            f"vacation_mode must be boolean False, not a falsy value. "
            f"Got {data['vacation_mode']!r} ({type(data['vacation_mode'])!r})"
        )

    def test_vacation_mode_true_is_actual_true_not_truthy(
        self,
        auth_client: TestClient,
        db: Session,
        other_player: Player,
        other_nation: Nation,
    ):
        """vacation_mode=True must be the boolean True, not 1 or a non-empty string."""
        other_player.vacation_mode = True
        other_player.vacation_since = _utcnow()
        db.flush()

        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["vacation_mode"] is True, (
            f"vacation_mode must be boolean True, not a truthy value. "
            f"Got {data['vacation_mode']!r} ({type(data['vacation_mode'])!r})"
        )

    def test_unauthenticated_request_still_returns_401(
        self,
        client: TestClient,
        other_nation: Nation,
    ):
        """The vacation fields do not relax auth requirements — 401 still enforced."""
        resp = client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 401, (
            f"Unauthenticated request must return 401 regardless of vacation field addition, "
            f"got {resp.status_code}"
        )

    def test_vacation_since_timezone_is_utc_or_offset_aware(
        self,
        auth_client: TestClient,
        db: Session,
        other_player: Player,
        other_nation: Nation,
    ):
        """vacation_since must include timezone offset information (not naive datetime string)."""
        other_player.vacation_mode = True
        other_player.vacation_since = _utcnow()  # timezone-aware UTC
        db.flush()

        resp = auth_client.get(f"/api/nations/{other_nation.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        raw = data["vacation_since"]
        assert raw is not None

        # A timezone-aware ISO 8601 string must contain either 'Z', '+', or '-'
        # after the time portion (YYYY-MM-DDTHH:MM:SS).
        # Quick check: the string must contain timezone indicator
        has_tz = (
            raw.endswith("Z")
            or "+" in raw[10:]   # after the date portion to avoid matching date '-'
            or (raw.count("-") > 2)  # more than just the date separators
        )
        assert has_tz, (
            f"vacation_since must be a timezone-aware ISO 8601 string (include offset). "
            f"Got {raw!r} which does not contain a recognisable timezone indicator."
        )
        # Belt-and-suspenders: fromisoformat must produce timezone-aware datetime
        parsed = datetime.fromisoformat(raw)
        assert parsed.tzinfo is not None, (
            f"Parsed vacation_since must be timezone-aware, got tzinfo=None for {raw!r}"
        )
