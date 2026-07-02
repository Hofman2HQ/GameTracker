"""Game persistence helpers shared by the API and view routers."""

from collections.abc import Iterable

from sqlalchemy.orm import Session

from .cache import is_game_data_fresh
from .models import Entry, Game
from .rawg import RawgClient
from .timeutil import utcnow


def owned_rawg_ids(db: Session, rawg_ids: Iterable[int]) -> set[int]:
    """Of the given RAWG ids, return those already in the user's list (have an entry)."""
    ids = [i for i in rawg_ids if i]
    if not ids:
        return set()
    rows = (
        db.query(Game.rawg_id)
        .join(Entry, Entry.game_id == Game.id)
        .filter(Game.rawg_id.in_(ids))
        .all()
    )
    return {row[0] for row in rows}


def annotate_owned(db: Session, results: list[dict]) -> list[dict]:
    """Tag each result dict with ``owned`` = already in the user's list."""
    owned = owned_rawg_ids(db, [r.get('id') for r in results])
    for r in results:
        r['owned'] = r.get('id') in owned
    return results


def _needs_fetch(game: Game | None) -> bool:
    if not game:
        return True
    if (not game.description or not game.genres_json
            or not game.platforms_json or not game.playtime):
        # Key fields missing (playtime included, so games cached before it
        # existed backfill on next view) — refetch at most once a day so a
        # game that legitimately lacks them doesn't trigger a call every view.
        return not is_game_data_fresh(game, max_age_days=1)
    return not is_game_data_fresh(game)


def ensure_game(db: Session, rawg_id: int, client: RawgClient) -> Game:
    """Return the local Game row for a RAWG id, fetching/refreshing as needed.

    Existing values are never overwritten with None, so a partial RAWG payload
    cannot erase data we already have. Flushes but does not commit.
    """
    game = db.query(Game).filter(Game.rawg_id == rawg_id).first()
    if not _needs_fetch(game):
        return game

    data = client.get_game(rawg_id)
    mapped = client.map_game_payload(data)
    if game:
        for key, value in mapped.items():
            if value is not None:
                setattr(game, key, value)
        game.last_rawg_fetch = utcnow()
    else:
        game = Game(**mapped, last_rawg_fetch=utcnow())
        db.add(game)
    db.flush()
    return game
