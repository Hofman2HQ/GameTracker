from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import DB_URL

engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})

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
