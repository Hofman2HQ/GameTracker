"""Upcoming-games grouping and the shared month/year → RAWG dates helper.

RAWG represents release dates three ways, which map to the three tiers the
Upcoming page shows:
  * a real ``YYYY-MM-DD``            → grouped under that year and month
  * a ``YYYY-01-01`` / ``YYYY-12-31`` placeholder, or ``tba=True`` with a year
                                      → grouped under the year only (no month)
  * ``released is null`` (``tba``)   → the "TBA" section

Note: RAWG's list endpoints never return null-date games (there is no date to
match and they are absent from popularity feeds), so the TBA section is drawn
from games already in the local library/cache that are flagged ``tba``.
"""

import calendar
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from .models import Game
from .rawg import RawgClient
from .services import owned_rawg_ids

UPCOMING_START_BUFFER_DAYS = 0
UPCOMING_END = '2035-12-31'
YEAR_PLACEHOLDER_MMDD = {('01', '01'), ('12', '31')}

MONTH_NAMES = [
    '', 'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
]


def month_year_to_dates(year: int | None, month: int | None) -> str | None:
    """Build a RAWG ``dates`` range from an optional year and month.

    year+month → that whole month; year only → that whole year; anything
    without a year → None (a month alone can't form a range).
    """
    if not year:
        return None
    if month and 1 <= month <= 12:
        last_day = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-01,{year:04d}-{month:02d}-{last_day:02d}"
    return f"{year:04d}-01-01,{year:04d}-12-31"


def classify_release(released: str | None, tba: bool) -> tuple[str, int | None, int | None]:
    """Return ``(bucket, year, month)`` where bucket is 'month', 'year' or 'tba'."""
    if not released:
        return ('tba', None, None)
    parts = released.split('-')
    if len(parts) != 3:
        return ('tba', None, None)
    year_str, month_str, day_str = parts
    try:
        year = int(year_str)
        month = int(month_str)
    except ValueError:
        return ('tba', None, None)
    if tba or (month_str, day_str) in YEAR_PLACEHOLDER_MMDD:
        return ('year', year, None)
    return ('month', year, month)


def _summarize(g: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': g.get('id'),
        'name': g.get('name'),
        'background_image': g.get('background_image'),
        'released': g.get('released'),
        'metacritic': g.get('metacritic'),
        'added': g.get('added') or 0,
        'genres': [genre.get('name') for genre in g.get('genres') or [] if genre.get('name')],
        'platforms': [
            p.get('platform', {}).get('name')
            for p in g.get('platforms') or []
            if p.get('platform', {}).get('name')
        ],
    }


def build_upcoming(
    db: Session,
    platform_ids: list[int] | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Fetch and group upcoming games into years → months, plus year-only and TBA."""
    client = RawgClient(db=db)
    start = (date.today() + timedelta(days=UPCOMING_START_BUFFER_DAYS)).isoformat()
    dates = f"{start},{UPCOMING_END}"
    parent = ','.join(str(p) for p in platform_ids) if platform_ids else None

    candidates: dict[int, dict[str, Any]] = {}
    # Soonest-first for near-term coverage, then most-anticipated for the hype.
    for ordering in ('released', '-added'):
        data = client.list_top_games(
            page_size=40,
            ordering=ordering,
            parent_platforms=parent,
            dates=dates,
            force_refresh=force_refresh,
        )
        for g in data.get('results', []):
            gid = g.get('id')
            if gid and gid not in candidates:
                candidates[gid] = _summarize(g)
            # Preserve RAWG's tba flag for classification.
            if gid in candidates:
                candidates[gid]['tba'] = bool(g.get('tba'))

    # Merge locally-known TBA games (null-date), which RAWG list feeds omit.
    local_platform_names = None
    if platform_ids:
        catalog = client.list_platforms()
        local_platform_names = {p['name'] for p in catalog if p['id'] in platform_ids}
    for game in db.query(Game).filter(Game.tba.is_(True)).all():
        if game.rawg_id in candidates:
            continue
        if local_platform_names is not None and not (set(game.platforms) & local_platform_names):
            continue
        candidates[game.rawg_id] = {
            'id': game.rawg_id,
            'name': game.name,
            'background_image': game.background_image,
            'released': game.released,
            'metacritic': game.metacritic,
            'added': 0,
            'genres': game.genres,
            'platforms': game.platforms,
            'tba': True,
        }

    # Flag games already in the user's list so the card shows "In your list".
    owned = owned_rawg_ids(db, list(candidates.keys()))

    years: dict[int, dict[str, Any]] = {}
    tba: list[dict[str, Any]] = []
    for game in candidates.values():
        game['owned'] = game['id'] in owned
        bucket, year, month = classify_release(game.get('released'), game.get('tba', False))
        if bucket == 'tba':
            tba.append(game)
            continue
        year_entry = years.setdefault(year, {'year': year, 'months': {}, 'undated': []})
        if bucket == 'month':
            year_entry['months'].setdefault(month, []).append(game)
        else:
            year_entry['undated'].append(game)

    def sort_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(games, key=lambda g: g['added'], reverse=True)

    grouped_years = []
    for year in sorted(years):
        entry = years[year]
        months = [
            {'month': m, 'name': MONTH_NAMES[m], 'games': sort_games(entry['months'][m])}
            for m in sorted(entry['months'])
        ]
        grouped_years.append({
            'year': year,
            'months': months,
            'undated': sort_games(entry['undated']),
        })

    return {'years': grouped_years, 'tba': sort_games(tba)}
