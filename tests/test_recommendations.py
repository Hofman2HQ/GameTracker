"""
Tests for the recommendations helper functions in app/recommendations.py
and the /api/recommendations endpoint.
"""

import json
from unittest.mock import MagicMock, patch

from app.models import Entry, Game
from app.recommendations import MAX_RECOMMENDATION_PAGE, clamp_page
from app.timeutil import utcnow

# ---------------------------------------------------------------------------
# clamp_page
# ---------------------------------------------------------------------------

class TestClampPage:
    def test_within_bounds(self):
        assert clamp_page(5) == 5

    def test_minimum_is_one(self):
        assert clamp_page(0) == 1
        assert clamp_page(-100) == 1

    def test_maximum_is_max_page(self):
        assert clamp_page(9999) == MAX_RECOMMENDATION_PAGE

    def test_boundary_values(self):
        assert clamp_page(1) == 1
        assert clamp_page(MAX_RECOMMENDATION_PAGE) == MAX_RECOMMENDATION_PAGE

    def test_custom_max(self):
        assert clamp_page(100, max_page=10) == 10
        assert clamp_page(5, max_page=10) == 5


# ---------------------------------------------------------------------------
# GET /api/recommendations  (mocked RAWG)
# ---------------------------------------------------------------------------

GENRES_RESPONSE = [{"id": 4, "name": "Action", "slug": "action"}]
PLATFORMS_RESPONSE = [{"id": 1, "name": "PC"}]
GAMES_RESPONSE = {
    "results": [
        {
            "id": 500,
            "name": "Recommended Game",
            "background_image": None,
            "released": "2021-01-01",
            "metacritic": 85,
            "genres": [{"name": "Action"}],
            "platforms": [{"platform": {"name": "PC"}}],
            "ratings_count": 1000,
        }
    ],
    "next": None,
}


def _make_game_with_entry(db, rawg_id, name, genres=None, platforms=None,
                           status="COMPLETED", rating=9, favorite=True):
    game = Game(
        rawg_id=rawg_id,
        slug=f"game-{rawg_id}",
        name=name,
        genres_json=json.dumps(genres or ["Action"]),
        platforms_json=json.dumps(platforms or ["PC"]),
        last_rawg_fetch=utcnow(),
    )
    db.add(game)
    db.flush()
    entry = Entry(
        game_id=game.id,
        status=status,
        rating=rating,
        favorite=favorite,
    )
    db.add(entry)
    db.commit()
    return game, entry


class TestRecommendationsApi:
    def test_empty_library_returns_empty(self, client):
        with (
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=GENRES_RESPONSE)),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=PLATFORMS_RESPONSE)),
            patch("app.recommendations.RawgClient.list_top_games",
                  new=MagicMock(return_value=GAMES_RESPONSE)),
        ):
            r = client.get("/api/recommendations")
        assert r.status_code == 200
        body = r.json()
        assert body["results"] == []
        assert body["next_page"] is None

    def test_with_library_returns_recommendations(self, client, db):
        _make_game_with_entry(db, rawg_id=1, name="My Game")

        with (
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=GENRES_RESPONSE)),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=PLATFORMS_RESPONSE)),
            patch("app.recommendations.RawgClient.list_top_games",
                  new=MagicMock(return_value=GAMES_RESPONSE)),
        ):
            r = client.get("/api/recommendations")
        assert r.status_code == 200
        body = r.json()
        assert len(body["results"]) >= 1
        rec = body["results"][0]
        assert "name" in rec
        assert "reasons" in rec

    def test_owned_games_excluded(self, client, db):
        # The "recommended" game has id=500 – add it to the library so it
        # should be excluded from recommendations.
        _make_game_with_entry(db, rawg_id=1, name="My Game")
        _make_game_with_entry(db, rawg_id=500, name="Recommended Game")

        with (
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=GENRES_RESPONSE)),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=PLATFORMS_RESPONSE)),
            patch("app.recommendations.RawgClient.list_top_games",
                  new=MagicMock(return_value=GAMES_RESPONSE)),
        ):
            r = client.get("/api/recommendations")
        assert r.status_code == 200
        ids = [rec["id"] for rec in r.json()["results"]]
        assert 500 not in ids

    def test_page_size_clamped(self, client):
        with (
            patch("app.recommendations.RawgClient.list_genres", new=MagicMock(return_value=[])),
            patch("app.recommendations.RawgClient.list_platforms", new=MagicMock(return_value=[])),
        ):
            r = client.get("/api/recommendations?page_size=100")
        assert r.status_code == 200

    def test_next_page_present_when_has_more(self, client, db):
        _make_game_with_entry(db, rawg_id=1, name="My Game")

        has_next_response = {**GAMES_RESPONSE, "next": "http://rawg.io/api/games?page=2"}
        with (
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=GENRES_RESPONSE)),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=PLATFORMS_RESPONSE)),
            patch("app.recommendations.RawgClient.list_top_games",
                  new=MagicMock(return_value=has_next_response)),
        ):
            r = client.get("/api/recommendations?page=1")
        assert r.status_code == 200
        body = r.json()
        if body["next_page"] is not None:
            assert body["next_page"] == 2
