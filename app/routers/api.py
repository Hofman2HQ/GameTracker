import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Game, Entry
from ..schemas import EntryCreate, EntryUpdate, EntryOut, GameOut
from ..rawg import RawgClient, rank_results
from ..recommendations import build_recommendations
from ..config import STATUSES

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get('/statuses')
def list_statuses():
    return STATUSES


@router.get('/entries', response_model=list[EntryOut])
def list_entries(status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Entry).join(Game).order_by(Entry.updated_at.desc())
    if status:
        q = q.filter(Entry.status == status)
    entries = q.all()
    return entries


@router.post('/entries', response_model=EntryOut)
async def add_entry(payload: EntryCreate, db: Session = Depends(get_db)):
    from datetime import datetime
    from ..cache import is_game_data_fresh
    # Ensure game exists in DB
    game = db.query(Game).filter(Game.rawg_id == payload.rawg_id).first()
    if not game or not is_game_data_fresh(game):
        client = RawgClient(db=db)
        data = await client.get_game(payload.rawg_id)
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
    # Check existing entry for this game
    existing = db.query(Entry).filter(Entry.game_id == game.id).first()
    if existing:
        raise HTTPException(status_code=409, detail='Game already in your list')
    entry = Entry(
        game_id=game.id,
        status=payload.status,
        rating=payload.rating,
        comment=payload.comment,
        hours_played=payload.hours_played,
        favorite=payload.favorite,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.patch('/entries/{entry_id}', response_model=EntryOut)
def update_entry(entry_id: int, payload: EntryUpdate, db: Session = Depends(get_db)):
    entry = db.query(Entry).filter(Entry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail='Entry not found')
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete('/entries/{entry_id}')
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    entry = db.query(Entry).filter(Entry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail='Entry not found')
    db.delete(entry)
    db.commit()
    return {'ok': True}


@router.get('/search')
async def search(
    query: Optional[str] = None,
    page_size: int = 20,
    mode: str = 'search',
    platform: Optional[str] = None,
    genre: Optional[str] = None,
    page: int = 1,
    db: Session = Depends(get_db)
):
    client = RawgClient(db=db)
    page_size = max(1, min(page_size, 40))
    page = max(1, min(page, 50))
    platform_id = int(platform) if platform and platform.isdigit() else None
    prefer_popular = mode == 'autocomplete'
    if not query or not query.strip():
        if prefer_popular:
            return {'results': []}
        return await client.list_top_games(
            page_size=page_size,
            parent_platforms=platform_id,
            genres=genre,
            page=page
        )
    query = query.strip()
    ordering = '-metacritic' if prefer_popular else None
    res = await client.search_games(
        query,
        page_size=page_size,
        parent_platforms=platform_id,
        genres=genre,
        ordering=ordering,
        page=page
    )
    res['results'] = rank_results(query, res.get('results', []), prefer_popular=prefer_popular)
    return res


@router.get('/recommendations')
async def recommendations_api(
    page: int = 1,
    page_size: int = 8,
    db: Session = Depends(get_db)
):
    page_size = max(1, min(page_size, 20))
    recommendations, has_more = await build_recommendations(
        db,
        page=page,
        page_size=page_size
    )
    return {
        'results': recommendations,
        'next_page': page + 1 if has_more else None
    }
from fastapi.responses import StreamingResponse
import io
import csv

@router.get('/export/csv')
def export_csv(db: Session = Depends(get_db)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['game', 'status', 'rating', 'hours_played', 'favorite', 'start_date', 'end_date', 'comment'])
    for e in db.query(Entry).join(Game).all():
        writer.writerow([
            e.game.name,
            e.status,
            e.rating if e.rating is not None else '',
            e.hours_played if e.hours_played is not None else '',
            'yes' if e.favorite else 'no',
            e.start_date or '',
            e.end_date or '',
            (e.comment or '').replace('\n', ' ').strip()
        ])
    output.seek(0)
    headers = {'Content-Disposition': 'attachment; filename=gametracker.csv'}
    return StreamingResponse(iter([output.read()]), media_type='text/csv', headers=headers)
