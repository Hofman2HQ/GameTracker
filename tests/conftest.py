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

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

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

@pytest.fixture(autouse=True)
def clear_tables():
    """Truncate every table between tests for isolation."""
    yield
    with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture()
def db():
    """Provide a SQLAlchemy session backed by the in-memory test database."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    """
    FastAPI TestClient with the database dependency overridden to use the
    in-memory test session.  Both the API router and the views router share
    the same session so foreign-key relationships are visible within a test.
    """
    def override_get_db():
        yield db

    app.dependency_overrides[api_get_db] = override_get_db
    app.dependency_overrides[views_get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
