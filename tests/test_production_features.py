"""
Tests for production-hardening features: health check, JSON backup/restore,
input validation, graceful degradation when RAWG is down, and security headers.
"""

import json
from unittest.mock import MagicMock, patch

from app.models import Entry, Game, User
from app.rawg import RawgUnavailableError
from app.timeutil import utcnow


def _uid(db):
    return db.query(User).filter(User.email == "tester@example.com").first().id


def _make_game(db, rawg_id=1, name="Test Game", slug="test-game",
               genres=None, platforms=None):
    game = Game(
        rawg_id=rawg_id,
        slug=slug,
        name=name,
        genres_json=json.dumps(genres or []),
        platforms_json=json.dumps(platforms or []),
        last_rawg_fetch=utcnow(),
    )
    db.add(game)
    db.flush()
    entry = Entry(user_id=_uid(db), game_id=game.id, status="PLAN")
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return game, entry


class TestHealthz:
    def test_healthy(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "version" in body


class TestSecurityHeaders:
    def test_headers_present(self, client):
        r = client.get("/list")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert "Content-Security-Policy" in r.headers
        assert "Referrer-Policy" in r.headers


class TestValidation:
    def test_invalid_status_rejected_on_create(self, client):
        r = client.post("/api/entries", json={"rawg_id": 1, "status": "BOGUS"})
        assert r.status_code == 422

    def test_invalid_status_rejected_on_update(self, client, db):
        _, entry = _make_game(db, rawg_id=1)
        r = client.patch(f"/api/entries/{entry.id}", json={"status": "BOGUS"})
        assert r.status_code == 422

    def test_invalid_date_rejected(self, client, db):
        _, entry = _make_game(db, rawg_id=1)
        r = client.patch(f"/api/entries/{entry.id}", json={"start_date": "not-a-date"})
        assert r.status_code == 422

    def test_valid_date_accepted(self, client, db):
        _, entry = _make_game(db, rawg_id=1)
        r = client.patch(
            f"/api/entries/{entry.id}",
            json={"status": "PLAYING", "start_date": "2024-05-01"},
        )
        assert r.status_code == 200
        assert r.json()["start_date"] == "2024-05-01"


class TestJsonBackup:
    def test_export_shape(self, client, db):
        _, entry = _make_game(db, rawg_id=1, name="Game A", genres=["RPG"], platforms=["PC"])
        entry.status = "COMPLETED"
        entry.rating = 9
        entry.hours_played = 42.0
        entry.favorite = True
        db.commit()

        r = client.get("/api/export/json")
        assert r.status_code == 200
        body = json.loads(r.content)
        assert body["version"] == 1
        assert len(body["entries"]) == 1
        item = body["entries"][0]
        assert item["rawg_id"] == 1
        assert item["name"] == "Game A"
        assert item["status"] == "COMPLETED"
        assert item["rating"] == 9
        assert item["genres"] == ["RPG"]

    def test_roundtrip_restores_entries(self, client, db):
        _, entry = _make_game(db, rawg_id=1, name="Game A", genres=["RPG"], platforms=["PC"])
        entry.status = "COMPLETED"
        entry.rating = 8
        db.commit()

        backup = json.loads(client.get("/api/export/json").content)

        db.query(Entry).delete()
        db.query(Game).delete()
        db.commit()

        r = client.post("/api/import/json", json=backup)
        assert r.status_code == 200
        assert r.json() == {"imported": 1, "skipped": 0}

        entries = client.get("/api/entries").json()
        assert len(entries) == 1
        assert entries[0]["status"] == "COMPLETED"
        assert entries[0]["rating"] == 8
        assert entries[0]["game"]["name"] == "Game A"
        assert entries[0]["game"]["genres"] == ["RPG"]

    def test_import_skips_existing_entries(self, client, db):
        _make_game(db, rawg_id=1, name="Game A")
        payload = {"version": 1, "entries": [
            {"rawg_id": 1, "name": "Game A", "status": "COMPLETED"},
            {"rawg_id": 2, "name": "Game B", "status": "PLAN"},
        ]}
        r = client.post("/api/import/json", json=payload)
        assert r.status_code == 200
        assert r.json() == {"imported": 1, "skipped": 1}
        # The existing entry keeps its original status.
        original = db.query(Entry).join(Game).filter(Game.rawg_id == 1).first()
        assert original.status == "PLAN"

    def test_import_rejects_malformed_payload(self, client):
        r = client.post("/api/import/json", json={"entries": [{"name": "no rawg_id"}]})
        assert r.status_code == 422


class TestGracefulDegradation:
    def test_search_page_renders_banner_when_rawg_down(self, client):
        down = MagicMock(side_effect=RawgUnavailableError("boom"))
        with (
            patch("app.routers.views.RawgClient.list_platforms", new=down),
            patch("app.routers.views.RawgClient.list_genres", new=down),
            patch("app.routers.views.RawgClient.list_top_games", new=down),
        ):
            r = client.get("/search")
        assert r.status_code == 200
        assert "temporarily unavailable" in r.text

    def test_api_search_returns_502_when_rawg_down(self, client):
        down = MagicMock(side_effect=RawgUnavailableError("boom"))
        with patch("app.routers.api.RawgClient.list_top_games", new=down):
            r = client.get("/api/search")
        assert r.status_code == 502
        assert "unreachable" in r.json()["detail"]

    def test_game_detail_renders_error_page_when_rawg_down(self, client):
        down = MagicMock(side_effect=RawgUnavailableError("boom"))
        with patch("app.routers.views.RawgClient.get_game", new=down):
            r = client.get("/game/12345")
        assert r.status_code == 502
        assert "unreachable" in r.text


class TestStatsWithZeroRating:
    def test_rating_zero_does_not_crash_stats(self, client, db):
        _, entry = _make_game(db, rawg_id=1)
        entry.status = "COMPLETED"
        entry.rating = 0
        db.commit()

        r = client.get("/stats")
        assert r.status_code == 200


class TestEntryDateValidation:
    def _released_game(self, db, released="2020-06-15"):
        game = Game(
            rawg_id=50, slug="dated-game", name="Dated Game",
            released=released, last_rawg_fetch=utcnow(),
            genres_json="[]", platforms_json="[]",
        )
        db.add(game)
        db.flush()
        entry = Entry(user_id=_uid(db), game_id=game.id, status="PLAYING")
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return game, entry

    def test_api_rejects_start_before_release(self, client, db):
        _, entry = self._released_game(db)
        r = client.patch(f"/api/entries/{entry.id}", json={"start_date": "2019-01-01"})
        assert r.status_code == 422
        assert "release date" in r.json()["detail"]

    def test_api_rejects_end_before_start(self, client, db):
        _, entry = self._released_game(db)
        r = client.patch(
            f"/api/entries/{entry.id}",
            json={"start_date": "2021-05-01", "end_date": "2021-01-01"},
        )
        assert r.status_code == 422
        assert "before start_date" in r.json()["detail"]

    def test_api_accepts_dates_after_release(self, client, db):
        _, entry = self._released_game(db)
        r = client.patch(
            f"/api/entries/{entry.id}",
            json={"start_date": "2021-01-01", "end_date": "2021-02-01"},
        )
        assert r.status_code == 200

    def test_form_clamps_start_to_release_date(self, client, db):
        _, entry = self._released_game(db)
        r = client.post(f"/entries/{entry.id}/update", data={
            "status": "PLAYING",
            "start_date": "2019-01-01",
            "end_date": "2021-03-01",
        }, follow_redirects=False)
        assert r.status_code == 303
        db.refresh(entry)
        assert entry.start_date == "2020-06-15"  # clamped to release
        assert entry.end_date == "2021-03-01"

    def test_form_clamps_end_to_start(self, client, db):
        _, entry = self._released_game(db)
        r = client.post(f"/entries/{entry.id}/update", data={
            "status": "COMPLETED",
            "start_date": "2021-05-01",
            "end_date": "2021-01-01",
        }, follow_redirects=False)
        assert r.status_code == 303
        db.refresh(entry)
        assert entry.end_date == entry.start_date == "2021-05-01"

    def test_form_redirect_carries_saved_flag(self, client, db):
        _, entry = self._released_game(db)
        r = client.post(f"/entries/{entry.id}/update", data={"status": "PLAYING"},
                        follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].endswith("?saved=1")


class TestScreenshots:
    def test_screenshots_fetched_and_rendered(self, client, db):
        game, _ = TestEntryDateValidation()._released_game(db)
        shots = ["https://media.rawg.io/shot1.jpg", "https://media.rawg.io/shot2.jpg"]
        with patch("app.rawg.RawgClient.list_screenshots", new=MagicMock(return_value=shots)):
            r = client.get(f"/game/{game.rawg_id}")
        assert r.status_code == 200
        assert "shot1.jpg" in r.text
        assert "shot2.jpg" in r.text
        db.refresh(game)
        assert json.loads(game.screenshots_json) == shots

    def test_screenshots_fetched_only_once(self, client, db):
        game, _ = TestEntryDateValidation()._released_game(db)
        mock = MagicMock(return_value=[])
        with patch("app.rawg.RawgClient.list_screenshots", new=mock):
            client.get(f"/game/{game.rawg_id}")
            client.get(f"/game/{game.rawg_id}")
        assert mock.call_count == 1  # second view served from the DB

    def test_screenshot_failure_does_not_break_page(self, client, db):
        game, _ = TestEntryDateValidation()._released_game(db)
        with patch("app.rawg.RawgClient.list_screenshots",
                   new=MagicMock(side_effect=RawgUnavailableError("boom"))):
            r = client.get(f"/game/{game.rawg_id}")
        assert r.status_code == 200


class TestSavedButtonState:
    def test_saved_param_renders_saved_button(self, client, db):
        game, _ = TestEntryDateValidation()._released_game(db)
        r = client.get(f"/game/{game.rawg_id}?saved=1")
        assert r.status_code == 200
        assert "Saved!" in r.text
        assert 'class="save-button is-saved"' in r.text

    def test_without_param_renders_normal_button(self, client, db):
        game, _ = TestEntryDateValidation()._released_game(db)
        r = client.get(f"/game/{game.rawg_id}")
        assert 'class="save-button is-saved"' not in r.text


class TestActiveNav:
    def test_current_page_marked_active(self, client):
        r = client.get("/stats")
        assert '<a href="/stats" class="active" aria-current="page">' in r.text
        # Only one nav item should be active at a time.
        assert r.text.count('aria-current="page"') == 1


class TestRecommendationFeedback:
    GENRES = [{"id": 4, "name": "Action", "slug": "action"},
              {"id": 51, "name": "Indie", "slug": "indie"}]
    PLATFORMS = [{"id": 1, "name": "PC"}]

    def _library(self, db):
        game = Game(
            rawg_id=10, slug="lib-game", name="Library Game",
            genres_json='["Action"]', platforms_json='["PC"]',
            last_rawg_fetch=utcnow(),
        )
        db.add(game)
        db.flush()
        db.add(Entry(user_id=_uid(db), game_id=game.id, status="COMPLETED", rating=9, favorite=True))
        db.commit()

    def _games_response(self, ids_and_genres):
        return {
            "results": [
                {
                    "id": gid,
                    "name": f"Game {gid}",
                    "background_image": None,
                    "released": "2021-01-01",
                    "metacritic": 85,
                    "genres": [{"name": g} for g in genres],
                    "platforms": [{"platform": {"name": "PC"}}],
                }
                for gid, genres in ids_and_genres
            ],
            "next": None,
        }

    def test_feedback_set_toggle_and_switch(self, client):
        payload = {"rawg_id": 77, "name": "Some Game", "genres": ["Indie"],
                   "platforms": ["PC"], "direction": "more"}
        r = client.post("/api/recommendations/feedback", json=payload)
        assert r.status_code == 200
        assert r.json() == {"rawg_id": 77, "direction": "more"}

        # Switching direction updates the row.
        r = client.post("/api/recommendations/feedback", json={**payload, "direction": "less"})
        assert r.json() == {"rawg_id": 77, "direction": "less"}

        # Clicking the same direction again clears the feedback.
        r = client.post("/api/recommendations/feedback", json={**payload, "direction": "less"})
        assert r.json() == {"rawg_id": 77, "direction": None}

    def test_feedback_rejects_bad_direction(self, client):
        r = client.post("/api/recommendations/feedback",
                        json={"rawg_id": 1, "direction": "sideways"})
        assert r.status_code == 422

    def test_downvoted_game_excluded_from_recommendations(self, client, db):
        self._library(db)
        client.post("/api/recommendations/feedback", json={
            "rawg_id": 500, "name": "Game 500", "genres": ["Action"],
            "platforms": ["PC"], "direction": "less",
        })
        games = self._games_response([(500, ["Action"]), (501, ["Action"])])
        with (
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=self.GENRES)),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=self.PLATFORMS)),
            patch("app.recommendations.RawgClient.list_top_games",
                  new=MagicMock(return_value=games)),
        ):
            r = client.get("/api/recommendations")
        ids = [item["id"] for item in r.json()["results"]]
        assert 500 not in ids
        assert 501 in ids

    def test_more_feedback_boosts_genre_weighting(self, client, db):
        self._library(db)  # library genre: Action (weight ~6.5)
        # Three "more" votes for Indie games → Indie outweighs Action.
        for gid in (901, 902, 903):
            client.post("/api/recommendations/feedback", json={
                "rawg_id": gid, "name": f"Game {gid}", "genres": ["Indie"],
                "platforms": ["PC"], "direction": "more",
            })
        top_games = MagicMock(return_value=self._games_response([(600, ["Indie"])]))
        with (
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=self.GENRES)),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=self.PLATFORMS)),
            patch("app.recommendations.RawgClient.list_top_games", new=top_games),
        ):
            r = client.get("/api/recommendations")
        assert r.status_code == 200
        # The first (highest-priority) RAWG query must now filter by the boosted genre.
        first_call_genres = top_games.call_args_list[0].kwargs.get("genres")
        assert first_call_genres == "indie"

    def test_upvoted_game_marked_in_results(self, client, db):
        self._library(db)
        client.post("/api/recommendations/feedback", json={
            "rawg_id": 501, "name": "Game 501", "genres": ["Action"],
            "platforms": ["PC"], "direction": "more",
        })
        games = self._games_response([(501, ["Action"]), (502, ["Action"])])
        with (
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=self.GENRES)),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=self.PLATFORMS)),
            patch("app.recommendations.RawgClient.list_top_games",
                  new=MagicMock(return_value=games)),
        ):
            r = client.get("/api/recommendations")
        by_id = {item["id"]: item for item in r.json()["results"]}
        assert by_id[501]["feedback"] == "more"
        assert by_id[502]["feedback"] is None


class TestSmarterRecommendations:
    GENRES = [{"id": 4, "name": "Action", "slug": "action"},
              {"id": 51, "name": "Indie", "slug": "indie"}]
    PLATFORMS = [{"id": 1, "name": "PC"}]

    def _entry(self, db, rawg_id, genres, status="COMPLETED", rating=9, favorite=False):
        game = Game(
            rawg_id=rawg_id, slug=f"g-{rawg_id}", name=f"Game {rawg_id}",
            genres_json=json.dumps(genres), platforms_json='["PC"]',
            last_rawg_fetch=utcnow(),
        )
        db.add(game)
        db.flush()
        db.add(Entry(user_id=_uid(db), game_id=game.id, status=status, rating=rating, favorite=favorite))
        db.commit()

    def test_entry_affinity_signs(self):
        from app.recommendations import entry_affinity
        loved = Entry(status="COMPLETED", rating=10, favorite=True)
        dropped = Entry(status="DROPPED", rating=2, favorite=False)
        plain = Entry(status="PLAN", rating=None, favorite=False)
        assert entry_affinity(loved) > 3
        assert entry_affinity(dropped) < 0
        assert 0 < entry_affinity(plain) <= 1

    def test_dropped_genre_suppressed_in_queries(self, client, db):
        # Loved Indie game, dropped + low-rated Action game.
        self._entry(db, 1, ["Indie"], status="COMPLETED", rating=10, favorite=True)
        self._entry(db, 2, ["Action"], status="DROPPED", rating=2)
        top_games = MagicMock(return_value={"results": [], "next": None})
        with (
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=self.GENRES)),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=self.PLATFORMS)),
            patch("app.recommendations.RawgClient.list_top_games", new=top_games),
        ):
            client.get("/api/recommendations")
        queried_genres = {c.kwargs.get("genres") for c in top_games.call_args_list}
        assert "indie" in queried_genres
        assert "action" not in queried_genres  # negative affinity → never queried

    def test_popularity_ordering_included_in_queries(self, client, db):
        self._entry(db, 1, ["Indie"])
        top_games = MagicMock(return_value={"results": [], "next": None})
        with (
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=self.GENRES)),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=self.PLATFORMS)),
            patch("app.recommendations.RawgClient.list_top_games", new=top_games),
        ):
            client.get("/api/recommendations")
        orderings = {c.kwargs.get("ordering") for c in top_games.call_args_list}
        assert "-added" in orderings  # popularity angle, not just metacritic

    def test_dismiss_hides_game_without_shifting_weights(self, client, db):
        self._entry(db, 1, ["Indie"])
        r = client.post("/api/recommendations/feedback", json={
            "rawg_id": 700, "name": "Game 700", "genres": ["Action"],
            "platforms": ["PC"], "direction": "dismiss",
        })
        assert r.json() == {"rawg_id": 700, "direction": "dismiss"}

        games = {"results": [
            {"id": 700, "name": "Game 700", "genres": [{"name": "Action"}],
             "platforms": [{"platform": {"name": "PC"}}], "metacritic": 95,
             "released": "2021-01-01", "background_image": None},
            {"id": 701, "name": "Game 701", "genres": [{"name": "Indie"}],
             "platforms": [{"platform": {"name": "PC"}}], "metacritic": 80,
             "released": "2021-01-01", "background_image": None},
        ], "next": None}
        top_games = MagicMock(return_value=games)
        with (
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=self.GENRES)),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=self.PLATFORMS)),
            patch("app.recommendations.RawgClient.list_top_games", new=top_games),
        ):
            resp = client.get("/api/recommendations")
        ids = [item["id"] for item in resp.json()["results"]]
        assert 700 not in ids  # dismissed → hidden
        assert 701 in ids
        # Unlike "less", dismissing an Action game must not suppress Action
        # from the query set (weights untouched; only Indie is in the library).
        queried_genres = {c.kwargs.get("genres") for c in top_games.call_args_list}
        assert "indie" in queried_genres


class TestPlaytimeOnGamePage:
    def _game(self, db, rawg_id=60, playtime=None):
        game = Game(
            rawg_id=rawg_id, slug="pt-game", name="Playtime Game",
            released="2020-01-01", playtime=playtime, last_rawg_fetch=utcnow(),
            genres_json='["RPG"]', platforms_json='["PC"]', screenshots_json='[]',
        )
        db.add(game)
        db.flush()
        db.add(Entry(user_id=_uid(db), game_id=game.id, status="PLAYING"))
        db.commit()
        return game

    def test_playtime_shown_when_present(self, client, db):
        game = self._game(db, playtime=43)
        r = client.get(f"/game/{game.rawg_id}")
        assert r.status_code == 200
        assert "Time to Beat" in r.text
        assert "43" in r.text
        assert "average time to complete" in r.text

    def test_playtime_absent_shows_not_available(self, client, db):
        game = self._game(db, playtime=None)
        r = client.get(f"/game/{game.rawg_id}")
        assert r.status_code == 200
        assert "Time to Beat" in r.text
        assert "Not available" in r.text

    def test_playtime_flows_from_rawg_payload(self, client, db):
        payload = {
            "id": 4242, "slug": "new", "name": "New Game", "released": "2022-02-02",
            "metacritic": 88, "playtime": 25, "description_raw": "desc",
            "genres": [{"name": "RPG"}], "platforms": [{"platform": {"name": "PC"}}],
        }
        with patch("app.services.RawgClient.get_game", new=MagicMock(return_value=payload)):
            r = client.get("/game/4242")
        assert r.status_code == 200
        assert "25" in r.text
        stored = db.query(Game).filter(Game.rawg_id == 4242).first()
        assert stored.playtime == 25


class TestRecommendationReasonGenreConsistency:
    GENRES = [{"id": 4, "name": "Action", "slug": "action"},
              {"id": 5, "name": "RPG", "slug": "rpg"},
              {"id": 51, "name": "Indie", "slug": "indie"}]
    PLATFORMS = [{"id": 1, "name": "PC"}]

    def test_cited_genres_appear_in_first_three_displayed(self, client, db):
        # Library loves RPG + Action.
        g = Game(rawg_id=1, slug="lib", name="Lib", genres_json='["RPG", "Action"]',
                 platforms_json='["PC"]', last_rawg_fetch=utcnow())
        db.add(g)
        db.flush()
        db.add(Entry(user_id=_uid(db), game_id=g.id, status="COMPLETED", rating=10, favorite=True))
        db.commit()

        # Candidate lists Indie/Adventure FIRST and the matched RPG/Action last —
        # the old code would cite RPG/Action but bury them past the 3-chip cutoff.
        candidate = {
            "id": 900, "name": "Hades-like",
            "genres": [{"name": "Indie"}, {"name": "Adventure"},
                       {"name": "Action"}, {"name": "RPG"}],
            "platforms": [{"platform": {"name": "PC"}}],
            "metacritic": 93, "released": "2020-09-17", "background_image": None,
        }
        games = {"results": [candidate], "next": None}
        with (
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=self.GENRES)),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=self.PLATFORMS)),
            patch("app.recommendations.RawgClient.list_top_games",
                  new=MagicMock(return_value=games)),
        ):
            rec = client.get("/api/recommendations").json()["results"][0]

        import re as _re
        cited = _re.search(r"taste in ([^.]+)\.", rec["reasons"][0]).group(1)
        cited_genres = [c.strip() for c in cited.split(",")]
        displayed = rec["genres"][:3]  # the card shows genres[:3]
        for genre in cited_genres:
            assert genre in displayed, f"cited {genre} not in shown chips {displayed}"
        # Both taste-matched genres are cited and lead the displayed list,
        # ahead of the game's non-matching Indie/Adventure genres.
        assert set(cited_genres) == {"RPG", "Action"}
        assert set(rec["genres"][:2]) == {"RPG", "Action"}


# ---------------------------------------------------------------------------
# Search: popularity ordering + month/year filter
# ---------------------------------------------------------------------------

class TestSearchPopularityAndDates:
    def test_browse_orders_by_added_not_metacritic(self, client):
        top = MagicMock(return_value={"results": [], "next": None})
        with patch("app.routers.api.RawgClient.list_top_games", new=top):
            client.get("/api/search")  # no query = browse
        assert top.call_args.kwargs.get("ordering") == "-added"

    def test_browse_passes_month_year_as_dates(self, client):
        top = MagicMock(return_value={"results": [], "next": None})
        with patch("app.routers.api.RawgClient.list_top_games", new=top):
            client.get("/api/search?year=2023&month=9")
        assert top.call_args.kwargs.get("dates") == "2023-09-01,2023-09-30"

    def test_query_search_passes_year_only_range(self, client):
        sg = MagicMock(return_value={"results": [], "next": None})
        with patch("app.routers.api.RawgClient.search_games", new=sg):
            client.get("/api/search?query=zelda&year=2020")
        assert sg.call_args.kwargs.get("dates") == "2020-01-01,2020-12-31"

    def test_month_without_year_is_ignored(self, client):
        top = MagicMock(return_value={"results": [], "next": None})
        with patch("app.routers.views.RawgClient.list_top_games", new=top), \
             patch("app.routers.views.RawgClient.list_platforms", new=MagicMock(return_value=[])), \
             patch("app.routers.views.RawgClient.list_genres", new=MagicMock(return_value=[])):
            r = client.get("/search?month=9")
        assert r.status_code == 200
        assert top.call_args.kwargs.get("dates") is None


class TestMonthYearToDates:
    def test_month_and_year(self):
        from app.upcoming import month_year_to_dates
        assert month_year_to_dates(2024, 2) == "2024-02-01,2024-02-29"  # leap year

    def test_year_only(self):
        from app.upcoming import month_year_to_dates
        assert month_year_to_dates(2023, None) == "2023-01-01,2023-12-31"

    def test_no_year_returns_none(self):
        from app.upcoming import month_year_to_dates
        assert month_year_to_dates(None, 5) is None


# ---------------------------------------------------------------------------
# Platform-filtered recommendations
# ---------------------------------------------------------------------------

class TestPlatformRecommendations:
    GENRES = [{"id": 4, "name": "Action", "slug": "action"}]
    PLATFORMS = [{"id": 1, "name": "PC"}, {"id": 2, "name": "PlayStation"}, {"id": 3, "name": "Xbox"}]

    def _library(self, db):
        g = Game(rawg_id=1, slug="lib", name="Lib", genres_json='["Action"]',
                 platforms_json='["PC"]', last_rawg_fetch=utcnow())
        db.add(g)
        db.flush()
        db.add(Entry(user_id=_uid(db), game_id=g.id, status="COMPLETED", rating=9))
        db.commit()

    def test_selected_platforms_passed_as_parent_platforms(self, client, db):
        self._library(db)
        top = MagicMock(return_value={"results": [], "next": None})
        with (
            patch("app.recommendations.RawgClient.list_genres", new=MagicMock(return_value=self.GENRES)),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=self.PLATFORMS)),
            patch("app.recommendations.RawgClient.list_top_games", new=top),
        ):
            client.get("/api/recommendations?platforms=2&platforms=3")
        parents = {c.kwargs.get("parent_platforms") for c in top.call_args_list}
        assert parents == {"2,3"}  # every query constrained to PS or Xbox

    def test_candidates_filtered_to_selected_platforms(self, client, db):
        self._library(db)
        games = {"results": [
            {"id": 800, "name": "PC only", "genres": [{"name": "Action"}],
             "platforms": [{"platform": {"name": "PC"}}], "metacritic": 90,
             "released": "2021-01-01", "background_image": None, "added": 100},
            {"id": 801, "name": "On PlayStation", "genres": [{"name": "Action"}],
             "platforms": [{"platform": {"name": "PlayStation 5"}}], "metacritic": 88,
             "released": "2021-01-01", "background_image": None, "added": 100},
        ], "next": None}
        with (
            patch("app.recommendations.RawgClient.list_genres", new=MagicMock(return_value=self.GENRES)),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=self.PLATFORMS)),
            patch("app.recommendations.RawgClient.list_top_games", new=MagicMock(return_value=games)),
        ):
            r = client.get("/api/recommendations?platforms=2")  # PlayStation only
        ids = [x["id"] for x in r.json()["results"]]
        assert 801 in ids and 800 not in ids


# ---------------------------------------------------------------------------
# Refresh / regenerate recommendations
# ---------------------------------------------------------------------------

class TestRecommendationRefresh:
    def test_refresh_forces_cache_bypass(self, client, db):
        g = Game(rawg_id=1, slug="lib", name="Lib", genres_json='["Action"]',
                 platforms_json='["PC"]', last_rawg_fetch=utcnow())
        db.add(g)
        db.flush()
        db.add(Entry(user_id=_uid(db), game_id=g.id, status="COMPLETED", rating=9))
        db.commit()
        top = MagicMock(return_value={"results": [], "next": None})
        with (
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=[{"id": 4, "name": "Action", "slug": "action"}])),
            patch("app.recommendations.RawgClient.list_platforms", new=MagicMock(return_value=[])),
            patch("app.recommendations.RawgClient.list_top_games", new=top),
        ):
            client.get("/api/recommendations?refresh=1")
        assert all(c.kwargs.get("force_refresh") is True for c in top.call_args_list)


# ---------------------------------------------------------------------------
# Debug tools
# ---------------------------------------------------------------------------

class TestDebugTools:
    def test_refresh_clears_cache_and_marks_stale(self, client, db):
        from app.models import APICache
        g = Game(rawg_id=1, slug="g", name="G", last_rawg_fetch=utcnow(),
                 genres_json="[]", platforms_json="[]")
        db.add(g)
        db.add(APICache(cache_key="k", cache_type="list", response_json="{}",
                        expires_at=utcnow()))
        db.commit()
        r = client.post("/api/debug/refresh")
        assert r.status_code == 200
        assert r.json()["cache_cleared"] == 1
        assert r.json()["games_marked_stale"] == 1
        db.expire_all()
        assert db.query(Game).first().last_rawg_fetch is None
        assert db.query(APICache).count() == 0

    def test_reset_wipes_this_users_library(self, client, db):
        g = Game(rawg_id=1, slug="g", name="G", last_rawg_fetch=utcnow(),
                 genres_json="[]", platforms_json="[]")
        db.add(g)
        db.flush()
        db.add(Entry(user_id=_uid(db), game_id=g.id, status="PLAN"))
        db.commit()
        r = client.post("/api/debug/reset")
        assert r.status_code == 200
        assert r.json()["entries_deleted"] == 1
        assert db.query(Entry).count() == 0
        # Shared game catalog is preserved, not wiped.
        assert db.query(Game).count() == 1

    def test_debug_page_renders(self, client):
        r = client.get("/debug")
        assert r.status_code == 200
        assert "Clear cache" in r.text
        assert "Reset" in r.text


# ---------------------------------------------------------------------------
# Upcoming games
# ---------------------------------------------------------------------------

class TestUpcomingClassification:
    def test_full_date_is_month_bucket(self):
        from app.upcoming import classify_release
        assert classify_release("2027-03-15", False) == ("month", 2027, 3)

    def test_jan1_placeholder_is_year_only(self):
        from app.upcoming import classify_release
        assert classify_release("2030-01-01", False) == ("year", 2030, None)

    def test_dec31_placeholder_is_year_only(self):
        from app.upcoming import classify_release
        assert classify_release("2029-12-31", False) == ("year", 2029, None)

    def test_tba_flag_with_year_is_year_only(self):
        from app.upcoming import classify_release
        assert classify_release("2028-06-15", True) == ("year", 2028, None)

    def test_null_release_is_tba(self):
        from app.upcoming import classify_release
        assert classify_release(None, True) == ("tba", None, None)


class TestUpcomingPage:
    def _upcoming_response(self):
        return {"results": [
            {"id": 10, "name": "March Game", "released": "2027-03-15", "tba": False,
             "genres": [], "platforms": [{"platform": {"name": "PC"}}], "metacritic": None,
             "background_image": None, "added": 500},
            {"id": 11, "name": "Year Only Game", "released": "2030-01-01", "tba": False,
             "genres": [], "platforms": [{"platform": {"name": "PC"}}], "metacritic": None,
             "background_image": None, "added": 200},
        ], "next": None}

    def test_page_groups_by_year_and_month(self, client):
        with (
            patch("app.routers.views.RawgClient.list_platforms",
                  new=MagicMock(return_value=[{"id": 1, "name": "PC"}])),
            patch("app.upcoming.RawgClient.list_top_games",
                  new=MagicMock(return_value=self._upcoming_response())),
        ):
            r = client.get("/search?upcoming=1")
        assert r.status_code == 200
        assert "March 2027" in r.text
        assert "March Game" in r.text
        assert "month to be confirmed" in r.text  # year-only bucket
        assert "Year Only Game" in r.text

    def test_local_tba_game_appears_in_tba_section(self, client, db):
        # A locally-known TBA game (like Intergalactic) with no release date.
        db.add(Game(rawg_id=999, slug="intergalactic", name="Intergalactic: The Heretic Prophet",
                    released=None, tba=True, last_rawg_fetch=utcnow(),
                    genres_json='["Action"]', platforms_json='["PC"]'))
        db.commit()
        with (
            patch("app.routers.views.RawgClient.list_platforms",
                  new=MagicMock(return_value=[{"id": 1, "name": "PC"}])),
            patch("app.upcoming.RawgClient.list_top_games",
                  new=MagicMock(return_value={"results": [], "next": None})),
        ):
            r = client.get("/search?upcoming=1")
        assert r.status_code == 200
        assert "TBA" in r.text
        assert "Intergalactic: The Heretic Prophet" in r.text

    def test_old_upcoming_url_redirects_into_search(self, client):
        r = client.get("/upcoming", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "/search?upcoming=1"

    def test_search_page_has_mode_toggle(self, client):
        with (
            patch("app.routers.views.RawgClient.list_platforms", new=MagicMock(return_value=[])),
            patch("app.routers.views.RawgClient.list_genres", new=MagicMock(return_value=[])),
            patch("app.routers.views.RawgClient.list_top_games",
                  new=MagicMock(return_value={"results": [], "next": None})),
        ):
            r = client.get("/search")
        assert "search-mode-toggle" in r.text
        assert "/search?upcoming=1" in r.text  # link to upcoming mode


class TestPlatformDisplayOrder:
    def test_selected_platform_surfaces_first_in_chips(self, client, db):
        g = Game(rawg_id=1, slug="lib", name="Lib", genres_json='["Action"]',
                 platforms_json='["PC"]', last_rawg_fetch=utcnow())
        db.add(g)
        db.flush()
        db.add(Entry(user_id=_uid(db), game_id=g.id, status="COMPLETED", rating=9))
        db.commit()
        # Candidate lists PC/PS/Xbox first and Nintendo Switch last.
        games = {"results": [{
            "id": 850, "name": "Multi", "genres": [{"name": "Action"}],
            "platforms": [{"platform": {"name": "PC"}}, {"platform": {"name": "PlayStation 5"}},
                          {"platform": {"name": "Xbox One"}}, {"platform": {"name": "Nintendo Switch"}}],
            "metacritic": 90, "released": "2021-01-01", "background_image": None, "added": 100,
        }], "next": None}
        platforms = [{"id": 7, "name": "Nintendo"}, {"id": 1, "name": "PC"}]
        with (
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=[{"id": 4, "name": "Action", "slug": "action"}])),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=platforms)),
            patch("app.recommendations.RawgClient.list_top_games",
                  new=MagicMock(return_value=games)),
        ):
            rec = client.get("/api/recommendations?platforms=7").json()["results"][0]
        # Nintendo Switch now leads, so it appears within the first 3 displayed chips.
        assert "Nintendo Switch" in rec["platforms"][:3]


class TestSearchViewYearMonthReachesResults:
    """Guards the bug where the search view dropped year/month before querying."""

    def test_view_browse_applies_year_month_dates(self, client):
        top = MagicMock(return_value={"results": [], "next": None})
        with (
            patch("app.routers.views.RawgClient.list_platforms", new=MagicMock(return_value=[])),
            patch("app.routers.views.RawgClient.list_genres", new=MagicMock(return_value=[])),
            patch("app.routers.views.RawgClient.list_top_games", new=top),
        ):
            client.get("/search?year=2015&month=5")
        assert top.call_args.kwargs.get("dates") == "2015-05-01,2015-05-31"

    def test_view_query_applies_year_dates(self, client):
        sg = MagicMock(return_value={"results": [], "next": None})
        with (
            patch("app.routers.views.RawgClient.list_platforms", new=MagicMock(return_value=[])),
            patch("app.routers.views.RawgClient.list_genres", new=MagicMock(return_value=[])),
            patch("app.routers.views.RawgClient.search_games", new=sg),
        ):
            client.get("/search?q=mario&year=2017")
        assert sg.call_args.kwargs.get("dates") == "2017-01-01,2017-12-31"

    def test_next_page_url_preserves_year_month(self, client):
        data = {"results": [{"id": 1, "name": "G", "released": "2015-05-01",
                             "background_image": None, "metacritic": None,
                             "genres": [], "platforms": []}],
                "next": "http://rawg/next"}
        with (
            patch("app.routers.views.RawgClient.list_platforms", new=MagicMock(return_value=[])),
            patch("app.routers.views.RawgClient.list_genres", new=MagicMock(return_value=[])),
            patch("app.routers.views.RawgClient.list_top_games", new=MagicMock(return_value=data)),
        ):
            r = client.get("/search?year=2015&month=5")
        assert "year=2015" in r.text and "month=5" in r.text


class TestCacheBestEffort:
    """A momentarily locked DB must degrade to 'no caching', never 500."""

    def test_set_cached_response_survives_locked_db(self, db, monkeypatch):
        from sqlalchemy.exc import OperationalError

        from app import cache as cache_mod

        def boom():
            raise OperationalError("INSERT", {}, Exception("database is locked"))

        monkeypatch.setattr(db, "commit", boom)
        # Must not raise — caching is best-effort.
        cache_mod.set_cached_response(db, "list", {"results": [1, 2]}, page=1)

    def test_cleanup_survives_locked_db(self, db, monkeypatch):
        from sqlalchemy.exc import OperationalError

        from app import cache as cache_mod

        def boom():
            raise OperationalError("DELETE", {}, Exception("database is locked"))

        monkeypatch.setattr(db, "commit", boom)
        assert cache_mod.cleanup_expired_cache(db) == 0

    def test_get_cached_response_survives_locked_db(self, db, monkeypatch):
        from sqlalchemy.exc import OperationalError

        from app import cache as cache_mod

        def boom(*args, **kwargs):
            raise OperationalError("SELECT", {}, Exception("database is locked"))

        monkeypatch.setattr(db, "query", boom)
        assert cache_mod.get_cached_response(db, "list", page=1) is None


class TestRecommendationsToolbar:
    def _library(self, db):
        g = Game(rawg_id=1, slug="lib", name="Lib", genres_json='["Action"]',
                 platforms_json='["PC"]', last_rawg_fetch=utcnow())
        db.add(g)
        db.flush()
        db.add(Entry(user_id=_uid(db), game_id=g.id, status="COMPLETED", rating=9))
        db.commit()

    def test_platform_pills_and_icon_refresh_render(self, client, db):
        self._library(db)
        platforms = [{"id": 1, "name": "PC"}, {"id": 7, "name": "Nintendo"}]
        with (
            patch("app.routers.views.RawgClient.list_platforms",
                  new=MagicMock(return_value=platforms)),
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=[{"id": 4, "name": "Action", "slug": "action"}])),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=platforms)),
            patch("app.recommendations.RawgClient.list_top_games",
                  new=MagicMock(return_value={"results": [], "next": None})),
        ):
            r = client.get("/recommendations")
        assert r.status_code == 200
        # Pills, not raw checkboxes-in-a-fieldset.
        assert "pill-toggle" in r.text
        assert "platform-pills" in r.text
        # Icon-only refresh (no verbose label text).
        assert 'class="icon-btn"' in r.text
        assert "Refresh / Regenerate" not in r.text
        assert 'aria-label="Refresh recommendations"' in r.text

    def test_selected_platform_pill_is_checked(self, client, db):
        self._library(db)
        platforms = [{"id": 1, "name": "PC"}, {"id": 7, "name": "Nintendo"}]
        with (
            patch("app.routers.views.RawgClient.list_platforms",
                  new=MagicMock(return_value=platforms)),
            patch("app.recommendations.RawgClient.list_genres",
                  new=MagicMock(return_value=[{"id": 4, "name": "Action", "slug": "action"}])),
            patch("app.recommendations.RawgClient.list_platforms",
                  new=MagicMock(return_value=platforms)),
            patch("app.recommendations.RawgClient.list_top_games",
                  new=MagicMock(return_value={"results": [], "next": None})),
        ):
            r = client.get("/recommendations?platforms=7")
        # The Nintendo pill's checkbox is pre-checked.
        collapsed = " ".join(r.text.split())
        assert 'value="7" checked' in collapsed


class TestOwnedGamesInLists:
    """Games already in the list show 'In your list', never 'Add to My List'."""

    def _own(self, db, rawg_id, name="Owned Game"):
        g = Game(rawg_id=rawg_id, slug=f"g-{rawg_id}", name=name,
                 genres_json="[]", platforms_json="[]", last_rawg_fetch=utcnow())
        db.add(g)
        db.flush()
        db.add(Entry(user_id=_uid(db), game_id=g.id, status="PLAYING"))
        db.commit()

    def test_owned_helper(self, db):
        from app.services import owned_rawg_ids
        self._own(db, 42)
        # A cached game with no entry is NOT owned.
        db.add(Game(rawg_id=43, slug="g43", name="Cached", genres_json="[]",
                    platforms_json="[]", last_rawg_fetch=utcnow()))
        db.commit()
        assert owned_rawg_ids(db, [42, 43, 99], _uid(db)) == {42}

    def test_api_search_marks_owned(self, client, db):
        self._own(db, 500)
        games = {"results": [
            {"id": 500, "name": "Owned", "genres": [], "platforms": [],
             "metacritic": 90, "released": "2020-01-01", "background_image": None},
            {"id": 501, "name": "Not owned", "genres": [], "platforms": [],
             "metacritic": 80, "released": "2020-01-01", "background_image": None},
        ], "next": None}
        with patch("app.routers.api.RawgClient.list_top_games",
                   new=MagicMock(return_value=games)):
            r = client.get("/api/search")  # browse mode
        by_id = {g["id"]: g.get("owned") for g in r.json()["results"]}
        assert by_id[500] is True
        assert by_id[501] is False

    def test_search_page_shows_in_your_list(self, client, db):
        self._own(db, 500, name="Owned Game")
        games = {"results": [
            {"id": 500, "name": "Owned Game", "genres": [], "platforms": [],
             "metacritic": 90, "released": "2020-01-01", "background_image": None},
            {"id": 501, "name": "Fresh Game", "genres": [], "platforms": [],
             "metacritic": 80, "released": "2020-01-01", "background_image": None},
        ], "next": None}
        with (
            patch("app.routers.views.RawgClient.list_platforms", new=MagicMock(return_value=[])),
            patch("app.routers.views.RawgClient.list_genres", new=MagicMock(return_value=[])),
            patch("app.routers.views.RawgClient.list_top_games", new=MagicMock(return_value=games)),
        ):
            r = client.get("/search")
        assert 'href="/game/500">✓ In your list' in r.text  # owned -> link
        # The non-owned game still offers an Add form.
        assert 'value="501"' in r.text and "Add to My List" in r.text

    def test_upcoming_marks_owned(self, client, db):
        self._own(db, 10, name="Owned Upcoming")
        resp = {"results": [
            {"id": 10, "name": "Owned Upcoming", "released": "2027-03-15", "tba": False,
             "genres": [], "platforms": [{"platform": {"name": "PC"}}], "metacritic": None,
             "background_image": None, "added": 100},
        ], "next": None}
        with (
            patch("app.routers.views.RawgClient.list_platforms",
                  new=MagicMock(return_value=[{"id": 1, "name": "PC"}])),
            patch("app.upcoming.RawgClient.list_top_games", new=MagicMock(return_value=resp)),
        ):
            r = client.get("/search?upcoming=1")
        assert 'href="/game/10">✓ In your list' in r.text
