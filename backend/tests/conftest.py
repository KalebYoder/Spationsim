import os

# Must be set before any app imports so the engine is built against the test DB
os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/spationsim_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.db.database import Base, get_db
from app.models.player import Player
from app.models.nation import Nation
from app.core.security import create_access_token, hash_password

_engine = create_engine(os.environ["DATABASE_URL"])


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    Base.metadata.drop_all(bind=_engine)
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture()
def db(setup_database):
    conn = _engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    trans.rollback()
    conn.close()


def _override_factory(session):
    def _override():
        yield session
    return _override


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = _override_factory(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def test_player(db):
    player = Player(
        username="testplayer",
        email="test@example.com",
        password_hash=hash_password("testpassword123"),
    )
    db.add(player)
    db.flush()
    return player


@pytest.fixture()
def test_nation(db, test_player):
    nation = Nation(
        player_id=test_player.id,
        name="Test Nation",
        minerals=1000,
        fuel=1000,
    )
    db.add(nation)
    db.flush()
    return nation


@pytest.fixture()
def auth_client(db, test_player):
    token = create_access_token(test_player.id)
    app.dependency_overrides[get_db] = _override_factory(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("session", token)
        yield c
    app.dependency_overrides.clear()
