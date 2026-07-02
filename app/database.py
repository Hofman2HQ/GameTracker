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
            # One entry per game is an invariant; enforce it at the DB level so
            # concurrent adds cannot slip a duplicate past the application check.
            try:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_entries_game_id ON entries (game_id)"
                ))
                conn.commit()
            except OperationalError:
                logger.warning(
                    "Could not create unique index on entries.game_id — "
                    "the database already contains duplicate entries for a game."
                )
