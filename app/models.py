from datetime import datetime
import json
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Float, Boolean
from sqlalchemy.orm import relationship, Mapped, mapped_column
from .database import Base

class Game(Base):
    __tablename__ = 'games'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rawg_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    background_image: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    released: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metacritic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    genres_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    platforms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_rawg_fetch: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    entries: Mapped[list['Entry']] = relationship('Entry', back_populates='game', cascade='all, delete')

    @property
    def genres(self) -> list[str]:
        if not self.genres_json:
            return []
        try:
            return json.loads(self.genres_json)
        except json.JSONDecodeError:
            return []

    @property
    def platforms(self) -> list[str]:
        if not self.platforms_json:
            return []
        try:
            return json.loads(self.platforms_json)
        except json.JSONDecodeError:
            return []


class Entry(Base):
    __tablename__ = 'entries'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey('games.id', ondelete='CASCADE'))
    status: Mapped[str] = mapped_column(String(20), index=True, default='PLAN')
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    hours_played: Mapped[float | None] = mapped_column(Float, nullable=True)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    start_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    game: Mapped['Game'] = relationship('Game', back_populates='entries')


class APICache(Base):
    __tablename__ = 'api_cache'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    cache_key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    cache_type: Mapped[str] = mapped_column(String(50), index=True)
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
