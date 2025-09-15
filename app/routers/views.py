from typing import Optional
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Game, Entry
from ..rawg import RawgClient
from ..config import STATUSES

router = APIRouter()

templates = Jinja2Templates(directory='app/templates')


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
def view_list(request: Request, status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Entry).join(Game).order_by(Entry.updated_at.desc())
    if status:
        q = q.filter(Entry.status == status)
    entries = q.all()
    return templates.TemplateResponse('list.html', {
        'request': request,
        'entries': entries,
        'statuses': STATUSES,
        'current_status': status or ''
    })


@router.get('/search')
async def search_page(request: Request, q: Optional[str] = None):
    results = []
    if q:
        client = RawgClient()
        data = await client.search_games(q, page_size=24)
        results = data.get('results', [])
    return templates.TemplateResponse('search.html', {
        'request': request,
        'results': results,
        'q': q or ''
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
    # Entry (may be None if not added)
    entry = db.query(Entry).filter(Entry.game_id == game.id).first()
    return templates.TemplateResponse('game.html', {
        'request': request,
        'game': game,
        'entry': entry,
        'statuses': STATUSES
    })


@router.post('/entries/{entry_id}/update')
def update_entry_view(
    entry_id: int,
    status: str = Form(...),
    rating: Optional[int] = Form(None),
    comment: Optional[str] = Form(None),
    hours_played: Optional[float] = Form(None),
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
    return templates.TemplateResponse('stats.html', {
        'request': request,
        'totals': totals,
        'total': total,
        'avg_rating': avg_rating,
        'hours': round(hours, 1)
    })
