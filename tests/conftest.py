"""
Shared test fixtures.

The DATABASE_URL environment variable is set to an in-memory SQLite database
**before** any application modules are imported.  SQLAlchemy's StaticPool is
used so that all connections within a test process share the same in-memory
store.  After each test the tables are truncated so every test starts with a
clean slate.
"""

import os

# Must be set before any app code is imported so that config.py / database.py
# pick up the test URL.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("RAWG_API_KEY", "test_key")
os.environ.setdefault("BCRYPT_ROUNDS", "4")  # fast password hashing in tests

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── import app modules *after* the env-var is set ──────────────────────────
import app.database as db_module
import app.main as main_module
from app.database import Base
from app.main import app
from app.routers.api import get_db as api_get_db
from app.routers.views import get_db as views_get_db

# ---------------------------------------------------------------------------
# Build a shared in-memory SQLite engine for the test session.
# StaticPool ensures all connections (including those created inside the app's
# lifespan) share the same database.
# ---------------------------------------------------------------------------
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Patch the database module so that `init_db()` and other helpers use our
# test engine / session factory.
db_module.engine = test_engine
db_module.SessionLocal = TestingSessionLocal

# Patch main.py's SessionLocal used inside the lifespan (startup / cleanup).
main_module.SessionLocal = TestingSessionLocal

# Create all tables once at import time so the lifespan startup succeeds.
Base.metadata.create_all(bind=test_engine)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DEFAULT_EMAIL = "tester@example.com"
DEFAULT_PASSWORD = "password123"


@pytest.fixture(autouse=True)
def clear_tables():
    """Truncate every table between tests for isolation."""
    yield
    with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture(autouse=True)
def seed_user():
    """Create the default test account before each test (tables are truncated between tests)."""
    from app.auth import hash_password
    from app.models import User

    session = TestingSessionLocal()
    try:
        if not session.query(User).filter(User.email == DEFAULT_EMAIL).first():
            session.add(User(
                email=DEFAULT_EMAIL,
                password_hash=hash_password(DEFAULT_PASSWORD),
                display_name="Tester",
                profile_slug="tester",
            ))
            session.commit()
    finally:
        session.close()
    yield


@pytest.fixture()
def test_user(db):
    """The default logged-in test user."""
    from app.models import User
    return db.query(User).filter(User.email == DEFAULT_EMAIL).first()


@pytest.fixture(autouse=True)
def no_screenshot_fetch():
    """Keep tests hermetic: the game detail page fetches screenshots from RAWG
    for games that have never had them fetched.  Individual tests can re-patch
    ``RawgClient.list_screenshots`` to supply data."""
    from unittest.mock import MagicMock, patch

    with patch("app.rawg.RawgClient.list_screenshots", new=MagicMock(return_value=[])):
        yield


@pytest.fixture()
def db():
    """Provide a SQLAlchemy session backed by the in-memory test database."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db, seed_user):
    """
    FastAPI TestClient using the in-memory test session, logged in as the
    default test user via a real session cookie (so auth middleware,
    dependencies, and templates all see the same user).
    """
    def override_get_db():
        yield db

    app.dependency_overrides[api_get_db] = override_get_db
    app.dependency_overrides[views_get_db] = override_get_db
    with TestClient(app) as c:
        resp = c.post('/login', data={'email': DEFAULT_EMAIL, 'password': DEFAULT_PASSWORD},
                      follow_redirects=False)
        assert resp.status_code == 303, 'test login failed'
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def anon_client(db):
    """A client that is NOT logged in (for testing auth gates)."""
    def override_get_db():
        yield db

    app.dependency_overrides[api_get_db] = override_get_db
    app.dependency_overrides[views_get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
