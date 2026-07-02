import hashlib
import json
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .config import settings
from .models import APICache
from .timeutil import utcnow

logger = logging.getLogger(__name__)

# Cache TTL settings (in seconds), tuned to conserve RAWG API quota —
# override via CACHE_TTL_* / GAME_REFRESH_DAYS env vars.
CACHE_TTL = {
    'search': settings.cache_ttl_search,
    'list': settings.cache_ttl_list,
    'genres': settings.cache_ttl_catalog,
    'platforms': settings.cache_ttl_catalog,
    'game': settings.cache_ttl_game,
}


def _make_cache_key(cache_type: str, **kwargs) -> str:
    """Create a unique cache key from parameters."""
    params = json.dumps(kwargs, sort_keys=True)
    hash_str = hashlib.sha256(f"{cache_type}:{params}".encode()).hexdigest()
    return f"{cache_type}:{hash_str}"


def get_cached_response(db: Session, cache_type: str, **kwargs) -> dict[str, Any] | None:
    """Retrieve cached API response if still valid.

    Caching is best-effort: if the DB is momentarily locked, treat it as a
    cache miss rather than failing the request.
    """
    cache_key = _make_cache_key(cache_type, **kwargs)
    try:
        cached = db.query(APICache).filter(
            APICache.cache_key == cache_key,
            APICache.expires_at > utcnow()
        ).first()
    except OperationalError:
        db.rollback()
        logger.warning("Cache read skipped (database busy) for %s", cache_type)
        return None

    if cached:
        try:
            return json.loads(cached.response_json)
        except json.JSONDecodeError:
            # Invalid cache, delete it (best-effort).
            try:
                db.delete(cached)
                db.commit()
            except OperationalError:
                db.rollback()
    return None


def set_cached_response(db: Session, cache_type: str, response: dict[str, Any], **kwargs) -> None:
    """Store an API response in the cache. Best-effort: a locked DB is logged
    and skipped, never raised, so caching can never break a live request."""
    cache_key = _make_cache_key(cache_type, **kwargs)
    ttl = CACHE_TTL.get(cache_type, 3600)
    expires_at = utcnow() + timedelta(seconds=ttl)

    try:
        cached = db.query(APICache).filter(APICache.cache_key == cache_key).first()
        if cached:
            cached.response_json = json.dumps(response)
            cached.created_at = utcnow()
            cached.expires_at = expires_at
        else:
            db.add(APICache(
                cache_key=cache_key,
                cache_type=cache_type,
                response_json=json.dumps(response),
                expires_at=expires_at,
            ))
        db.commit()
    except OperationalError:
        db.rollback()
        logger.warning("Cache write skipped (database busy) for %s", cache_type)


def cleanup_expired_cache(db: Session) -> int:
    """Remove expired cache entries. Returns number of deleted entries."""
    try:
        result = db.query(APICache).filter(
            APICache.expires_at <= utcnow()
        ).delete()
        db.commit()
        return result
    except OperationalError:
        db.rollback()
        logger.warning("Cache cleanup skipped (database busy)")
        return 0


def is_game_data_fresh(game, max_age_days: int | None = None) -> bool:
    """Check if game data is fresh enough to skip API fetch."""
    if max_age_days is None:
        max_age_days = settings.game_refresh_days
    if not game.last_rawg_fetch:
        return False

    age = utcnow() - game.last_rawg_fetch
    return age.days < max_age_days
