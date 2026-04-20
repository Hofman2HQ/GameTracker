"""
Tests for SQLAlchemy model properties (Game.genres, Game.platforms).
"""

import json
import pytest
from app.models import Game


class TestGameGenresProperty:
    def test_empty_when_none(self):
        game = Game(rawg_id=1, slug="g", name="G")
        assert game.genres == []

    def test_parses_json(self):
        game = Game(rawg_id=1, slug="g", name="G", genres_json=json.dumps(["RPG", "Action"]))
        assert game.genres == ["RPG", "Action"]

    def test_invalid_json_returns_empty(self):
        game = Game(rawg_id=1, slug="g", name="G", genres_json="NOT_JSON")
        assert game.genres == []

    def test_empty_list(self):
        game = Game(rawg_id=1, slug="g", name="G", genres_json=json.dumps([]))
        assert game.genres == []


class TestGamePlatformsProperty:
    def test_empty_when_none(self):
        game = Game(rawg_id=1, slug="g", name="G")
        assert game.platforms == []

    def test_parses_json(self):
        game = Game(rawg_id=1, slug="g", name="G", platforms_json=json.dumps(["PC", "PS4"]))
        assert game.platforms == ["PC", "PS4"]

    def test_invalid_json_returns_empty(self):
        game = Game(rawg_id=1, slug="g", name="G", platforms_json="{bad json")
        assert game.platforms == []

    def test_empty_list(self):
        game = Game(rawg_id=1, slug="g", name="G", platforms_json=json.dumps([]))
        assert game.platforms == []


class TestGamePersistence:
    """Verify that genres/platforms survive a round-trip through the database."""

    def test_genres_round_trip(self, db):
        game = Game(
            rawg_id=100,
            slug="test",
            name="Test Game",
            genres_json=json.dumps(["RPG", "Adventure"]),
        )
        db.add(game)
        db.commit()
        db.expire(game)
        loaded = db.query(Game).filter_by(rawg_id=100).first()
        assert loaded.genres == ["RPG", "Adventure"]

    def test_platforms_round_trip(self, db):
        game = Game(
            rawg_id=101,
            slug="test2",
            name="Test Game 2",
            platforms_json=json.dumps(["PC", "Xbox"]),
        )
        db.add(game)
        db.commit()
        db.expire(game)
        loaded = db.query(Game).filter_by(rawg_id=101).first()
        assert loaded.platforms == ["PC", "Xbox"]
