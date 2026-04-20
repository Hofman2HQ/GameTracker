"""
Tests for the JSON API routes in app/routers/api.py.

RAWG HTTP calls are mocked via unittest.mock so that tests are hermetic.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models import Entry, Game


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game(db, rawg_id=1, name="Test Game", slug="test-game",
               genres=None, platforms=None):
    """Insert a Game + Entry row and return both."""
    game = Game(
        rawg_id=rawg_id,
        slug=slug,
        name=name,
        genres_json=json.dumps(genres or []),
        platforms_json=json.dumps(platforms or []),
        last_rawg_fetch=datetime.utcnow(),
    )
    db.add(game)
    db.flush()
    entry = Entry(game_id=game.id, status="PLAN")
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return game, entry


RAWG_GAME_RESPONSE = {
    "id": 999,
    "slug": "new-game",
    "name": "New Game",
    "background_image": None,
    "released": "2020-01-01",
    "metacritic": 80,
    "description_raw": "A new game.",
    "genres": [{"name": "Action"}],
    "platforms": [{"platform": {"name": "PC"}}],
}


# ---------------------------------------------------------------------------
# GET /api/statuses
# ---------------------------------------------------------------------------

class TestListStatuses:
    def test_returns_all_statuses(self, client):
        r = client.get("/api/statuses")
        assert r.status_code == 200
        statuses = r.json()
        assert set(statuses) == {"PLAN", "PLAYING", "COMPLETED", "DROPPED"}


# ---------------------------------------------------------------------------
# GET /api/entries
# ---------------------------------------------------------------------------

class TestListEntries:
    def test_empty_list(self, client):
        r = client.get("/api/entries")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_entries(self, client, db):
        _make_game(db, rawg_id=1, name="Game A")
        _make_game(db, rawg_id=2, name="Game B")
        r = client.get("/api/entries")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_filter_by_status(self, client, db):
        game1, entry1 = _make_game(db, rawg_id=1, name="Game A")
        game2, entry2 = _make_game(db, rawg_id=2, name="Game B")
        # Update one entry to COMPLETED.
        entry2.status = "COMPLETED"
        db.commit()

        r = client.get("/api/entries?status=COMPLETED")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["game"]["name"] == "Game B"

    def test_entry_shape(self, client, db):
        _make_game(db, rawg_id=1, name="Game A", genres=["RPG"], platforms=["PC"])
        r = client.get("/api/entries")
        entry = r.json()[0]
        assert "id" in entry
        assert "status" in entry
        assert "game" in entry
        assert entry["game"]["name"] == "Game A"


# ---------------------------------------------------------------------------
# POST /api/entries
# ---------------------------------------------------------------------------

class TestAddEntry:
    def test_adds_new_entry(self, client, db):
        with patch(
            "app.routers.api.RawgClient.get_game",
            new=AsyncMock(return_value=RAWG_GAME_RESPONSE),
        ):
            r = client.post("/api/entries", json={"rawg_id": 999, "status": "PLAN"})
        assert r.status_code == 200
        body = r.json()
        assert body["game"]["rawg_id"] == 999
        assert body["status"] == "PLAN"

    def test_duplicate_returns_409(self, client, db):
        _make_game(db, rawg_id=1)
        with patch(
            "app.routers.api.RawgClient.get_game",
            new=AsyncMock(return_value={**RAWG_GAME_RESPONSE, "id": 1}),
        ):
            r = client.post("/api/entries", json={"rawg_id": 1, "status": "PLAN"})
        assert r.status_code == 409

    def test_rating_and_fields_stored(self, client, db):
        with patch(
            "app.routers.api.RawgClient.get_game",
            new=AsyncMock(return_value=RAWG_GAME_RESPONSE),
        ):
            r = client.post("/api/entries", json={
                "rawg_id": 999,
                "status": "COMPLETED",
                "rating": 8,
                "hours_played": 50.0,
                "favorite": True,
                "comment": "Loved it",
            })
        assert r.status_code == 200
        body = r.json()
        assert body["rating"] == 8
        assert body["hours_played"] == 50.0
        assert body["favorite"] is True


# ---------------------------------------------------------------------------
# PATCH /api/entries/{entry_id}
# ---------------------------------------------------------------------------

class TestUpdateEntry:
    def test_update_status(self, client, db):
        _, entry = _make_game(db, rawg_id=1)
        r = client.patch(f"/api/entries/{entry.id}", json={"status": "PLAYING"})
        assert r.status_code == 200
        assert r.json()["status"] == "PLAYING"

    def test_update_rating(self, client, db):
        _, entry = _make_game(db, rawg_id=1)
        r = client.patch(f"/api/entries/{entry.id}", json={"rating": 9})
        assert r.status_code == 200
        assert r.json()["rating"] == 9

    def test_update_nonexistent_returns_404(self, client):
        r = client.patch("/api/entries/9999", json={"status": "PLAYING"})
        assert r.status_code == 404

    def test_partial_update_preserves_other_fields(self, client, db):
        _, entry = _make_game(db, rawg_id=1)
        entry.rating = 7
        entry.status = "PLAYING"
        db.commit()

        r = client.patch(f"/api/entries/{entry.id}", json={"comment": "Nice"})
        assert r.status_code == 200
        body = r.json()
        assert body["rating"] == 7
        assert body["status"] == "PLAYING"
        assert body["comment"] == "Nice"


# ---------------------------------------------------------------------------
# DELETE /api/entries/{entry_id}
# ---------------------------------------------------------------------------

class TestDeleteEntry:
    def test_delete_existing(self, client, db):
        _, entry = _make_game(db, rawg_id=1)
        r = client.delete(f"/api/entries/{entry.id}")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        # Verify it's gone.
        assert db.query(Entry).filter_by(id=entry.id).first() is None

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/entries/9999")
        assert r.status_code == 404

    def test_delete_removes_only_target_entry(self, client, db):
        _, entry1 = _make_game(db, rawg_id=1, name="Game 1")
        _, entry2 = _make_game(db, rawg_id=2, name="Game 2")
        client.delete(f"/api/entries/{entry1.id}")
        assert db.query(Entry).count() == 1
        assert db.query(Entry).first().id == entry2.id


# ---------------------------------------------------------------------------
# GET /api/export/csv
# ---------------------------------------------------------------------------

class TestExportCsv:
    def test_empty_export(self, client):
        r = client.get("/api/export/csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        lines = r.text.strip().splitlines()
        # Only the header row.
        assert len(lines) == 1
        assert "game" in lines[0]

    def test_export_with_entries(self, client, db):
        game, entry = _make_game(db, rawg_id=1, name="My Game")
        entry.status = "COMPLETED"
        entry.rating = 9
        entry.hours_played = 20.0
        entry.favorite = True
        entry.comment = "Awesome"
        db.commit()

        r = client.get("/api/export/csv")
        assert r.status_code == 200
        lines = r.text.strip().splitlines()
        assert len(lines) == 2  # header + 1 data row
        data_row = lines[1]
        assert "My Game" in data_row
        assert "COMPLETED" in data_row
        assert "9" in data_row
        assert "yes" in data_row

    def test_export_content_disposition(self, client):
        r = client.get("/api/export/csv")
        assert "attachment" in r.headers.get("content-disposition", "")
        assert "gametracker.csv" in r.headers.get("content-disposition", "")


# ---------------------------------------------------------------------------
# GET /api/search  (mocked RAWG)
# ---------------------------------------------------------------------------

SEARCH_RESPONSE = {
    "results": [
        {"id": 1, "name": "The Witcher 3", "metacritic": 92, "ratings_count": 5000, "added": 10000},
    ],
    "next": None,
}


class TestSearchApi:
    def test_returns_results(self, client):
        with patch(
            "app.routers.api.RawgClient.search_games",
            new=AsyncMock(return_value=SEARCH_RESPONSE),
        ):
            r = client.get("/api/search?query=witcher")
        assert r.status_code == 200
        body = r.json()
        assert "results" in body

    def test_empty_query_calls_list_top_games(self, client):
        with patch(
            "app.routers.api.RawgClient.list_top_games",
            new=AsyncMock(return_value=SEARCH_RESPONSE),
        ) as mock_top:
            r = client.get("/api/search")
        assert r.status_code == 200
        mock_top.assert_called_once()

    def test_autocomplete_mode_empty_query_returns_empty(self, client):
        r_mock = {"results": [], "next": None}
        with patch(
            "app.routers.api.RawgClient.list_top_games",
            new=AsyncMock(return_value=r_mock),
        ):
            r = client.get("/api/search?mode=autocomplete")
        assert r.status_code == 200
        assert r.json() == {"results": []}

    def test_page_size_clamped(self, client):
        with patch(
            "app.routers.api.RawgClient.list_top_games",
            new=AsyncMock(return_value=SEARCH_RESPONSE),
        ) as mock_top:
            client.get("/api/search?page_size=100")
        # page_size is clamped to 40.
        call_kwargs = mock_top.call_args
        assert call_kwargs.kwargs.get("page_size", 40) <= 40
