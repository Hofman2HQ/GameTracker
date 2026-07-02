"""
Tests for the HTML view routes in app/routers/views.py.

These tests verify HTTP status codes, redirects, and the presence of key
content in rendered responses.  RAWG HTTP calls are mocked where needed.
"""

import json
from unittest.mock import MagicMock, patch

from app.models import Entry, Game, User
from app.timeutil import utcnow


def _uid(db):
    return db.query(User).filter(User.email == "tester@example.com").first().id

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game(db, rawg_id=1, name="Test Game", slug="test-game",
               genres=None, platforms=None, released="2020-01-01",
               description="A test game."):
    game = Game(
        rawg_id=rawg_id,
        slug=slug,
        name=name,
        genres_json=json.dumps(genres or ["Action"]),
        platforms_json=json.dumps(platforms or ["PC"]),
        released=released,
        description=description,
        last_rawg_fetch=utcnow(),
    )
    db.add(game)
    db.flush()
    entry = Entry(user_id=_uid(db), game_id=game.id, status="PLAN")
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return game, entry


RAWG_GAME_RESPONSE = {
    "id": 777,
    "slug": "new-game",
    "name": "New Game",
    "background_image": None,
    "released": "2020-01-01",
    "metacritic": 80,
    "description_raw": "A new game.",
    "genres": [{"name": "Action"}],
    "platforms": [{"platform": {"name": "PC"}}],
}

PLATFORMS_RESPONSE = [{"id": 1, "name": "PC"}]
GENRES_RESPONSE = [{"id": 4, "name": "Action", "slug": "action"}]


# ---------------------------------------------------------------------------
# GET /  →  redirect to /list
# ---------------------------------------------------------------------------

class TestHomeRedirect:
    def test_redirects_to_list(self, client):
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/list"


# ---------------------------------------------------------------------------
# GET /list
# ---------------------------------------------------------------------------

class TestListView:
    def test_empty_library(self, client):
        r = client.get("/list")
        assert r.status_code == 200

    def test_entries_appear(self, client, db):
        _make_game(db, rawg_id=1, name="My Favourite Game")
        r = client.get("/list")
        assert r.status_code == 200
        assert "My Favourite Game" in r.text

    def test_filter_by_status(self, client, db):
        game1, entry1 = _make_game(db, rawg_id=1, name="Plan Game")
        game2, entry2 = _make_game(db, rawg_id=2, name="Playing Game")
        entry2.status = "PLAYING"
        db.commit()

        r = client.get("/list?status=PLAYING")
        assert r.status_code == 200
        assert "Playing Game" in r.text
        assert "Plan Game" not in r.text

    def test_filter_by_hours_range(self, client, db):
        game1, entry1 = _make_game(db, rawg_id=1, name="Short Game")
        game2, entry2 = _make_game(db, rawg_id=2, name="Long Game")
        entry1.hours_played = 3.0
        entry2.hours_played = 20.0
        db.commit()

        r = client.get("/list?hours=1-6")
        assert r.status_code == 200
        assert "Short Game" in r.text
        assert "Long Game" not in r.text

    def test_sort_alpha(self, client, db):
        _make_game(db, rawg_id=1, name="Zelda")
        _make_game(db, rawg_id=2, name="Alundra")
        r = client.get("/list?sort=alpha")
        assert r.status_code == 200
        # Both names should appear.
        assert "Zelda" in r.text
        assert "Alundra" in r.text


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------

class TestStatsView:
    def test_empty_stats(self, client):
        r = client.get("/stats")
        assert r.status_code == 200

    def test_stats_with_data(self, client, db):
        game, entry = _make_game(db, rawg_id=1, name="Epic Game",
                                  genres=["RPG"], platforms=["PC"])
        entry.status = "COMPLETED"
        entry.rating = 9
        entry.hours_played = 40.0
        db.commit()

        r = client.get("/stats")
        assert r.status_code == 200
        # Completion count should be reflected.
        assert "COMPLETED" in r.text or "40" in r.text


# ---------------------------------------------------------------------------
# GET /search
# ---------------------------------------------------------------------------

class TestSearchView:
    def test_search_page_loads(self, client):
        with (
            patch("app.routers.views.RawgClient.list_platforms",
                  new=MagicMock(return_value=PLATFORMS_RESPONSE)),
            patch("app.routers.views.RawgClient.list_genres",
                  new=MagicMock(return_value=GENRES_RESPONSE)),
            patch("app.routers.views.RawgClient.list_top_games",
                  new=MagicMock(return_value={"results": [], "next": None})),
        ):
            r = client.get("/search")
        assert r.status_code == 200

    def test_search_with_query(self, client):
        search_results = {
            "results": [
                {"id": 1, "name": "The Witcher 3", "metacritic": 92,
                 "ratings_count": 5000, "added": 10000,
                 "background_image": None, "released": "2015-05-19",
                 "genres": [{"name": "RPG"}],
                 "platforms": [{"platform": {"name": "PC"}}]},
            ],
            "next": None,
        }
        with (
            patch("app.routers.views.RawgClient.list_platforms",
                  new=MagicMock(return_value=PLATFORMS_RESPONSE)),
            patch("app.routers.views.RawgClient.list_genres",
                  new=MagicMock(return_value=GENRES_RESPONSE)),
            patch("app.routers.views.RawgClient.search_games",
                  new=MagicMock(return_value=search_results)),
        ):
            r = client.get("/search?q=witcher")
        assert r.status_code == 200
        assert "The Witcher 3" in r.text


# ---------------------------------------------------------------------------
# GET /game/{rawg_id}
# ---------------------------------------------------------------------------

class TestGameDetailView:
    def test_existing_game(self, client, db):
        _make_game(db, rawg_id=1, name="Known Game")
        r = client.get("/game/1")
        assert r.status_code == 200
        assert "Known Game" in r.text

    def test_unknown_game_fetches_from_rawg(self, client):
        with patch(
            "app.routers.views.RawgClient.get_game",
            new=MagicMock(return_value=RAWG_GAME_RESPONSE),
        ):
            r = client.get("/game/777")
        assert r.status_code == 200
        assert "New Game" in r.text


# ---------------------------------------------------------------------------
# POST /add
# ---------------------------------------------------------------------------

class TestAddFromSearch:
    def test_adds_game_and_redirects(self, client):
        with patch(
            "app.routers.views.RawgClient.get_game",
            new=MagicMock(return_value=RAWG_GAME_RESPONSE),
        ):
            r = client.post("/add", data={"rawg_id": 777}, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/game/777"

    def test_duplicate_add_still_redirects(self, client, db):
        _make_game(db, rawg_id=1, name="Already Added")
        with patch(
            "app.routers.views.RawgClient.get_game",
            new=MagicMock(return_value={**RAWG_GAME_RESPONSE, "id": 1}),
        ):
            r = client.post("/add", data={"rawg_id": 1}, follow_redirects=False)
        assert r.status_code == 303


# ---------------------------------------------------------------------------
# POST /entries/{entry_id}/update
# ---------------------------------------------------------------------------

class TestUpdateEntryView:
    def test_update_status(self, client, db):
        _, entry = _make_game(db, rawg_id=1)
        r = client.post(
            f"/entries/{entry.id}/update",
            data={"status": "PLAYING"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        db.expire(entry)
        assert entry.status == "PLAYING"

    def test_update_with_rating_and_hours(self, client, db):
        _, entry = _make_game(db, rawg_id=1)
        r = client.post(
            f"/entries/{entry.id}/update",
            data={"status": "COMPLETED", "rating": "8", "hours_played": "35"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        db.expire(entry)
        assert entry.rating == 8
        assert entry.hours_played == 35.0

    def test_plan_status_clears_rating(self, client, db):
        _, entry = _make_game(db, rawg_id=1)
        entry.rating = 7
        entry.hours_played = 10.0
        db.commit()

        r = client.post(
            f"/entries/{entry.id}/update",
            data={"status": "PLAN"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        db.expire(entry)
        assert entry.rating is None
        assert entry.hours_played is None

    def test_nonexistent_entry_redirects(self, client):
        r = client.post(
            "/entries/9999/update",
            data={"status": "PLAN"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/list"


# ---------------------------------------------------------------------------
# POST /entries/{entry_id}/delete
# ---------------------------------------------------------------------------

class TestDeleteEntryView:
    def test_delete_redirects_to_game(self, client, db):
        game, entry = _make_game(db, rawg_id=1)
        r = client.post(f"/entries/{entry.id}/delete", follow_redirects=False)
        assert r.status_code == 303
        assert "/game/1" in r.headers["location"]

    def test_delete_nonexistent_redirects_to_list(self, client):
        r = client.post("/entries/9999/delete", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/list"

    def test_entry_removed_from_db(self, client, db):
        game, entry = _make_game(db, rawg_id=1)
        entry_id = entry.id
        client.post(f"/entries/{entry_id}/delete")
        assert db.query(Entry).filter_by(id=entry_id).first() is None


# ---------------------------------------------------------------------------
# GET /recommendations (view)
# ---------------------------------------------------------------------------

class TestRecommendationsView:
    def test_page_loads_empty_library(self, client):
        with (
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=GENRES_RESPONSE)),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=PLATFORMS_RESPONSE)),
            patch("app.recommendations.RawgClient.list_top_games",
                  new=MagicMock(return_value={"results": [], "next": None})),
        ):
            r = client.get("/recommendations")
        assert r.status_code == 200
