"""
Tests for the pure helper functions and static methods in app/rawg.py.
No database or HTTP connections are required.
"""

import pytest
from app.rawg import (
    _normalize,
    _token_overlap,
    _important_tokens,
    _token_match_ratio,
    _popularity_score,
    rank_results,
    RawgClient,
)


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_lowercases(self):
        assert _normalize("Hello World") == "hello world"

    def test_strips_punctuation(self):
        assert _normalize("God of War!") == "god of war"

    def test_collapses_multiple_spaces(self):
        assert _normalize("a  b   c") == "a b c"

    def test_empty_string(self):
        assert _normalize("") == ""

    def test_none_input(self):
        # The function uses `(text or '').lower()`, so None is treated as "".
        assert _normalize(None) == ""

    def test_special_characters(self):
        assert _normalize("Pokémon: Sword & Shield") == "pok mon sword shield"

    def test_numbers_preserved(self):
        assert _normalize("FIFA 23") == "fifa 23"


# ---------------------------------------------------------------------------
# _token_overlap
# ---------------------------------------------------------------------------

class TestTokenOverlap:
    def test_full_overlap(self):
        assert _token_overlap("hello world", "hello world") == 1.0

    def test_no_overlap(self):
        assert _token_overlap("foo bar", "baz qux") == 0.0

    def test_partial_overlap(self):
        score = _token_overlap("the witcher 3", "witcher wild hunt")
        assert 0.0 < score < 1.0

    def test_empty_query(self):
        assert _token_overlap("", "hello") == 0.0

    def test_empty_name(self):
        assert _token_overlap("hello", "") == 0.0

    def test_subset(self):
        # "dark souls" vs "dark souls remastered" – 2 of 2 query tokens match.
        score = _token_overlap("dark souls", "dark souls remastered")
        assert score == 1.0


# ---------------------------------------------------------------------------
# _important_tokens
# ---------------------------------------------------------------------------

class TestImportantTokens:
    def test_filters_short_tokens(self):
        # Tokens with length <= 2 are excluded.
        assert _important_tokens("a bb ccc dddd") == ["ccc", "dddd"]

    def test_all_short(self):
        assert _important_tokens("a bb") == []

    def test_all_long(self):
        tokens = _important_tokens("dark souls elden ring")
        assert tokens == ["dark", "souls", "elden", "ring"]

    def test_empty_string(self):
        assert _important_tokens("") == []


# ---------------------------------------------------------------------------
# _token_match_ratio
# ---------------------------------------------------------------------------

class TestTokenMatchRatio:
    def test_perfect_match(self):
        assert _token_match_ratio(["dark", "souls"], ["dark", "souls", "remastered"]) == 1.0

    def test_no_match(self):
        assert _token_match_ratio(["foo", "bar"], ["baz", "qux"]) == 0.0

    def test_partial_match(self):
        ratio = _token_match_ratio(["dark", "souls", "three"], ["dark", "qux", "baz"])
        assert ratio == pytest.approx(1 / 3)

    def test_empty_query_tokens(self):
        assert _token_match_ratio([], ["dark", "souls"]) == 0.0

    def test_empty_name_tokens(self):
        assert _token_match_ratio(["dark"], []) == 0.0

    def test_prefix_match(self):
        # "soul" starts-with check: "souls".startswith("soul") == True
        assert _token_match_ratio(["soul"], ["souls"]) == 1.0


# ---------------------------------------------------------------------------
# _popularity_score
# ---------------------------------------------------------------------------

class TestPopularityScore:
    def test_zero_for_empty(self):
        assert _popularity_score({}) == 0.0

    def test_metacritic_only(self):
        score = _popularity_score({"metacritic": 80})
        assert score == pytest.approx(0.8)

    def test_ratings_count_contributes(self):
        score = _popularity_score({"ratings_count": 1000})
        assert score > 0.0

    def test_added_contributes(self):
        score = _popularity_score({"added": 50000})
        assert score > 0.0

    def test_all_fields(self):
        full = _popularity_score({"metacritic": 90, "ratings_count": 5000, "added": 100000})
        partial = _popularity_score({"metacritic": 90})
        assert full > partial

    def test_non_int_metacritic_ignored(self):
        # metacritic might be None or a string in edge cases
        assert _popularity_score({"metacritic": None}) == 0.0

    def test_score_capped(self):
        # ratings_count and added contributions are capped at 1.0 each.
        score = _popularity_score({"ratings_count": 10**10, "added": 10**10})
        assert score <= 2.0


# ---------------------------------------------------------------------------
# rank_results
# ---------------------------------------------------------------------------

class TestRankResults:
    def _make_game(self, name, metacritic=None, ratings_count=0, added=0):
        return {
            "name": name,
            "metacritic": metacritic,
            "ratings_count": ratings_count,
            "added": added,
        }

    def test_empty_results(self):
        assert rank_results("witcher", []) == []

    def test_exact_match_beats_irrelevant(self):
        games = [
            self._make_game("Some Completely Unrelated Title"),
            self._make_game("Witcher"),
        ]
        ranked = rank_results("witcher", games)
        names = [g["name"] for g in ranked]
        assert names[0] == "Witcher"

    def test_popular_game_beats_low_popularity_exact_match(self):
        # A highly-rated popular game should outrank an exact-name match with
        # no popularity signals, which is the intended behaviour of the scorer.
        games = [
            self._make_game("Witcher"),  # exact match, zero popularity
            self._make_game("The Witcher 3: Wild Hunt", metacritic=92,
                            ratings_count=50000, added=200000),
        ]
        ranked = rank_results("witcher", games)
        # Both should appear; the highly popular one is expected to rank first.
        assert ranked[0]["name"] == "The Witcher 3: Wild Hunt"

    def test_irrelevant_results_deprioritised(self):
        games = [
            self._make_game("The Witcher 3", metacritic=92, ratings_count=10000),
            self._make_game("XYZ AAABBBCCC"),
        ]
        ranked = rank_results("witcher 3", games)
        names = [g["name"] for g in ranked]
        assert names[0] == "The Witcher 3"

    def test_prefer_popular_boosts_popular_games(self):
        games = [
            self._make_game("Witcher Indie", metacritic=55, ratings_count=10),
            self._make_game("The Witcher 3", metacritic=92, ratings_count=50000),
        ]
        normal = rank_results("witcher", games, prefer_popular=False)
        popular = rank_results("witcher", games, prefer_popular=True)
        assert popular[0]["name"] == "The Witcher 3"

    def test_empty_query_returns_results_unchanged(self):
        games = [self._make_game("Game A"), self._make_game("Game B")]
        # An empty query normalises to "" so results are returned as-is.
        result = rank_results("", games)
        assert result == games

    def test_game_with_no_name_skipped(self):
        games = [
            {"name": "", "metacritic": 90},
            {"name": "Dark Souls", "metacritic": 89},
        ]
        ranked = rank_results("dark souls", games)
        assert all(g["name"] for g in ranked)


# ---------------------------------------------------------------------------
# RawgClient.map_game_payload
# ---------------------------------------------------------------------------

class TestMapGamePayload:
    def _payload(self, **overrides):
        base = {
            "id": 1,
            "slug": "the-witcher-3",
            "name": "The Witcher 3: Wild Hunt",
            "background_image": "https://example.com/img.jpg",
            "released": "2015-05-19",
            "metacritic": 92,
            "description_raw": "An open world RPG.",
            "genres": [{"name": "RPG"}, {"name": "Action"}],
            "platforms": [
                {"platform": {"name": "PC"}},
                {"platform": {"name": "PlayStation 4"}},
            ],
        }
        base.update(overrides)
        return base

    def test_basic_mapping(self):
        result = RawgClient.map_game_payload(self._payload())
        assert result["rawg_id"] == 1
        assert result["slug"] == "the-witcher-3"
        assert result["name"] == "The Witcher 3: Wild Hunt"
        assert result["metacritic"] == 92
        assert result["released"] == "2015-05-19"

    def test_genres_serialised(self):
        import json
        result = RawgClient.map_game_payload(self._payload())
        assert json.loads(result["genres_json"]) == ["RPG", "Action"]

    def test_platforms_serialised(self):
        import json
        result = RawgClient.map_game_payload(self._payload())
        platforms = json.loads(result["platforms_json"])
        assert "PC" in platforms
        assert "PlayStation 4" in platforms

    def test_description_raw_preferred(self):
        result = RawgClient.map_game_payload(self._payload(
            description_raw="Raw description",
            description="<p>HTML description</p>",
        ))
        assert result["description"] == "Raw description"

    def test_html_description_stripped_when_no_raw(self):
        result = RawgClient.map_game_payload(self._payload(
            description_raw=None,
            description="<p>Hello <b>world</b></p>",
        ))
        assert result["description"] == "Hello world"

    def test_no_description(self):
        result = RawgClient.map_game_payload(self._payload(
            description_raw=None,
            description=None,
        ))
        assert result["description"] is None

    def test_missing_name_defaults_to_unknown(self):
        result = RawgClient.map_game_payload(self._payload(name=None))
        assert result["name"] == "Unknown"

    def test_missing_slug_defaults_to_empty(self):
        result = RawgClient.map_game_payload(self._payload(slug=None))
        assert result["slug"] == ""

    def test_empty_genres(self):
        result = RawgClient.map_game_payload(self._payload(genres=[]))
        assert result["genres_json"] is None

    def test_empty_platforms(self):
        result = RawgClient.map_game_payload(self._payload(platforms=[]))
        assert result["platforms_json"] is None
