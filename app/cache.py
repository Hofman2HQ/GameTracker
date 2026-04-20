import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from .models import APICache

# Cache TTL settings (in seconds)
CACHE_TTL = {
    'search': 3600,  # 1 hour
    'list': 3600,    # 1 hour
    'genres': 86400,  # 24 hours
    'platforms': 86400,  # 24 hours
    'game': 604800,  # 7 days
}


def _make_cache_key(cache_type: str, **kwargs) -> str:
    """Create a unique cache key from parameters."""
    params = json.dumps(kwargs, sort_keys=True)
    hash_str = hashlib.md5(f"{cache_type}:{params}".encode()).hexdigest()
    return f"{cache_type}:{hash_str}"


def get_cached_response(db: Session, cache_type: str, **kwargs) -> Optional[Dict[str, Any]]:
    """Retrieve cached API response if still valid."""
    cache_key = _make_cache_key(cache_type, **kwargs)
    cached = db.query(APICache).filter(
        APICache.cache_key == cache_key,
        APICache.expires_at > datetime.utcnow()
    ).first()

    if cached:
        try:
            return json.loads(cached.response_json)
        except json.JSONDecodeError:
            # Invalid cache, delete it
            db.delete(cached)
            db.commit()
    return None


def set_cached_response(db: Session, cache_type: str, response: Dict[str, Any], **kwargs) -> None:
    """Store API response in cache."""
    cache_key = _make_cache_key(cache_type, **kwargs)
    ttl = CACHE_TTL.get(cache_type, 3600)
    expires_at = datetime.utcnow() + timedelta(seconds=ttl)

    # Check if cache entry already exists
    cached = db.query(APICache).filter(APICache.cache_key == cache_key).first()

    if cached:
        # Update existing cache
        cached.response_json = json.dumps(response)
        cached.created_at = datetime.utcnow()
        cached.expires_at = expires_at
    else:
        # Create new cache entry
        cached = APICache(
            cache_key=cache_key,
            cache_type=cache_type,
            response_json=json.dumps(response),
            expires_at=expires_at
        )
        db.add(cached)

    db.commit()


def cleanup_expired_cache(db: Session) -> int:
    """Remove expired cache entries. Returns number of deleted entries."""
    result = db.query(APICache).filter(
        APICache.expires_at <= datetime.utcnow()
    ).delete()
    db.commit()
    return result


def is_game_data_fresh(game, max_age_days: int = 7) -> bool:
    """Check if game data is fresh enough to skip API fetch."""
    if not game.last_rawg_fetch:
        return False

    age = datetime.utcnow() - game.last_rawg_fetch
    return age.days < max_age_days
