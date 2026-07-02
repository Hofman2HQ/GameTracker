"""Auth flows and per-user data isolation (T1)."""

from unittest.mock import MagicMock, patch

from app.auth import hash_password, verify_password
from app.models import Entry, Game, User
from app.timeutil import utcnow


def _new_user(db, email, slug):
    u = User(email=email, password_hash=hash_password("password123"),
             display_name=email.split("@")[0], profile_slug=slug)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class TestPasswordHashing:
    def test_roundtrip(self):
        h = hash_password("s3cret-password")
        assert h != "s3cret-password"
        assert verify_password("s3cret-password", h)
        assert not verify_password("wrong", h)

    def test_bad_hash_is_false_not_error(self):
        assert verify_password("x", "not-a-bcrypt-hash") is False


class TestAuthGate:
    def test_anon_list_redirects_to_login(self, anon_client):
        r = anon_client.get("/list", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].startswith("/login")

    def test_anon_api_returns_401(self, anon_client):
        r = anon_client.get("/api/entries")
        assert r.status_code == 401

    def test_login_page_is_public(self, anon_client):
        assert anon_client.get("/login").status_code == 200
        assert anon_client.get("/register").status_code == 200


class TestRegisterLogin:
    def test_register_creates_account_and_logs_in(self, anon_client, db):
        r = anon_client.post("/register", data={
            "email": "newbie@example.com", "password": "password123",
            "display_name": "Newbie",
        }, follow_redirects=False)
        assert r.status_code == 303
        assert db.query(User).filter(User.email == "newbie@example.com").first()
        # Session established: a gated page now works.
        assert anon_client.get("/list").status_code == 200

    def test_register_rejects_short_password(self, anon_client):
        r = anon_client.post("/register", data={"email": "x@example.com", "password": "short"})
        assert r.status_code == 400
        assert "at least 8" in r.text

    def test_register_rejects_duplicate_email(self, anon_client, db):
        _new_user(db, "dupe@example.com", "dupe")
        r = anon_client.post("/register", data={"email": "dupe@example.com", "password": "password123"})
        assert r.status_code == 400
        assert "already exists" in r.text

    def test_login_wrong_password_401(self, anon_client, db):
        _new_user(db, "real@example.com", "real")
        r = anon_client.post("/login", data={"email": "real@example.com", "password": "nope"})
        assert r.status_code == 401

    def test_logout_clears_session(self, client):
        assert client.get("/list").status_code == 200
        client.post("/logout", follow_redirects=False)
        r = client.get("/list", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login")


class TestDataIsolation:
    """The core promise: one user never sees or mutates another's data."""

    def _game(self, db, rawg_id):
        g = Game(rawg_id=rawg_id, slug=f"g{rawg_id}", name=f"Game {rawg_id}",
                 genres_json="[]", platforms_json="[]", last_rawg_fetch=utcnow())
        db.add(g)
        db.flush()
        return g

    def test_entries_are_per_user(self, client, db, test_user):
        # Another user with their own entry.
        other = _new_user(db, "other@example.com", "other")
        g1 = self._game(db, 1)
        g2 = self._game(db, 2)
        db.add(Entry(user_id=test_user.id, game_id=g1.id, status="PLAYING"))
        db.add(Entry(user_id=other.id, game_id=g2.id, status="COMPLETED"))
        db.commit()

        # The logged-in test user sees only their own entry.
        body = client.get("/api/entries").json()
        assert len(body) == 1
        assert body[0]["game"]["rawg_id"] == 1

    def test_cannot_edit_another_users_entry(self, client, db, test_user):
        other = _new_user(db, "other@example.com", "other")
        g = self._game(db, 1)
        other_entry = Entry(user_id=other.id, game_id=g.id, status="PLAN")
        db.add(other_entry)
        db.commit()
        db.refresh(other_entry)

        # Test user tries to patch / delete the other user's entry → 404 (not found for them).
        assert client.patch(f"/api/entries/{other_entry.id}", json={"status": "DROPPED"}).status_code == 404
        assert client.delete(f"/api/entries/{other_entry.id}").status_code == 404
        # Untouched.
        db.refresh(other_entry)
        assert other_entry.status == "PLAN"

    def test_same_game_can_be_added_by_two_users(self, client, db, test_user):
        other = _new_user(db, "other@example.com", "other")
        g = self._game(db, 3328)
        db.add(Entry(user_id=other.id, game_id=g.id, status="COMPLETED"))
        db.commit()
        # Test user adds the same game — allowed (per-user uniqueness, not global).
        with patch("app.services.RawgClient.get_game", new=MagicMock(return_value={
            "id": 3328, "slug": "w3", "name": "Witcher 3", "released": "2015-05-19",
            "metacritic": 92, "playtime": 40, "description_raw": "x",
            "genres": [], "platforms": [],
        })):
            r = client.post("/api/entries", json={"rawg_id": 3328, "status": "PLAYING"})
        assert r.status_code == 201
        assert db.query(Entry).filter(Entry.game_id == g.id).count() == 2

    def test_recommendation_feedback_is_per_user(self, client, db, test_user):
        other = _new_user(db, "other@example.com", "other")
        from app.models import RecommendationFeedback
        # Other user dislikes game 500.
        db.add(RecommendationFeedback(user_id=other.id, rawg_id=500, direction=-1))
        db.commit()
        # Test user can still record their own feedback for the same game.
        r = client.post("/api/recommendations/feedback",
                        json={"rawg_id": 500, "direction": "more"})
        assert r.status_code == 200
        assert db.query(RecommendationFeedback).filter(
            RecommendationFeedback.rawg_id == 500).count() == 2


class TestPublicProfile:
    def test_private_profile_404(self, anon_client, db):
        _new_user(db, "priv@example.com", "priv")  # is_public defaults False
        assert anon_client.get("/u/priv").status_code == 404

    def test_public_profile_visible_to_anon(self, anon_client, db):
        u = _new_user(db, "pub@example.com", "pub")
        u.is_public = True
        g = Game(rawg_id=1, slug="g1", name="Public Game", genres_json="[]",
                 platforms_json="[]", last_rawg_fetch=utcnow())
        db.add(g)
        db.flush()
        db.add(Entry(user_id=u.id, game_id=g.id, status="COMPLETED", rating=9))
        db.commit()
        r = anon_client.get("/u/pub")
        assert r.status_code == 200
        assert "Public Game" in r.text

    def test_settings_toggle_publishes(self, client, test_user, db):
        r = client.post("/settings", data={"display_name": "Tester", "is_public": "true"},
                        follow_redirects=False)
        assert r.status_code == 303
        db.refresh(test_user)
        assert test_user.is_public is True
