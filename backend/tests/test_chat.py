"""
Test suite for the Chat system.

Covers:
  1. Send message — public channel, DM channel, unauthorized channel blocked
  2. Get messages — public history, after_id polling, DM access control
  3. DM channels list — returns channels this nation participated in
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
from app.models.chat_message import ChatMessage
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


def _make_chat(db: Session, nation: Nation, channel: str, content: str = "hello") -> ChatMessage:
    m = ChatMessage(channel=channel, sender_nation_id=nation.id, content=content)
    db.add(m)
    db.flush()
    return m


def _dm_channel(id1: int, id2: int) -> str:
    return f"dm_{min(id1, id2)}_{max(id1, id2)}"


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
# 1. SEND MESSAGE
# ===========================================================================


class TestSendMessage:

    def test_send_to_public_channel(self, db, auth_client, my_nation):
        db.commit()
        resp = auth_client.post("/api/chat/messages", json={
            "channel": "general",
            "content": "Hello world",
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["channel"] == "general"
        assert data["content"] == "Hello world"
        assert data["sender_nation_name"] == "My Nation"

    def test_send_to_own_dm_channel(self, db, auth_client, my_nation, other_nation):
        db.commit()
        channel = _dm_channel(my_nation.id, other_nation.id)
        resp = auth_client.post("/api/chat/messages", json={
            "channel": channel,
            "content": "Private message",
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["channel"] == channel

    def test_cannot_send_to_others_dm_channel(self, db, auth_client, my_nation):
        # Create two other nations whose DM channel my_nation is not part of
        p2 = _make_player(db, "p2")
        n2 = _make_nation(db, p2, "Nation2")
        p3 = _make_player(db, "p3")
        n3 = _make_nation(db, p3, "Nation3")
        db.commit()
        channel = _dm_channel(n2.id, n3.id)
        resp = auth_client.post("/api/chat/messages", json={
            "channel": channel,
            "content": "Sneaky",
        })
        assert resp.status_code == 403

    def test_cannot_send_to_arbitrary_channel(self, db, auth_client, my_nation):
        db.commit()
        resp = auth_client.post("/api/chat/messages", json={
            "channel": "secret_admin_channel",
            "content": "Hack",
        })
        assert resp.status_code == 403

    def test_send_to_trade_public_channel(self, db, auth_client, my_nation):
        db.commit()
        resp = auth_client.post("/api/chat/messages", json={
            "channel": "trade",
            "content": "Selling fuel",
        })
        assert resp.status_code == 201


# ===========================================================================
# 2. GET MESSAGES
# ===========================================================================


class TestGetMessages:

    def test_get_public_messages(self, db, auth_client, my_nation):
        _make_chat(db, my_nation, "general", "First message")
        _make_chat(db, my_nation, "general", "Second message")
        db.commit()
        resp = auth_client.get("/api/chat/messages?channel=general")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) == 2
        assert data[0]["content"] == "First message"
        assert data[1]["content"] == "Second message"

    def test_after_id_returns_only_newer(self, db, auth_client, my_nation):
        m1 = _make_chat(db, my_nation, "general", "Old")
        m2 = _make_chat(db, my_nation, "general", "New")
        db.commit()
        resp = auth_client.get(f"/api/chat/messages?channel=general&after_id={m1.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == m2.id

    def test_dm_only_accessible_by_participants(self, db, auth_client, my_nation, other_nation):
        channel = _dm_channel(my_nation.id, other_nation.id)
        _make_chat(db, my_nation, channel, "DM content")
        db.commit()
        resp = auth_client.get(f"/api/chat/messages?channel={channel}")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_dm_blocked_for_outsider(self, db, auth_client, my_nation):
        p2 = _make_player(db, "p4")
        n2 = _make_nation(db, p2, "Nation4")
        p3 = _make_player(db, "p5")
        n3 = _make_nation(db, p3, "Nation5")
        channel = _dm_channel(n2.id, n3.id)
        _make_chat(db, n2, channel, "Secret")
        db.commit()
        resp = auth_client.get(f"/api/chat/messages?channel={channel}")
        assert resp.status_code == 403


# ===========================================================================
# 3. DM CHANNELS LIST
# ===========================================================================


class TestDmChannels:

    def test_returns_channels_nation_participated_in(self, db, auth_client, my_nation, other_nation):
        channel = _dm_channel(my_nation.id, other_nation.id)
        _make_chat(db, my_nation, channel, "Hi")
        db.commit()
        resp = auth_client.get("/api/chat/dm-channels")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) == 1
        assert data[0]["channel"] == channel
        assert data[0]["other_nation_id"] == other_nation.id
        assert data[0]["other_nation_name"] == "Other Nation"

    def test_returns_channel_where_nation_is_recipient(self, db, auth_client, my_nation, other_nation):
        channel = _dm_channel(my_nation.id, other_nation.id)
        _make_chat(db, other_nation, channel, "From other")
        db.commit()
        resp = auth_client.get("/api/chat/dm-channels")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_no_channels_when_no_dms(self, db, auth_client, my_nation):
        db.commit()
        resp = auth_client.get("/api/chat/dm-channels")
        assert resp.status_code == 200
        assert resp.json() == []
