import difflib
import json
import logging
import math
import re
import time
from typing import Any

import httpx

from .config import RAWG_API_KEY, RAWG_BASE_URL, settings

logger = logging.getLogger(__name__)


class RawgError(Exception):
    """Base error for RAWG API failures."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class RawgAuthError(RawgError):
    """RAWG rejected the API key (missing, empty, or invalid)."""


class RawgNotFoundError(RawgError):
    """The requested resource does not exist on RAWG."""


class RawgUnavailableError(RawgError):
    """RAWG is unreachable or persistently failing (network, timeout, 5xx)."""


# Shared HTTP client with connection pooling, created by the app lifespan.
# httpx.Client is thread-safe, so it is shared across FastAPI's worker threads.
# When absent (tests, scripts), each request falls back to a one-shot client.
_shared_client: httpx.Client | None = None


def configure_shared_client() -> None:
    global _shared_client
    _shared_client = httpx.Client(
        timeout=settings.http_timeout_seconds,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


def close_shared_client() -> None:
    global _shared_client
    if _shared_client is not None:
        _shared_client.close()
        _shared_client = None


def _normalize(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', (text or '').lower()).strip()


def _token_overlap(query: str, name: str) -> float:
    q_tokens = set(query.split())
    n_tokens = set(name.split())
    if not q_tokens or not n_tokens:
        return 0.0
    return len(q_tokens & n_tokens) / max(len(q_tokens), 1)


def _important_tokens(text: str) -> list[str]:
    return [token for token in text.split() if len(token) > 2]


def _token_match_ratio(query_tokens: list[str], name_tokens: list[str]) -> float:
    if not query_tokens or not name_tokens:
        return 0.0
    matches = 0
    for token in query_tokens:
        if any(name.startswith(token) for name in name_tokens):
            matches += 1
    return matches / len(query_tokens)


def _popularity_score(item: dict[str, Any]) -> float:
    score = 0.0
    metacritic = item.get('metacritic')
    if isinstance(metacritic, int):
        score += metacritic / 100.0
    ratings_count = item.get('ratings_count') or 0
    if ratings_count:
        score += min(math.log10(ratings_count + 1) / 3.0, 1.0)
    added = item.get('added') or 0
    if added:
        score += min(math.log10(added + 1) / 4.0, 1.0)
    return score


def rank_results(
    query: str,
    results: list[dict[str, Any]],
    prefer_popular: bool = False
) -> list[dict[str, Any]]:
    normalized_query = _normalize(query)
    if not normalized_query:
        return results

    min_score = 0.25 if len(normalized_query) < 4 else 0.35
    scored_all: list[tuple[float, float, float, dict[str, Any]]] = []
    for item in results:
        name = item.get('name') or ''
        normalized_name = _normalize(name)
        if not normalized_name:
            continue
        similarity = difflib.SequenceMatcher(None, normalized_query, normalized_name).ratio()
        overlap = _token_overlap(normalized_query, normalized_name)
        relevance = max(similarity, overlap)
        important_tokens = _important_tokens(normalized_query)
        if important_tokens:
            match_ratio = _token_match_ratio(important_tokens, normalized_name.split())
            if len(important_tokens) >= 2 and match_ratio < 0.8:
                relevance *= 0.6
        elif len(normalized_query.split()) >= 2 and overlap < 0.5:
            relevance *= 0.75
        popularity = _popularity_score(item)
        if prefer_popular:
            score = relevance * 1.1 + popularity * 0.8
        else:
            score = relevance * 1.5 + popularity * 0.4
        scored_all.append((score, relevance, popularity, item))

    scored = [item for item in scored_all if item[1] >= min_score]
    if len(scored) < 5:
        scored = scored_all

    scored.sort(key=lambda item: (item[0], item[2], item[1]), reverse=True)
    return [item[3] for item in scored]


class RawgClient:
    def __init__(self, api_key: str = RAWG_API_KEY, base_url: str = RAWG_BASE_URL, db=None):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.db = db

    def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET with retries; maps transport/HTTP failures to typed RawgErrors."""
        url = f"{self.base_url}{path}"
        attempts = max(1, settings.http_retries + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            if attempt:
                time.sleep(0.5 * (2 ** (attempt - 1)))
            try:
                if _shared_client is not None:
                    r = _shared_client.get(url, params=params)
                else:
                    with httpx.Client(timeout=settings.http_timeout_seconds) as client:
                        r = client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("RAWG request failed (%s), attempt %d/%d: %s",
                               path, attempt + 1, attempts, exc)
                continue
            if r.status_code in (401, 403):
                raise RawgAuthError('RAWG API key is missing or invalid', r.status_code)
            if r.status_code == 404:
                raise RawgNotFoundError('Game not found on RAWG', 404)
            if r.status_code == 429 or r.status_code >= 500:
                last_error = httpx.HTTPStatusError(
                    f"RAWG returned {r.status_code}", request=r.request, response=r)
                logger.warning("RAWG returned %d (%s), attempt %d/%d",
                               r.status_code, path, attempt + 1, attempts)
                continue
            r.raise_for_status()
            return r.json()
        raise RawgUnavailableError(f"RAWG API unavailable: {last_error}") from last_error

    def list_games(
        self,
        page_size: int = 10,
        query: str | None = None,
        ordering: str | None = None,
        platforms: int | None = None,
        parent_platforms: int | str | None = None,
        genres: str | None = None,
        search_precise: bool = True,
        page: int | None = None,
        dates: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        cache_params = dict(
            page_size=page_size,
            query=query,
            ordering=ordering,
            platforms=platforms,
            parent_platforms=parent_platforms,
            genres=genres,
            search_precise=search_precise,
            page=page,
            dates=dates,
        )
        cache_type = 'search' if query else 'list'
        if self.db and not force_refresh:
            from .cache import get_cached_response
            cached = get_cached_response(self.db, cache_type, **cache_params)
            if cached:
                return cached

        params = {
            'key': self.api_key,
            'page_size': page_size,
        }
        if page:
            params['page'] = page
        if ordering:
            params['ordering'] = ordering
        if query:
            params['search'] = query
            params['search_precise'] = str(search_precise).lower()
        if parent_platforms:
            params['parent_platforms'] = parent_platforms
        elif platforms:
            params['platforms'] = platforms
        if genres:
            params['genres'] = genres
        if dates:
            params['dates'] = dates

        result = self._get_json('/games', params)

        if self.db:
            from .cache import set_cached_response
            set_cached_response(self.db, cache_type, result, **cache_params)

        return result

    def search_games(
        self,
        query: str,
        page_size: int = 10,
        platforms: int | None = None,
        parent_platforms: int | str | None = None,
        genres: str | None = None,
        ordering: str | None = None,
        page: int | None = None,
        dates: str | None = None,
    ) -> dict[str, Any]:
        return self.list_games(
            page_size=page_size,
            query=query,
            ordering=ordering,
            platforms=platforms,
            parent_platforms=parent_platforms,
            genres=genres,
            search_precise=True,
            page=page,
            dates=dates,
        )

    def list_top_games(
        self,
        page_size: int = 10,
        platforms: int | None = None,
        parent_platforms: int | str | None = None,
        genres: str | None = None,
        page: int | None = None,
        ordering: str = '-metacritic',
        dates: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        return self.list_games(
            page_size=page_size,
            ordering=ordering,
            platforms=platforms,
            parent_platforms=parent_platforms,
            genres=genres,
            page=page,
            dates=dates,
            force_refresh=force_refresh,
        )

    def list_genres(self) -> list[dict[str, Any]]:
        if self.db:
            from .cache import get_cached_response
            cached = get_cached_response(self.db, 'genres')
            if cached:
                return cached.get('results', [])

        data = self._get_json('/genres', {'key': self.api_key, 'page_size': 50})
        results = [
            {'id': g.get('id'), 'name': g.get('name'), 'slug': g.get('slug')}
            for g in data.get('results', [])
            if g.get('id') and g.get('name') and g.get('slug')
        ]

        if self.db:
            from .cache import set_cached_response
            set_cached_response(self.db, 'genres', {'results': results})

        return results

    def list_platforms(self) -> list[dict[str, Any]]:
        if self.db:
            from .cache import get_cached_response
            cached = get_cached_response(self.db, 'platforms')
            if cached:
                return cached.get('results', [])

        data = self._get_json('/platforms/lists/parents', {'key': self.api_key, 'page_size': 50})
        results = [
            {'id': p.get('id'), 'name': p.get('name')}
            for p in data.get('results', [])
            if p.get('id') and p.get('name')
        ]

        if self.db:
            from .cache import set_cached_response
            set_cached_response(self.db, 'platforms', {'results': results})

        return results

    def get_game(self, rawg_id: int) -> dict[str, Any]:
        return self._get_json(f"/games/{rawg_id}", {'key': self.api_key})

    def list_screenshots(self, rawg_id: int, limit: int = 10) -> list[str]:
        """Screenshot image URLs for a game (best-effort extra media)."""
        data = self._get_json(
            f"/games/{rawg_id}/screenshots",
            {'key': self.api_key, 'page_size': limit},
        )
        return [
            s['image'] for s in data.get('results', [])
            if s.get('image') and not s.get('is_deleted')
        ][:limit]

    @staticmethod
    def map_game_payload(payload: dict[str, Any]) -> dict[str, Any]:
        description = payload.get('description_raw')
        if not description:
            raw_html = payload.get('description') or ''
            description = re.sub(r'<[^>]+>', '', raw_html).strip() or None
        genres = [g.get('name') for g in payload.get('genres') or []]
        platforms = [p.get('platform', {}).get('name') for p in payload.get('platforms') or []]
        return {
            'rawg_id': payload.get('id'),
            'slug': payload.get('slug') or '',
            'name': payload.get('name') or 'Unknown',
            'background_image': payload.get('background_image'),
            'released': payload.get('released'),
            'metacritic': payload.get('metacritic'),
            'description': description,
            'playtime': payload.get('playtime') or None,
            'tba': bool(payload.get('tba')),
            'genres_json': json.dumps(genres) if genres else None,
            'platforms_json': json.dumps(platforms) if platforms else None,
        }
