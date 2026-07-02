import logging

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DB_URL

logger = logging.getLogger(__name__)

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)

if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        # WAL lets readers and one writer run concurrently; a generous busy
        # timeout makes writers wait for the lock instead of failing, and
        # NORMAL sync (safe under WAL) shortens how long each write holds it.
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def init_db():
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "sqlite":
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(games)"))
            columns = {row[1] for row in result}
            if "description" not in columns:
                conn.execute(text("ALTER TABLE games ADD COLUMN description TEXT"))
                conn.commit()
            if "last_rawg_fetch" not in columns:
                conn.execute(text("ALTER TABLE games ADD COLUMN last_rawg_fetch DATETIME"))
                conn.commit()
            if "screenshots_json" not in columns:
                conn.execute(text("ALTER TABLE games ADD COLUMN screenshots_json TEXT"))
                conn.commit()
            if "playtime" not in columns:
                conn.execute(text("ALTER TABLE games ADD COLUMN playtime INTEGER"))
                conn.commit()
            if "tba" not in columns:
                conn.execute(text("ALTER TABLE games ADD COLUMN tba BOOLEAN DEFAULT 0"))
                conn.commit()
            _migrate_multiuser(conn)


def _migrate_multiuser(conn):
    """Upgrade a pre-auth database to the multi-user schema in place.

    Adds users.*/entries.user_id/feedback.user_id, assigns all existing rows
    to a single legacy account, and swaps the old global unique indexes for
    per-user ones. Idempotent and best-effort.
    """
    entry_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(entries)"))}
    if "user_id" in entry_cols:
        return  # already migrated

    from .auth import hash_password
    from .timeutil import utcnow

    logger.info("Migrating database to multi-user schema...")
    conn.execute(text("ALTER TABLE entries ADD COLUMN user_id INTEGER"))
    conn.execute(text("ALTER TABLE recommendation_feedback ADD COLUMN user_id INTEGER"))
    conn.commit()

    has_data = conn.execute(text("SELECT COUNT(*) FROM entries")).scalar() or 0
    has_feedback = conn.execute(text("SELECT COUNT(*) FROM recommendation_feedback")).scalar() or 0
    if has_data or has_feedback:
        # Park pre-existing data under a claimable legacy account.
        conn.execute(
            text("INSERT INTO users (email, password_hash, display_name, profile_slug, "
                 "is_public, created_at) VALUES (:e, :p, :d, :s, 0, :t)"),
            {"e": "legacy@local", "p": hash_password("changeme-legacy"),
             "d": "Legacy", "s": "legacy", "t": utcnow()},
        )
        uid = conn.execute(text("SELECT id FROM users WHERE email='legacy@local'")).scalar()
        conn.execute(text("UPDATE entries SET user_id=:u WHERE user_id IS NULL"), {"u": uid})
        conn.execute(text("UPDATE recommendation_feedback SET user_id=:u WHERE user_id IS NULL"),
                     {"u": uid})
        conn.commit()
        logger.warning("Existing data assigned to legacy account 'legacy@local' "
                       "(password 'changeme-legacy') — log in and change it, or reset.")

    # Swap global unique indexes for per-user ones.
    for stmt in (
        "DROP INDEX IF EXISTS uq_entries_game_id",
        "DROP INDEX IF EXISTS ix_recommendation_feedback_rawg_id",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_entries_user_game ON entries (user_id, game_id)",
        "CREATE INDEX IF NOT EXISTS ix_recommendation_feedback_rawg_id "
        "ON recommendation_feedback (rawg_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_feedback_user_rawg "
        "ON recommendation_feedback (user_id, rawg_id)",
        "CREATE INDEX IF NOT EXISTS ix_entries_user_id ON entries (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_recommendation_feedback_user_id "
        "ON recommendation_feedback (user_id)",
    ):
        try:
            conn.execute(text(stmt))
        except OperationalError as exc:
            logger.warning("Migration step skipped (%s): %s", stmt.split()[0:2], exc)
    conn.commit()
