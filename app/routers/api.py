import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Game, Entry
from ..schemas import EntryCreate, EntryUpdate, EntryOut, GameOut
from ..rawg import RawgClient
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
    # Ensure game exists in DB
    game = db.query(Game).filter(Game.rawg_id == payload.rawg_id).first()
    if not game:
        client = RawgClient()
        data = await client.get_game(payload.rawg_id)
        mapped = client.map_game_payload(data)
        game = Game(**mapped)
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
async def search(query: str):
    client = RawgClient()
    res = await client.search_games(query, page_size=20)
    return res
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
