"""
Tests for the cache layer in app/cache.py.
"""

import json
from datetime import timedelta

from app.cache import (
    _make_cache_key,
    cleanup_expired_cache,
    get_cached_response,
    is_game_data_fresh,
    set_cached_response,
)
from app.models import APICache, Game
from app.timeutil import utcnow

# ---------------------------------------------------------------------------
# _make_cache_key
# ---------------------------------------------------------------------------

class TestMakeCacheKey:
    def test_deterministic(self):
        k1 = _make_cache_key("search", query="witcher", page=1)
        k2 = _make_cache_key("search", query="witcher", page=1)
        assert k1 == k2

    def test_different_params_give_different_keys(self):
        k1 = _make_cache_key("search", query="witcher")
        k2 = _make_cache_key("search", query="dark souls")
        assert k1 != k2

    def test_different_types_give_different_keys(self):
        k1 = _make_cache_key("search", query="witcher")
        k2 = _make_cache_key("list", query="witcher")
        assert k1 != k2

    def test_key_contains_cache_type_prefix(self):
        k = _make_cache_key("game", id=123)
        assert k.startswith("game:")

    def test_kwargs_order_independent(self):
        k1 = _make_cache_key("search", query="witcher", page=1, page_size=10)
        k2 = _make_cache_key("search", page_size=10, page=1, query="witcher")
        assert k1 == k2


# ---------------------------------------------------------------------------
# get_cached_response / set_cached_response
# ---------------------------------------------------------------------------

class TestGetSetCachedResponse:
    def test_miss_on_empty_db(self, db):
        result = get_cached_response(db, "search", query="witcher")
        assert result is None

    def test_set_and_get(self, db):
        data = {"results": [{"id": 1, "name": "Witcher"}]}
        set_cached_response(db, "search", data, query="witcher")
        result = get_cached_response(db, "search", query="witcher")
        assert result == data

    def test_expired_entry_returns_none(self, db):
        data = {"results": []}
        set_cached_response(db, "search", data, query="old")
        # Manually expire the entry.
        entry = db.query(APICache).first()
        entry.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

        result = get_cached_response(db, "search", query="old")
        assert result is None

    def test_expired_entry_stays_until_cleanup(self, db):
        # Expired entries are filtered out by the query but NOT deleted
        # automatically by get_cached_response; only cleanup_expired_cache
        # removes them.
        data = {"results": []}
        set_cached_response(db, "search", data, query="old")
        entry = db.query(APICache).first()
        entry.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

        result = get_cached_response(db, "search", query="old")
        assert result is None
        # Row is still present; cleanup_expired_cache is responsible for removal.
        assert db.query(APICache).count() == 1

    def test_update_existing_entry(self, db):
        set_cached_response(db, "search", {"v": 1}, query="witcher")
        set_cached_response(db, "search", {"v": 2}, query="witcher")

        # Should still be only one entry.
        assert db.query(APICache).count() == 1
        result = get_cached_response(db, "search", query="witcher")
        assert result == {"v": 2}

    def test_invalid_json_in_cache_returns_none(self, db):
        # Insert a corrupted cache entry directly.
        entry = APICache(
            cache_key=_make_cache_key("search", query="bad"),
            cache_type="search",
            response_json="NOT_VALID_JSON",
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.add(entry)
        db.commit()

        result = get_cached_response(db, "search", query="bad")
        assert result is None

    def test_different_queries_stored_separately(self, db):
        set_cached_response(db, "search", {"q": "witcher"}, query="witcher")
        set_cached_response(db, "search", {"q": "dark"}, query="dark souls")

        assert db.query(APICache).count() == 2
        assert get_cached_response(db, "search", query="witcher") == {"q": "witcher"}
        assert get_cached_response(db, "search", query="dark souls") == {"q": "dark"}


# ---------------------------------------------------------------------------
# cleanup_expired_cache
# ---------------------------------------------------------------------------

class TestCleanupExpiredCache:
    def test_deletes_only_expired(self, db):
        # One fresh entry, one expired entry.
        fresh = APICache(
            cache_key="search:fresh",
            cache_type="search",
            response_json=json.dumps({}),
            expires_at=utcnow() + timedelta(hours=1),
        )
        expired = APICache(
            cache_key="search:expired",
            cache_type="search",
            response_json=json.dumps({}),
            expires_at=utcnow() - timedelta(seconds=1),
        )
        db.add_all([fresh, expired])
        db.commit()

        deleted = cleanup_expired_cache(db)
        assert deleted == 1
        remaining = db.query(APICache).all()
        assert len(remaining) == 1
        assert remaining[0].cache_key == "search:fresh"

    def test_returns_zero_when_nothing_to_clean(self, db):
        assert cleanup_expired_cache(db) == 0

    def test_deletes_all_when_all_expired(self, db):
        for i in range(3):
            db.add(APICache(
                cache_key=f"search:key{i}",
                cache_type="search",
                response_json=json.dumps({}),
                expires_at=utcnow() - timedelta(seconds=1),
            ))
        db.commit()

        deleted = cleanup_expired_cache(db)
        assert deleted == 3
        assert db.query(APICache).count() == 0


# ---------------------------------------------------------------------------
# is_game_data_fresh
# ---------------------------------------------------------------------------

class TestIsGameDataFresh:
    def _make_game(self, last_rawg_fetch=None):
        return Game(
            rawg_id=1,
            slug="test-game",
            name="Test Game",
            last_rawg_fetch=last_rawg_fetch,
        )

    def test_no_fetch_returns_false(self):
        game = self._make_game(last_rawg_fetch=None)
        assert is_game_data_fresh(game) is False

    def test_fresh_data(self):
        game = self._make_game(
            last_rawg_fetch=utcnow() - timedelta(days=1)
        )
        assert is_game_data_fresh(game) is True

    def test_stale_data(self):
        from app.config import settings
        game = self._make_game(
            last_rawg_fetch=utcnow() - timedelta(days=settings.game_refresh_days + 1)
        )
        assert is_game_data_fresh(game) is False

    def test_custom_max_age(self):
        game = self._make_game(
            last_rawg_fetch=utcnow() - timedelta(days=2)
        )
        assert is_game_data_fresh(game, max_age_days=1) is False
        assert is_game_data_fresh(game, max_age_days=3) is True

    def test_exactly_on_boundary_is_stale(self):
        # age.days == max_age_days → NOT fresh (strict less-than check).
        game = self._make_game(
            last_rawg_fetch=utcnow() - timedelta(days=7)
        )
        assert is_game_data_fresh(game, max_age_days=7) is False
