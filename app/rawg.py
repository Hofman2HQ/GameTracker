import json
from typing import Any, Dict, List, Optional
import httpx
from .config import RAWG_API_KEY, RAWG_BASE_URL

class RawgClient:
    def __init__(self, api_key: str = RAWG_API_KEY, base_url: str = RAWG_BASE_URL):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')

    async def search_games(self, query: str, page_size: int = 10) -> Dict[str, Any]:
        params = {
            'key': self.api_key,
            'search': query,
            'page_size': page_size,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{self.base_url}/games", params=params)
            r.raise_for_status()
            return r.json()

    async def get_game(self, rawg_id: int) -> Dict[str, Any]:
        params = { 'key': self.api_key }
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{self.base_url}/games/{rawg_id}", params=params)
            r.raise_for_status()
            return r.json()

    @staticmethod
    def map_game_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        genres = [g.get('name') for g in payload.get('genres') or []]
        platforms = [p.get('platform', {}).get('name') for p in payload.get('platforms') or []]
        return {
            'rawg_id': payload.get('id'),
            'slug': payload.get('slug') or '',
            'name': payload.get('name') or 'Unknown',
            'background_image': payload.get('background_image'),
            'released': payload.get('released'),
            'metacritic': payload.get('metacritic'),
            'genres_json': json.dumps(genres) if genres else None,
            'platforms_json': json.dumps(platforms) if platforms else None,
        }
