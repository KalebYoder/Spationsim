import os

# Must be set before any app imports so the engine is built against the test DB.
# When running inside Docker (docker compose run/exec): DB_PASSWORD comes from env_file,
# and the host is 'db' (the compose service name). TEST_DATABASE_URL overrides everything.
_db_pw = os.getenv("DB_PASSWORD", "SpationDev2026")
os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL",
    f"postgresql://spationsim:{_db_pw}@db/spationsim_test",
)
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.database import Base, get_db
from app.models.player import Player
from app.models.nation import Nation
from app.core.security import create_access_token, hash_password

_engine = create_engine(os.environ["DATABASE_URL"])
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    # DROP SCHEMA handles the circular FK between nations ↔ territories cleanly
    with _engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(bind=_engine)
    yield


@pytest.fixture(autouse=True)
def clean_tables(setup_database):
    # Truncate all tables before each test; CASCADE handles FK ordering
    table_names = ", ".join(f'"{name}"' for name in Base.metadata.tables.keys())
    with _engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture()
def db(clean_tables):
    session = TestingSession()
    yield session
    session.close()


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
