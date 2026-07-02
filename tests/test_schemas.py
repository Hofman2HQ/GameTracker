"""
Tests for Pydantic schemas in app/schemas.py.
"""

import pytest
from pydantic import ValidationError

from app.schemas import EntryBase, EntryCreate, EntryUpdate, GameBase

# ---------------------------------------------------------------------------
# EntryBase / EntryCreate validation
# ---------------------------------------------------------------------------

class TestEntryBaseValidation:
    def test_defaults(self):
        entry = EntryBase()
        assert entry.status == "PLAN"
        assert entry.rating is None
        assert entry.hours_played is None
        assert entry.favorite is False

    def test_valid_rating(self):
        entry = EntryBase(rating=7)
        assert entry.rating == 7

    def test_rating_zero_is_valid(self):
        entry = EntryBase(rating=0)
        assert entry.rating == 0

    def test_rating_ten_is_valid(self):
        entry = EntryBase(rating=10)
        assert entry.rating == 10

    def test_rating_above_ten_fails(self):
        with pytest.raises(ValidationError):
            EntryBase(rating=11)

    def test_rating_below_zero_fails(self):
        with pytest.raises(ValidationError):
            EntryBase(rating=-1)

    def test_hours_played_zero_is_valid(self):
        entry = EntryBase(hours_played=0.0)
        assert entry.hours_played == 0.0

    def test_hours_played_negative_fails(self):
        with pytest.raises(ValidationError):
            EntryBase(hours_played=-1.0)

    def test_all_fields(self):
        entry = EntryBase(
            status="COMPLETED",
            rating=9,
            comment="Great game",
            hours_played=45.5,
            favorite=True,
            start_date="2024-01-01",
            end_date="2024-02-15",
        )
        assert entry.status == "COMPLETED"
        assert entry.rating == 9
        assert entry.hours_played == 45.5
        assert entry.favorite is True


class TestEntryCreateValidation:
    def test_requires_rawg_id(self):
        with pytest.raises(ValidationError):
            EntryCreate()  # rawg_id is required

    def test_valid(self):
        entry = EntryCreate(rawg_id=12345)
        assert entry.rawg_id == 12345
        assert entry.status == "PLAN"


class TestEntryUpdateValidation:
    def test_all_optional(self):
        # EntryUpdate inherits from EntryBase, so all fields have defaults.
        update = EntryUpdate()
        assert update.status == "PLAN"


# ---------------------------------------------------------------------------
# GameBase
# ---------------------------------------------------------------------------

class TestGameBaseValidation:
    def test_valid(self):
        game = GameBase(rawg_id=1, slug="witcher-3", name="The Witcher 3")
        assert game.name == "The Witcher 3"

    def test_requires_rawg_id(self):
        with pytest.raises(ValidationError):
            GameBase(slug="witcher-3", name="The Witcher 3")

    def test_optional_fields_default_to_none(self):
        game = GameBase(rawg_id=1, slug="game", name="Game")
        assert game.background_image is None
        assert game.released is None
        assert game.metacritic is None
        assert game.genres is None
        assert game.platforms is None
