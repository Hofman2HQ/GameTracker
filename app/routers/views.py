from typing import Optional
from urllib.parse import urlencode
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import case
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Game, Entry
from ..rawg import RawgClient, rank_results
from ..recommendations import build_recommendations
from ..config import STATUSES

router = APIRouter()

templates = Jinja2Templates(directory='app/templates')

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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get('/')
def home(_: Request):
    return RedirectResponse(url='/list', status_code=302)


@router.get('/list')
def view_list(
    request: Request,
    status: Optional[str] = None,
    sort: Optional[str] = None,
    hours: Optional[str] = None,
    db: Session = Depends(get_db)
):
    q = db.query(Entry).join(Game)
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
    return templates.TemplateResponse('list.html', {
        'request': request,
        'entries': entries,
        'statuses': STATUSES,
        'current_status': status or '',
        'current_sort': sort or '',
        'current_hours': hours or ''
    })


@router.get('/search')
async def search_page(
    request: Request,
    q: Optional[str] = None,
    platform: Optional[str] = None,
    genre: Optional[str] = None,
    page: int = 1
):
    client = RawgClient()
    platform_id = int(platform) if platform and platform.isdigit() else None
    genre_slug = genre or None
    page = clamp_page(page)
    page_size = SEARCH_PAGE_SIZE
    platforms = sorted(await client.list_platforms(), key=lambda item: item['name'])
    genres = sorted(await client.list_genres(), key=lambda item: item['name'])

    query = (q or '').strip()
    if query:
        data = await client.search_games(
            query,
            page_size=page_size,
            parent_platforms=platform_id,
            genres=genre_slug,
            page=page
        )
        raw_results = rank_results(query, data.get('results', []))
    else:
        data = await client.list_top_games(
            page_size=page_size,
            parent_platforms=platform_id,
            genres=genre_slug,
            page=page
        )
        raw_results = data.get('results', [])

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
    has_more = bool(data.get('next'))
    params = {}
    if query:
        params['q'] = query
    if platform_id:
        params['platform'] = platform_id
    if genre_slug:
        params['genre'] = genre_slug
    query_string = urlencode(params)
    next_page_url = None
    if has_more:
        if query_string:
            next_page_url = f"/search?{query_string}&page={page + 1}"
        else:
            next_page_url = f"/search?page={page + 1}"
    return templates.TemplateResponse('search.html', {
        'request': request,
        'results': results,
        'q': query,
        'platform': platform_id or '',
        'genre': genre_slug or '',
        'platforms': platforms,
        'genres': genres,
        'page': page,
        'page_size': page_size,
        'next_page_url': next_page_url
    })


@router.post('/add')
async def add_from_search(rawg_id: int = Form(...), db: Session = Depends(get_db)):
    client = RawgClient()
    # Ensure game exists
    game = db.query(Game).filter(Game.rawg_id == rawg_id).first()
    if not game:
        data = await client.get_game(rawg_id)
        mapped = client.map_game_payload(data)
        game = Game(**mapped)
        db.add(game)
        db.flush()
    # Create entry if not exists
    entry = db.query(Entry).filter(Entry.game_id == game.id).first()
    if not entry:
        entry = Entry(game_id=game.id, status='PLAN')
        db.add(entry)
        db.commit()
    return RedirectResponse(url=f'/game/{rawg_id}', status_code=303)


@router.get('/game/{rawg_id}')
async def game_detail(request: Request, rawg_id: int, db: Session = Depends(get_db)):
    # Fetch game from DB or RAWG
    game = db.query(Game).filter(Game.rawg_id == rawg_id).first()
    if not game:
        client = RawgClient()
        data = await client.get_game(rawg_id)
        mapped = client.map_game_payload(data)
        game = Game(**mapped)
        db.add(game)
        db.commit()
        db.refresh(game)
    elif not game.description or not game.genres_json or not game.platforms_json:
        client = RawgClient()
        data = await client.get_game(rawg_id)
        mapped = client.map_game_payload(data)
        if mapped.get('description') and not game.description:
            game.description = mapped['description']
        if mapped.get('genres_json') and not game.genres_json:
            game.genres_json = mapped['genres_json']
        if mapped.get('platforms_json') and not game.platforms_json:
            game.platforms_json = mapped['platforms_json']
        db.add(game)
        db.commit()
        db.refresh(game)
    # Entry (may be None if not added)
    entry = db.query(Entry).filter(Entry.game_id == game.id).first()
    return templates.TemplateResponse('game.html', {
        'request': request,
        'game': game,
        'entry': entry,
        'statuses': STATUSES,
        'genres': game.genres,
        'platforms': game.platforms,
        'synopsis': game.description
    })


@router.post('/entries/{entry_id}/update')
def update_entry_view(
    entry_id: int,
    status: str = Form(...),
    rating: Optional[str] = Form(None),
    comment: Optional[str] = Form(None),
    hours_played: Optional[str] = Form(None),
    favorite: Optional[bool] = Form(False),
    start_date: Optional[str] = Form(None),
    end_date: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    entry = db.query(Entry).filter(Entry.id == entry_id).first()
    if not entry:
        return RedirectResponse(url='/list', status_code=303)
    entry.status = status
    entry.rating = int(rating) if rating not in (None, '') else None
    entry.comment = comment
    entry.hours_played = float(hours_played) if hours_played not in (None, '') else None
    if isinstance(favorite, str):
        entry.favorite = favorite.lower() in ('1', 'true', 'on', 'yes')
    else:
        entry.favorite = bool(favorite)
    entry.start_date = start_date or None
    entry.end_date = end_date or None
    db.add(entry)
    db.commit()
    return RedirectResponse(url=f'/game/{entry.game.rawg_id}', status_code=303)


@router.post('/entries/{entry_id}/delete')
def delete_entry_view(entry_id: int, db: Session = Depends(get_db)):
    entry = db.query(Entry).filter(Entry.id == entry_id).first()
    if entry:
        rawg_id = entry.game.rawg_id
        db.delete(entry)
        db.commit()
        return RedirectResponse(url=f'/game/{rawg_id}', status_code=303)
    return RedirectResponse(url='/list', status_code=303)


@router.get('/stats')
def stats_page(request: Request, db: Session = Depends(get_db)):
    totals = {s: 0 for s in STATUSES}
    ratings: list[int] = []
    hours = 0.0
    total = 0
    for e in db.query(Entry).all():
        totals[e.status] = totals.get(e.status, 0) + 1
        if e.rating is not None:
            ratings.append(e.rating)
        if e.hours_played:
            hours += e.hours_played
        total += 1
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
    status_colors = {
        'PLAN': 'var(--status-plan)',
        'PLAYING': 'var(--status-playing)',
        'COMPLETED': 'var(--status-completed)',
        'DROPPED': 'var(--status-dropped)',
    }
    chart_items = []
    chart_segments = []
    offset = 0.0
    if total:
        for status in STATUSES:
            count = totals.get(status, 0)
            if not count:
                continue
            percent = round(count / total * 100, 1)
            color = status_colors.get(status, 'var(--border)')
            chart_items.append({
                'label': status,
                'value': count,
                'percent': percent,
                'color': color,
            })
            end = offset + percent
            chart_segments.append(f"{color} {offset:.2f}% {end:.2f}%")
            offset = end
    chart_css = f"conic-gradient({', '.join(chart_segments)})" if chart_segments else "conic-gradient(var(--border) 0 100%)"
    return templates.TemplateResponse('stats.html', {
        'request': request,
        'totals': totals,
        'total': total,
        'avg_rating': avg_rating,
        'hours': round(hours, 1),
        'chart_items': chart_items,
        'chart_css': chart_css
    })


@router.get('/recommendations')
async def recommendations_page(
    request: Request,
    page: int = 1,
    db: Session = Depends(get_db)
):
    page = clamp_page(page)
    recommendations, has_more = await build_recommendations(
        db,
        page=page,
        page_size=RECOMMENDATIONS_PAGE_SIZE
    )
    next_page_url = f"/recommendations?page={page + 1}" if has_more else None
    return templates.TemplateResponse('recommendations.html', {
        'request': request,
        'recommendations': recommendations,
        'page': page,
        'page_size': RECOMMENDATIONS_PAGE_SIZE,
        'next_page_url': next_page_url
    })
