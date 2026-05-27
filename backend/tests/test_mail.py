"""
Test suite for the Mail system.

Covers:
  1. Send mail — happy path, self-send blocked, bad recipient
  2. Inbox — shows received messages, excludes deleted
  3. Outbox — shows sent messages, excludes deleted
  4. Read mail — full body returned, marks message as read, access control
  5. Unread count — counts only unread non-deleted inbox messages
  6. Delete mail — soft-deletes for sender and recipient independently
"""

from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    os.getenv("TEST_DATABASE_URL", "postgresql://spationsim:SpationDev2026@db/spationsim_test"),
)
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.db.database import get_db
from app.models.mail_message import MailMessage
from app.models.nation import Nation
from app.models.player import Player
from app.core.security import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_override(session: Session):
    def _override():
        yield session
    return _override


def _make_player(db: Session, username: str) -> Player:
    p = Player(username=username, email=f"{username}@example.com", password_hash=hash_password("pw"))
    db.add(p)
    db.flush()
    return p


def _make_nation(db: Session, player: Player, name: str) -> Nation:
    n = Nation(player_id=player.id, name=name, minerals=0, fuel=0, currency=0)
    db.add(n)
    db.flush()
    return n


def _make_mail(db: Session, from_nation: Nation, to_nation: Nation, subject="Hello", body="World") -> MailMessage:
    m = MailMessage(
        sender_nation_id=from_nation.id,
        recipient_nation_id=to_nation.id,
        subject=subject,
        body=body,
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def my_nation(db: Session, test_player: Player) -> Nation:
    return _make_nation(db, test_player, "My Nation")


@pytest.fixture()
def other_player(db: Session) -> Player:
    return _make_player(db, "other")


@pytest.fixture()
def other_nation(db: Session, other_player: Player) -> Nation:
    return _make_nation(db, other_player, "Other Nation")


@pytest.fixture()
def auth_client(db: Session, test_player: Player):
    token = create_access_token(test_player.id)
    app.dependency_overrides[get_db] = _db_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()


# ===========================================================================
# 1. SEND MAIL
# ===========================================================================


class TestSendMail:

    def test_send_happy_path(self, db, auth_client, my_nation, other_nation):
        db.commit()
        resp = auth_client.post("/api/mail", json={
            "recipient_nation_id": other_nation.id,
            "subject": "Greetings",
            "body": "Hello there.",
        })
        assert resp.status_code == 201, resp.text
        assert "id" in resp.json()

    def test_cannot_send_to_self(self, db, auth_client, my_nation):
        db.commit()
        resp = auth_client.post("/api/mail", json={
            "recipient_nation_id": my_nation.id,
            "subject": "Self-mail",
            "body": "Oops.",
        })
        assert resp.status_code == 409

    def test_unknown_recipient_returns_404(self, db, auth_client, my_nation):
        db.commit()
        resp = auth_client.post("/api/mail", json={
            "recipient_nation_id": 99999,
            "subject": "Nobody",
            "body": "...",
        })
        assert resp.status_code == 404


# ===========================================================================
# 2. INBOX
# ===========================================================================


class TestInbox:

    def test_inbox_returns_received_messages(self, db, auth_client, my_nation, other_nation):
        _make_mail(db, other_nation, my_nation, subject="Test")
        db.commit()
        resp = auth_client.get("/api/mail/inbox")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["subject"] == "Test"
        assert data[0]["sender_nation_name"] == "Other Nation"

    def test_inbox_excludes_deleted(self, db, auth_client, my_nation, other_nation):
        m = _make_mail(db, other_nation, my_nation)
        m.deleted_by_recipient = True
        db.commit()
        resp = auth_client.get("/api/mail/inbox")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_inbox_excludes_outgoing(self, db, auth_client, my_nation, other_nation):
        _make_mail(db, my_nation, other_nation)
        db.commit()
        resp = auth_client.get("/api/mail/inbox")
        assert resp.status_code == 200
        assert resp.json() == []


# ===========================================================================
# 3. OUTBOX
# ===========================================================================


class TestOutbox:

    def test_outbox_returns_sent_messages(self, db, auth_client, my_nation, other_nation):
        _make_mail(db, my_nation, other_nation, subject="Sent")
        db.commit()
        resp = auth_client.get("/api/mail/outbox")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["subject"] == "Sent"

    def test_outbox_excludes_deleted_by_sender(self, db, auth_client, my_nation, other_nation):
        m = _make_mail(db, my_nation, other_nation)
        m.deleted_by_sender = True
        db.commit()
        resp = auth_client.get("/api/mail/outbox")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_outbox_excludes_incoming(self, db, auth_client, my_nation, other_nation):
        _make_mail(db, other_nation, my_nation)
        db.commit()
        resp = auth_client.get("/api/mail/outbox")
        assert resp.status_code == 200
        assert resp.json() == []


# ===========================================================================
# 4. READ MAIL
# ===========================================================================


class TestReadMail:

    def test_read_returns_full_body(self, db, auth_client, my_nation, other_nation):
        m = _make_mail(db, other_nation, my_nation, subject="Hi", body="The body text.")
        db.commit()
        resp = auth_client.get(f"/api/mail/{m.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["body"] == "The body text."
        assert data["subject"] == "Hi"

    def test_reading_marks_as_read(self, db, auth_client, my_nation, other_nation):
        m = _make_mail(db, other_nation, my_nation)
        assert m.read is False
        db.commit()
        auth_client.get(f"/api/mail/{m.id}")
        db.expire(m)
        assert m.read is True

    def test_sender_can_read_their_own_mail(self, db, auth_client, my_nation, other_nation):
        m = _make_mail(db, my_nation, other_nation)
        db.commit()
        resp = auth_client.get(f"/api/mail/{m.id}")
        assert resp.status_code == 200

    def test_third_party_cannot_read(self, db, auth_client, my_nation, other_nation):
        third_p = _make_player(db, "third")
        third_n = _make_nation(db, third_p, "Third")
        m = _make_mail(db, other_nation, third_n)
        db.commit()

        resp = auth_client.get(f"/api/mail/{m.id}")
        assert resp.status_code == 403

    def test_missing_mail_returns_404(self, db, auth_client, my_nation):
        db.commit()
        resp = auth_client.get("/api/mail/99999")
        assert resp.status_code == 404


# ===========================================================================
# 5. UNREAD COUNT
# ===========================================================================


class TestUnreadCount:

    def test_unread_count_returns_correct_number(self, db, auth_client, my_nation, other_nation):
        _make_mail(db, other_nation, my_nation)
        _make_mail(db, other_nation, my_nation)
        db.commit()
        resp = auth_client.get("/api/mail/unread-count")
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

    def test_read_messages_not_counted(self, db, auth_client, my_nation, other_nation):
        m = _make_mail(db, other_nation, my_nation)
        m.read = True
        db.commit()
        resp = auth_client.get("/api/mail/unread-count")
        assert resp.json()["count"] == 0

    def test_deleted_by_recipient_not_counted(self, db, auth_client, my_nation, other_nation):
        m = _make_mail(db, other_nation, my_nation)
        m.deleted_by_recipient = True
        db.commit()
        resp = auth_client.get("/api/mail/unread-count")
        assert resp.json()["count"] == 0

    def test_outgoing_not_counted(self, db, auth_client, my_nation, other_nation):
        _make_mail(db, my_nation, other_nation)
        db.commit()
        resp = auth_client.get("/api/mail/unread-count")
        assert resp.json()["count"] == 0


# ===========================================================================
# 6. DELETE MAIL
# ===========================================================================


class TestDeleteMail:

    def test_recipient_soft_deletes(self, db, auth_client, my_nation, other_nation):
        m = _make_mail(db, other_nation, my_nation)
        db.commit()
        resp = auth_client.delete(f"/api/mail/{m.id}")
        assert resp.status_code == 204
        db.expire(m)
        assert m.deleted_by_recipient is True
        assert m.deleted_by_sender is False

    def test_sender_soft_deletes(self, db, auth_client, my_nation, other_nation):
        m = _make_mail(db, my_nation, other_nation)
        db.commit()
        resp = auth_client.delete(f"/api/mail/{m.id}")
        assert resp.status_code == 204
        db.expire(m)
        assert m.deleted_by_sender is True
        assert m.deleted_by_recipient is False

    def test_third_party_delete_denied(self, db, auth_client, my_nation, other_nation):
        third_p = _make_player(db, "third4")
        third_n = _make_nation(db, third_p, "Third4")
        m = _make_mail(db, other_nation, third_n)
        db.commit()
        resp = auth_client.delete(f"/api/mail/{m.id}")
        assert resp.status_code == 403
