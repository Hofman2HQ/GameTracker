import difflib
import json
import math
import re
from typing import Any, Dict, List, Optional
import httpx
from .config import RAWG_API_KEY, RAWG_BASE_URL


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


def _popularity_score(item: Dict[str, Any]) -> float:
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
    results: list[Dict[str, Any]],
    prefer_popular: bool = False
) -> list[Dict[str, Any]]:
    normalized_query = _normalize(query)
    if not normalized_query:
        return results

    min_score = 0.25 if len(normalized_query) < 4 else 0.35
    scored_all: list[tuple[float, float, float, Dict[str, Any]]] = []
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
    def __init__(self, api_key: str = RAWG_API_KEY, base_url: str = RAWG_BASE_URL, db = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.db = db

    async def list_games(
        self,
        page_size: int = 10,
        query: Optional[str] = None,
        ordering: Optional[str] = None,
        platforms: Optional[int] = None,
        parent_platforms: Optional[int] = None,
        genres: Optional[str] = None,
        search_precise: bool = True,
        page: Optional[int] = None
    ) -> Dict[str, Any]:
        # Try cache if db session available
        if self.db:
            from .cache import get_cached_response, set_cached_response
            cache_type = 'search' if query else 'list'
            cached = get_cached_response(
                self.db,
                cache_type,
                page_size=page_size,
                query=query,
                ordering=ordering,
                platforms=platforms,
                parent_platforms=parent_platforms,
                genres=genres,
                search_precise=search_precise,
                page=page
            )
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
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{self.base_url}/games", params=params)
            r.raise_for_status()
            result = r.json()

        # Cache the result if db session available
        if self.db:
            from .cache import set_cached_response
            cache_type = 'search' if query else 'list'
            set_cached_response(
                self.db,
                cache_type,
                result,
                page_size=page_size,
                query=query,
                ordering=ordering,
                platforms=platforms,
                parent_platforms=parent_platforms,
                genres=genres,
                search_precise=search_precise,
                page=page
            )

        return result

    async def search_games(
        self,
        query: str,
        page_size: int = 10,
        platforms: Optional[int] = None,
        parent_platforms: Optional[int] = None,
        genres: Optional[str] = None,
        ordering: Optional[str] = None,
        page: Optional[int] = None
    ) -> Dict[str, Any]:
        return await self.list_games(
            page_size=page_size,
            query=query,
            ordering=ordering,
            platforms=platforms,
            parent_platforms=parent_platforms,
            genres=genres,
            search_precise=True,
            page=page
        )

    async def list_top_games(
        self,
        page_size: int = 10,
        platforms: Optional[int] = None,
        parent_platforms: Optional[int] = None,
        genres: Optional[str] = None,
        page: Optional[int] = None
    ) -> Dict[str, Any]:
        return await self.list_games(
            page_size=page_size,
            ordering='-metacritic',
            platforms=platforms,
            parent_platforms=parent_platforms,
            genres=genres,
            page=page
        )

    async def list_genres(self) -> list[dict[str, Any]]:
        # Try cache if db session available
        if self.db:
            from .cache import get_cached_response, set_cached_response
            cached = get_cached_response(self.db, 'genres')
            if cached:
                return cached.get('results', [])

        params = {'key': self.api_key, 'page_size': 50}
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{self.base_url}/genres", params=params)
            r.raise_for_status()
            data = r.json()
        results = [
            {'id': g.get('id'), 'name': g.get('name'), 'slug': g.get('slug')}
            for g in data.get('results', [])
            if g.get('id') and g.get('name') and g.get('slug')
        ]

        # Cache the result if db session available
        if self.db:
            from .cache import set_cached_response
            set_cached_response(self.db, 'genres', {'results': results})

        return results

    async def list_platforms(self) -> list[dict[str, Any]]:
        # Try cache if db session available
        if self.db:
            from .cache import get_cached_response, set_cached_response
            cached = get_cached_response(self.db, 'platforms')
            if cached:
                return cached.get('results', [])

        params = {'key': self.api_key, 'page_size': 50}
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{self.base_url}/platforms/lists/parents", params=params)
            r.raise_for_status()
            data = r.json()
        results = [
            {'id': p.get('id'), 'name': p.get('name')}
            for p in data.get('results', [])
            if p.get('id') and p.get('name')
        ]

        # Cache the result if db session available
        if self.db:
            from .cache import set_cached_response
            set_cached_response(self.db, 'platforms', {'results': results})

        return results

    async def get_game(self, rawg_id: int) -> Dict[str, Any]:
        params = { 'key': self.api_key }
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{self.base_url}/games/{rawg_id}", params=params)
            r.raise_for_status()
            return r.json()

    @staticmethod
    def map_game_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
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
            'genres_json': json.dumps(genres) if genres else None,
            'platforms_json': json.dumps(platforms) if platforms else None,
        }
