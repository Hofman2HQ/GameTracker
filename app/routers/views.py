import json
import logging
from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import case
from sqlalchemy.orm import Session, joinedload

from ..auth import require_user_view
from ..config import STATUSES
from ..deps import get_db  # noqa: F401  (re-exported for tests/overrides)
from ..models import Entry, Game, User
from ..rawg import RawgClient, RawgError, rank_results
from ..recommendations import build_recommendations
from ..services import annotate_owned, ensure_game
from ..templating import templates
from ..timeutil import utcnow
from ..upcoming import MONTH_NAMES, build_upcoming, month_year_to_dates

logger = logging.getLogger(__name__)

router = APIRouter()

SEARCH_PAGE_SIZE = 12
RECOMMENDATIONS_PAGE_SIZE = 8
MAX_BROWSE_PAGE = 50


def clamp_page(page: int, max_page: int = MAX_BROWSE_PAGE) -> int:
    return max(1, min(page, max_page))


def nulls_last(column, descending: bool = False):
    null_order = case((column.is_(None), 1), else_=0)
    if descending:
        return [null_order, column.desc()]
    return [null_order, column.asc()]


def parse_release_date(released: str | None):
    if not released:
        return None
    try:
        return datetime.strptime(released, '%Y-%m-%d').date()
    except ValueError:
        return None


@router.get('/')
def home(_: Request):
    return RedirectResponse(url='/list', status_code=302)


@router.get('/list')
def view_list(
    request: Request,
    status: str | None = None,
    sort: str | None = None,
    hours: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_view),
):
    q = db.query(Entry).join(Game).options(joinedload(Entry.game)).filter(Entry.user_id == user.id)
    if status:
        q = q.filter(Entry.status == status)
    if hours == '1-6':
        q = q.filter(Entry.hours_played >= 1, Entry.hours_played <= 6)
    elif hours == '7-15':
        q = q.filter(Entry.hours_played >= 7, Entry.hours_played <= 15)
    elif hours == '15+':
        q = q.filter(Entry.hours_played >= 15)

    order_by = [Entry.updated_at.desc()]
    if sort == 'alpha':
        order_by = [Game.name.asc()]
    elif sort == 'mc':
        order_by = nulls_last(Game.metacritic, descending=True)
    elif sort == 'release_asc':
        order_by = nulls_last(Game.released, descending=False)
    elif sort == 'release_desc':
        order_by = nulls_last(Game.released, descending=True)

    entries = q.order_by(*order_by).all()
    return templates.TemplateResponse(request, 'list.html', {
        'entries': entries,
        'statuses': STATUSES,
        'current_status': status or '',
        'current_sort': sort or '',
        'current_hours': hours or ''
    })


@router.get('/search')
def search_page(
    request: Request,
    q: str | None = None,
    platform: str | None = None,
    genre: str | None = None,
    year: int | None = None,
    month: int | None = None,
    upcoming: bool = False,
    page: int = 1,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_view),
):
    client = RawgClient(db=db)
    platform_id = int(platform) if platform and platform.isdigit() else None
    genre_slug = genre or None
    page = clamp_page(page)
    page_size = SEARCH_PAGE_SIZE
    query = (q or '').strip()
    if month and not year:
        month = None  # a month without a year can't form a date range
    dates = month_year_to_dates(year, month)

    error = None
    platforms: list = []
    genres: list = []
    raw_results: list = []
    data: dict = {}
    upcoming_groups = {'years': [], 'tba': []}

    if upcoming:
        # Upcoming mode: grouped year → month → TBA view, filtered by platform.
        try:
            platforms = sorted(client.list_platforms(), key=lambda item: item['name'])
            upcoming_groups = build_upcoming(
                db,
                user.id,
                platform_ids=[platform_id] if platform_id else None,
            )
        except RawgError as exc:
            logger.warning('Upcoming degraded, RAWG unavailable: %s', exc)
            error = 'The game database is unreachable right now — upcoming games are temporarily unavailable.'
        current_year = utcnow().year
        return templates.TemplateResponse(request, 'search.html', {
            'upcoming_mode': True,
            'years': upcoming_groups['years'],
            'tba': upcoming_groups['tba'],
            'results': [],
            'q': '',
            'platform': platform_id or '',
            'genre': '',
            'year': '',
            'month': '',
            'year_choices': list(range(current_year + 2, 1979, -1)),
            'month_choices': list(enumerate(MONTH_NAMES))[1:],
            'platforms': platforms,
            'genres': [],
            'page': 1,
            'page_size': page_size,
            'next_page_url': None,
            'error': error,
        })

    try:
        platforms = sorted(client.list_platforms(), key=lambda item: item['name'])
        genres = sorted(client.list_genres(), key=lambda item: item['name'])
        if query:
            data = client.search_games(
                query,
                page_size=page_size,
                parent_platforms=platform_id,
                genres=genre_slug,
                page=page,
                dates=dates,
            )
            raw_results = rank_results(query, data.get('results', []))
        else:
            # Browse view: most-added (popular) first, not Metacritic.
            data = client.list_top_games(
                page_size=page_size,
                parent_platforms=platform_id,
                genres=genre_slug,
                page=page,
                ordering='-added',
                dates=dates,
            )
            raw_results = data.get('results', [])
    except RawgError as exc:
        logger.warning('Search degraded, RAWG unavailable: %s', exc)
        error = 'The game database is unreachable right now — search is temporarily unavailable.'

    results = []
    for g in raw_results:
        results.append({
            'id': g.get('id'),
            'name': g.get('name'),
            'released': g.get('released'),
            'background_image': g.get('background_image'),
            'metacritic': g.get('metacritic'),
            'genres': [genre.get('name') for genre in g.get('genres') or [] if genre.get('name')],
            'platforms': [
                p.get('platform', {}).get('name')
                for p in g.get('platforms') or []
                if p.get('platform', {}).get('name')
            ],
        })
    annotate_owned(db, results, user.id)
    has_more = bool(data.get('next'))
    params = {}
    if query:
        params['q'] = query
    if platform_id:
        params['platform'] = platform_id
    if genre_slug:
        params['genre'] = genre_slug
    if year:
        params['year'] = year
    if month:
        params['month'] = month
    query_string = urlencode(params)
    next_page_url = None
    if has_more:
        if query_string:
            next_page_url = f"/search?{query_string}&page={page + 1}"
        else:
            next_page_url = f"/search?page={page + 1}"
    current_year = utcnow().year
    return templates.TemplateResponse(request, 'search.html', {
        'upcoming_mode': False,
        'results': results,
        'q': query,
        'platform': platform_id or '',
        'genre': genre_slug or '',
        'year': year or '',
        'month': month or '',
        'year_choices': list(range(current_year + 2, 1979, -1)),
        'month_choices': list(enumerate(MONTH_NAMES))[1:],
        'platforms': platforms,
        'genres': genres,
        'page': page,
        'page_size': page_size,
        'next_page_url': next_page_url,
        'error': error
    })


@router.post('/add')
def add_from_search(rawg_id: int = Form(...), db: Session = Depends(get_db),
                    user: User = Depends(require_user_view)):
    game = ensure_game(db, rawg_id, RawgClient(db=db))
    entry = db.query(Entry).filter(
        Entry.game_id == game.id, Entry.user_id == user.id
    ).first()
    if not entry:
        entry = Entry(user_id=user.id, game_id=game.id, status='PLAN')
        db.add(entry)
    db.commit()
    return RedirectResponse(url=f'/game/{rawg_id}', status_code=303)


@router.get('/game/{rawg_id}')
def game_detail(
    request: Request,
    rawg_id: int,
    saved: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_view),
):
    client = RawgClient(db=db)
    game = ensure_game(db, rawg_id, client)

    # Best-effort screenshot gallery: fetched once per game, then stored.
    # An empty list is stored as '[]' so games without screenshots don't refetch.
    if game.screenshots_json is None:
        try:
            game.screenshots_json = json.dumps(client.list_screenshots(rawg_id))
        except RawgError as exc:
            logger.warning('Could not fetch screenshots for %s: %s', rawg_id, exc)

    db.commit()
    db.refresh(game)

    # This user's entry for the game (may be None if not added)
    entry = db.query(Entry).filter(
        Entry.game_id == game.id, Entry.user_id == user.id
    ).first()
    rel_date = parse_release_date(game.released)
    is_unreleased = bool(rel_date and rel_date > utcnow().date())

    return templates.TemplateResponse(request, 'game.html', {
        'game': game,
        'entry': entry,
        'statuses': STATUSES,
        'genres': game.genres,
        'platforms': game.platforms,
        'screenshots': game.screenshots,
        'synopsis': game.description,
        'is_unreleased': is_unreleased,
        'saved': saved
    })


def _parse_int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, '') else None
    except ValueError:
        return None


def _parse_hours(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value not in (None, '') else None
    except ValueError:
        return None


def clamp_entry_dates(
    start_date: str | None,
    end_date: str | None,
    released: str | None,
) -> tuple[str | None, str | None]:
    """Keep entry dates sane: never before the game's release, end never before start."""
    start = parse_release_date(start_date)
    end = parse_release_date(end_date)
    release = parse_release_date(released)
    if release:
        if start and start < release:
            start = release
        if end and end < release:
            end = release
    if start and end and end < start:
        end = start
    return (
        start.isoformat() if start else None,
        end.isoformat() if end else None,
    )


@router.post('/entries/{entry_id}/update')
def update_entry_view(
    entry_id: int,
    status: str = Form(...),
    rating: str | None = Form(None),
    comment: str | None = Form(None),
    hours_played: str | None = Form(None),
    favorite: bool | None = Form(False),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user_view),
):
    entry = db.query(Entry).filter(
        Entry.id == entry_id, Entry.user_id == user.id
    ).first()
    if not entry:
        return RedirectResponse(url='/list', status_code=303)

    if status not in STATUSES:
        status = entry.status
    rel_date = parse_release_date(entry.game.released)
    if status != 'PLAN' and rel_date and rel_date > utcnow().date():
        status = 'PLAN'

    entry.status = status
    if status == 'PLAN':
        entry.rating = None
        entry.comment = comment
        entry.hours_played = None
        entry.favorite = False
        entry.start_date = None
        entry.end_date = None
    else:
        entry.rating = _parse_int(rating)
        entry.comment = comment
        entry.hours_played = _parse_hours(hours_played)
        if isinstance(favorite, str):
            entry.favorite = favorite.lower() in ('1', 'true', 'on', 'yes')
        else:
            entry.favorite = bool(favorite)
        entry.start_date, entry.end_date = clamp_entry_dates(
            start_date, end_date, entry.game.released
        )

    db.add(entry)
    db.commit()
    return RedirectResponse(url=f'/game/{entry.game.rawg_id}?saved=1', status_code=303)


@router.post('/entries/{entry_id}/delete')
def delete_entry_view(entry_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_user_view)):
    entry = db.query(Entry).filter(
        Entry.id == entry_id, Entry.user_id == user.id
    ).first()
    if entry:
        rawg_id = entry.game.rawg_id
        db.delete(entry)
        db.commit()
        return RedirectResponse(url=f'/game/{rawg_id}', status_code=303)
    return RedirectResponse(url='/list', status_code=303)


@router.get('/stats')
def stats_page(request: Request, db: Session = Depends(get_db),
               user: User = Depends(require_user_view)):
    totals = {s: 0 for s in STATUSES}
    ratings_dist = {str(i): 0 for i in range(1, 11)}
    ratings = []
    hours = 0.0
    total = 0
    genres_count = {}
    platforms_count = {}
    longest_games = []

    for e in db.query(Entry).options(joinedload(Entry.game)).filter(Entry.user_id == user.id).all():
        totals[e.status] = totals.get(e.status, 0) + 1
        if e.rating is not None:
            ratings.append(e.rating)
            key = str(e.rating)
            ratings_dist[key] = ratings_dist.get(key, 0) + 1
        if e.hours_played:
            hours += e.hours_played
            longest_games.append({
                'name': e.game.name,
                'hours': round(e.hours_played, 1),
                'id': e.game.rawg_id
            })
        total += 1

        for g in e.game.genres:
            genres_count[g] = genres_count.get(g, 0) + 1
        for p in e.game.platforms:
            platforms_count[p] = platforms_count.get(p, 0) + 1

    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
    completion_rate = round((totals.get('COMPLETED', 0) / total) * 100) if total else 0
    longest_games = sorted(longest_games, key=lambda x: x['hours'], reverse=True)[:5]
    sorted_genres = dict(sorted(genres_count.items(), key=lambda item: item[1], reverse=True)[:5])
    sorted_platforms = dict(sorted(platforms_count.items(), key=lambda item: item[1], reverse=True)[:5])

    return templates.TemplateResponse(request, 'stats.html', {
        'totals': totals,
        'total': total,
        'avg_rating': avg_rating,
        'hours': round(hours, 1),
        'completion_rate': completion_rate,
        'ratings_dist_json': json.dumps(ratings_dist),
        'genres_json': json.dumps(sorted_genres),
        'platforms_json': json.dumps(sorted_platforms),
        'status_json': json.dumps(totals),
        'longest_games': longest_games
    })


def _parse_platform_ids(platforms: list[str] | None) -> list[int]:
    """Accept repeated ?platforms=4&platforms=1 and comma form ?platforms=4,1."""
    ids: list[int] = []
    for chunk in platforms or []:
        for part in str(chunk).split(','):
            part = part.strip()
            if part.isdigit() and int(part) not in ids:
                ids.append(int(part))
    return ids


@router.get('/recommendations')
def recommendations_page(
    request: Request,
    page: int = 1,
    platforms: list[str] | None = Query(default=None),
    refresh: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_view),
):
    page = clamp_page(page)
    client = RawgClient(db=db)
    platform_ids = _parse_platform_ids(platforms)
    platforms_param = ','.join(str(p) for p in platform_ids)
    platform_selected = set(platform_ids)
    platform_choices: list = []
    try:
        platform_choices = sorted(client.list_platforms(), key=lambda item: item['name'])
        recommendations, has_more = build_recommendations(
            db,
            user.id,
            page=page,
            page_size=RECOMMENDATIONS_PAGE_SIZE,
            platform_ids=platform_ids,
            force_refresh=refresh,
        )
        error = None
    except RawgError as exc:
        logger.warning('Recommendations degraded, RAWG unavailable: %s', exc)
        recommendations, has_more = [], False
        error = 'The game database is unreachable right now — recommendations are temporarily unavailable.'
    # Preserve the platform filter across pagination / load-more.
    platform_qs = f"&platforms={platforms_param}" if platforms_param else ''
    next_page_url = f"/recommendations?page={page + 1}{platform_qs}" if has_more else None
    return templates.TemplateResponse(request, 'recommendations.html', {
        'recommendations': recommendations,
        'page': page,
        'page_size': RECOMMENDATIONS_PAGE_SIZE,
        'next_page_url': next_page_url,
        'error': error,
        'platform_choices': platform_choices,
        'platform_selected': platform_selected,
        'platforms_param': platforms_param,
    })


@router.get('/upcoming')
def upcoming_redirect(platform: str | None = None):
    # Upcoming is now a mode of Search; keep the old URL working.
    target = '/search?upcoming=1'
    if platform and platform.isdigit():
        target += f'&platform={platform}'
    return RedirectResponse(url=target, status_code=307)


@router.get('/settings')
def settings_page(request: Request, saved: bool = False,
                  user: User = Depends(require_user_view)):
    return templates.TemplateResponse(request, 'settings.html', {
        'account': user, 'saved': saved,
    })


@router.post('/settings')
def settings_save(
    request: Request,
    display_name: str = Form(''),
    is_public: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_user_view),
):
    user.display_name = display_name.strip() or user.display_name
    user.is_public = bool(is_public)
    db.add(user)
    db.commit()
    return RedirectResponse(url='/settings?saved=1', status_code=303)


@router.get('/debug')
def debug_page(request: Request, user: User = Depends(require_user_view)):
    return templates.TemplateResponse(request, 'debug.html', {})


@router.get('/u/{slug}')
def public_profile(request: Request, slug: str, db: Session = Depends(get_db)):
    """Public read-only profile — visible only if the owner enabled sharing."""
    profile = db.query(User).filter(User.profile_slug == slug, User.is_public.is_(True)).first()
    if not profile:
        return templates.TemplateResponse(
            request, 'error.html',
            {'status_code': 404, 'message': 'This profile does not exist or is private.'},
            status_code=404,
        )
    entries = (
        db.query(Entry).join(Game).options(joinedload(Entry.game))
        .filter(Entry.user_id == profile.id)
        .order_by(Entry.updated_at.desc())
        .all()
    )
    totals = {s: 0 for s in STATUSES}
    for e in entries:
        totals[e.status] = totals.get(e.status, 0) + 1
    return templates.TemplateResponse(request, 'profile.html', {
        'profile': profile,
        'entries': entries,
        'totals': totals,
        'total': len(entries),
    })
