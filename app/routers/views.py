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
    page: int = 1,
    db: Session = Depends(get_db)
):
    client = RawgClient(db=db)
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
    from datetime import datetime
    from ..cache import is_game_data_fresh
    client = RawgClient(db=db)
    # Ensure game exists
    game = db.query(Game).filter(Game.rawg_id == rawg_id).first()
    if not game or not is_game_data_fresh(game):
        data = await client.get_game(rawg_id)
        mapped = client.map_game_payload(data)
        if game:
            # Update existing game
            for key, value in mapped.items():
                setattr(game, key, value)
            game.last_rawg_fetch = datetime.utcnow()
        else:
            # Create new game
            game = Game(**mapped, last_rawg_fetch=datetime.utcnow())
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
    from datetime import datetime
    from ..cache import is_game_data_fresh
    # Fetch game from DB or RAWG
    game = db.query(Game).filter(Game.rawg_id == rawg_id).first()
    needs_fetch = False

    if not game:
        needs_fetch = True
    elif not game.description or not game.genres_json or not game.platforms_json:
        # Missing data, but check if we recently tried to fetch
        if not is_game_data_fresh(game, max_age_days=1):
            needs_fetch = True
    elif not is_game_data_fresh(game):
        # Data exists but is old (7+ days)
        needs_fetch = True

    if needs_fetch:
        client = RawgClient(db=db)
        data = await client.get_game(rawg_id)
        mapped = client.map_game_payload(data)
        if game:
            # Update existing game
            for key, value in mapped.items():
                if value is not None:  # Only update if new value exists
                    setattr(game, key, value)
            game.last_rawg_fetch = datetime.utcnow()
        else:
            # Create new game
            game = Game(**mapped, last_rawg_fetch=datetime.utcnow())
            db.add(game)
        db.commit()
        db.refresh(game)

    # Entry (may be None if not added)
    entry = db.query(Entry).filter(Entry.game_id == game.id).first()
    is_unreleased = False
    if game.released:
        try:
            rel_date = datetime.strptime(game.released, '%Y-%m-%d').date()
            if rel_date > datetime.utcnow().date():
                is_unreleased = True
        except ValueError:
            pass

    return templates.TemplateResponse('game.html', {
        'request': request,
        'game': game,
        'entry': entry,
        'statuses': STATUSES,
        'genres': game.genres,
        'platforms': game.platforms,
        'synopsis': game.description,
        'is_unreleased': is_unreleased
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
        
    import datetime
    if status != 'PLAN' and entry.game.released:
        try:
            rel_date = datetime.datetime.strptime(entry.game.released, '%Y-%m-%d').date()
            if rel_date > datetime.date.today():
                status = 'PLAN'
        except ValueError:
            pass

    entry.status = status
    if status == 'PLAN':
        entry.rating = None
        entry.comment = comment
        entry.hours_played = None
        entry.favorite = False
        entry.start_date = None
        entry.end_date = None
    else:
        entry.rating = int(rating) if rating not in (None, '') else None
        entry.comment = comment
        entry.hours_played = max(0.0, float(hours_played)) if hours_played not in (None, '') else None
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
    import json
    totals = {s: 0 for s in STATUSES}
    ratings_dist = {str(i): 0 for i in range(1, 11)}
    ratings = []
    hours = 0.0
    total = 0
    genres_count = {}
    platforms_count = {}
    longest_games = []

    for e in db.query(Entry).all():
        totals[e.status] = totals.get(e.status, 0) + 1
        if e.rating is not None:
            ratings.append(e.rating)
            ratings_dist[str(e.rating)] += 1
        if e.hours_played:
            hours += e.hours_played
            longest_games.append({
                'name': e.game.name,
                'hours': round(e.hours_played, 1),
                'id': e.game.rawg_id
            })
        total += 1
        
        if e.game.genres_json:
            try:
                g_list = json.loads(e.game.genres_json)
                for g in g_list:
                    genres_count[g] = genres_count.get(g, 0) + 1
            except Exception:
                pass
        if e.game.platforms_json:
            try:
                p_list = json.loads(e.game.platforms_json)
                for p in p_list:
                    platforms_count[p] = platforms_count.get(p, 0) + 1
            except Exception:
                pass

    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
    completion_rate = round((totals.get('COMPLETED', 0) / total) * 100) if total else 0
    longest_games = sorted(longest_games, key=lambda x: x['hours'], reverse=True)[:5]
    sorted_genres = dict(sorted(genres_count.items(), key=lambda item: item[1], reverse=True)[:5])
    sorted_platforms = dict(sorted(platforms_count.items(), key=lambda item: item[1], reverse=True)[:5])

    return templates.TemplateResponse('stats.html', {
        'request': request,
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
