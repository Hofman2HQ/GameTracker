import csv
import io
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..auth import require_user_api
from ..config import STATUSES
from ..deps import get_db  # noqa: F401  (re-exported for tests/overrides)
from ..models import APICache, Entry, Game, RecommendationFeedback, User
from ..rawg import RawgClient, rank_results
from ..recommendations import build_recommendations
from ..schemas import EntryCreate, EntryOut, EntryUpdate
from ..services import annotate_owned, ensure_game
from ..upcoming import month_year_to_dates

router = APIRouter()


def _validate_entry_dates(start_date: str | None, end_date: str | None, released: str | None) -> None:
    """Dates are ISO strings (schema-validated), so string comparison is chronological."""
    if released:
        for label, value in (('start_date', start_date), ('end_date', end_date)):
            if value and value < released:
                raise HTTPException(
                    status_code=422,
                    detail=f"{label} {value} is before the game's release date ({released})",
                )
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=422, detail='end_date is before start_date')


@router.get('/statuses')
def list_statuses():
    return STATUSES


@router.get('/entries', response_model=list[EntryOut])
def list_entries(
    status: str | None = None,
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_user_api),
):
    q = (
        db.query(Entry)
        .join(Game)
        .options(joinedload(Entry.game))
        .filter(Entry.user_id == user.id)
        .order_by(Entry.updated_at.desc())
    )
    if status:
        q = q.filter(Entry.status == status)
    return q.offset(offset).limit(limit).all()


@router.post('/entries', response_model=EntryOut, status_code=201)
def add_entry(payload: EntryCreate, db: Session = Depends(get_db),
              user: User = Depends(require_user_api)):
    game = ensure_game(db, payload.rawg_id, RawgClient(db=db))
    _validate_entry_dates(payload.start_date, payload.end_date, game.released)
    existing = db.query(Entry).filter(
        Entry.game_id == game.id, Entry.user_id == user.id
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail='Game already in your list')
    entry = Entry(
        user_id=user.id,
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
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request added the same game between our check and commit.
        db.rollback()
        raise HTTPException(status_code=409, detail='Game already in your list') from None
    db.refresh(entry)
    return entry


@router.patch('/entries/{entry_id}', response_model=EntryOut)
def update_entry(entry_id: int, payload: EntryUpdate, db: Session = Depends(get_db),
                 user: User = Depends(require_user_api)):
    entry = db.query(Entry).filter(
        Entry.id == entry_id, Entry.user_id == user.id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail='Entry not found')
    updates = payload.model_dump(exclude_unset=True)
    _validate_entry_dates(
        updates.get('start_date', entry.start_date),
        updates.get('end_date', entry.end_date),
        entry.game.released,
    )
    for field, value in updates.items():
        setattr(entry, field, value)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete('/entries/{entry_id}')
def delete_entry(entry_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_user_api)):
    entry = db.query(Entry).filter(
        Entry.id == entry_id, Entry.user_id == user.id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail='Entry not found')
    db.delete(entry)
    db.commit()
    return {'ok': True}


@router.get('/search')
def search(
    query: str | None = None,
    page_size: int = 20,
    mode: str = 'search',
    platform: str | None = None,
    genre: str | None = None,
    year: int | None = None,
    month: int | None = None,
    page: int = 1,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_api),
):
    client = RawgClient(db=db)
    page_size = max(1, min(page_size, 40))
    page = max(1, min(page, 50))
    platform_id = int(platform) if platform and platform.isdigit() else None
    dates = month_year_to_dates(year, month)
    prefer_popular = mode == 'autocomplete'
    if not query or not query.strip():
        if prefer_popular:
            return {'results': []}
        # Browse view: most-added (popular) first, not Metacritic.
        res = client.list_top_games(
            page_size=page_size,
            parent_platforms=platform_id,
            genres=genre,
            page=page,
            ordering='-added',
            dates=dates,
        )
        annotate_owned(db, res.get('results', []), user.id)
        return res
    query = query.strip()
    ordering = '-metacritic' if prefer_popular else None
    res = client.search_games(
        query,
        page_size=page_size,
        parent_platforms=platform_id,
        genres=genre,
        ordering=ordering,
        page=page,
        dates=dates,
    )
    res['results'] = rank_results(query, res.get('results', []), prefer_popular=prefer_popular)
    annotate_owned(db, res['results'], user.id)
    return res


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
def recommendations_api(
    page: int = 1,
    page_size: int = 8,
    platforms: list[str] | None = Query(default=None),
    refresh: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_user_api),
):
    page_size = max(1, min(page_size, 20))
    recommendations, has_more = build_recommendations(
        db,
        user.id,
        page=page,
        page_size=page_size,
        platform_ids=_parse_platform_ids(platforms),
        force_refresh=refresh,
    )
    return {
        'results': recommendations,
        'next_page': page + 1 if has_more else None
    }


class FeedbackPayload(BaseModel):
    rawg_id: int
    name: str = ''
    genres: list[str] = []
    platforms: list[str] = []
    direction: str  # 'more' | 'less' | 'dismiss'


DIRECTION_VALUES = {'more': 1, 'less': -1, 'dismiss': 0}


@router.post('/recommendations/feedback')
def set_recommendation_feedback(payload: FeedbackPayload, db: Session = Depends(get_db),
                                user: User = Depends(require_user_api)):
    """Record recommendation feedback — clicking the same choice again clears it.

    'more'/'less' shift the taste weights; 'dismiss' only hides the game.
    """
    if payload.direction not in DIRECTION_VALUES:
        raise HTTPException(status_code=422, detail="direction must be 'more', 'less' or 'dismiss'")
    value = DIRECTION_VALUES[payload.direction]
    row = db.query(RecommendationFeedback).filter(
        RecommendationFeedback.user_id == user.id,
        RecommendationFeedback.rawg_id == payload.rawg_id,
    ).first()
    if row and row.direction == value:
        db.delete(row)
        db.commit()
        return {'rawg_id': payload.rawg_id, 'direction': None}
    if row:
        row.direction = value
    else:
        row = RecommendationFeedback(
            user_id=user.id,
            rawg_id=payload.rawg_id,
            name=payload.name,
            genres_json=json.dumps(payload.genres) if payload.genres else None,
            platforms_json=json.dumps(payload.platforms) if payload.platforms else None,
            direction=value,
        )
        db.add(row)
    db.commit()
    return {'rawg_id': payload.rawg_id, 'direction': payload.direction}


@router.get('/export/csv')
def export_csv(db: Session = Depends(get_db), user: User = Depends(require_user_api)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['game', 'status', 'rating', 'hours_played', 'favorite',
                     'start_date', 'end_date', 'comment'])
    for e in db.query(Entry).join(Game).options(joinedload(Entry.game)).filter(
            Entry.user_id == user.id).all():
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


@router.get('/export/json')
def export_json(db: Session = Depends(get_db), user: User = Depends(require_user_api)):
    """Full backup: every entry with the game snapshot needed to re-import it."""
    items = []
    for e in db.query(Entry).join(Game).options(joinedload(Entry.game)).filter(
            Entry.user_id == user.id).all():
        items.append({
            'rawg_id': e.game.rawg_id,
            'name': e.game.name,
            'slug': e.game.slug,
            'background_image': e.game.background_image,
            'released': e.game.released,
            'metacritic': e.game.metacritic,
            'genres': e.game.genres,
            'platforms': e.game.platforms,
            'status': e.status,
            'rating': e.rating,
            'comment': e.comment,
            'hours_played': e.hours_played,
            'favorite': e.favorite,
            'start_date': e.start_date,
            'end_date': e.end_date,
        })
    payload = {'version': 1, 'entries': items}
    headers = {'Content-Disposition': 'attachment; filename=gametracker-backup.json'}
    return StreamingResponse(
        iter([json.dumps(payload, indent=2)]),
        media_type='application/json',
        headers=headers,
    )


class ImportEntry(BaseModel):
    rawg_id: int
    name: str
    slug: str = ''
    background_image: str | None = None
    released: str | None = None
    metacritic: int | None = None
    genres: list[str] | None = None
    platforms: list[str] | None = None
    status: str = 'PLAN'
    rating: int | None = Field(default=None, ge=0, le=10)
    comment: str | None = None
    hours_played: float | None = Field(default=None, ge=0.0)
    favorite: bool = False
    start_date: str | None = None
    end_date: str | None = None


class ImportPayload(BaseModel):
    version: int = 1
    entries: list[ImportEntry]


@router.post('/import/json')
def import_json(payload: ImportPayload, db: Session = Depends(get_db),
                user: User = Depends(require_user_api)) -> dict[str, Any]:
    """Restore a backup produced by /api/export/json into the current user's list.

    Games are upserted from the snapshot (no RAWG calls needed); entries for
    games already in your list are skipped, never overwritten.
    """
    imported = 0
    skipped = 0
    for item in payload.entries:
        if item.status not in STATUSES:
            skipped += 1
            continue
        game = db.query(Game).filter(Game.rawg_id == item.rawg_id).first()
        if not game:
            game = Game(
                rawg_id=item.rawg_id,
                slug=item.slug,
                name=item.name,
                background_image=item.background_image,
                released=item.released,
                metacritic=item.metacritic,
                genres_json=json.dumps(item.genres) if item.genres else None,
                platforms_json=json.dumps(item.platforms) if item.platforms else None,
            )
            db.add(game)
            db.flush()
        existing = db.query(Entry).filter(
            Entry.game_id == game.id, Entry.user_id == user.id
        ).first()
        if existing:
            skipped += 1
            continue
        db.add(Entry(
            user_id=user.id,
            game_id=game.id,
            status=item.status,
            rating=item.rating,
            comment=item.comment,
            hours_played=item.hours_played,
            favorite=item.favorite,
            start_date=item.start_date,
            end_date=item.end_date,
        ))
        imported += 1
    db.commit()
    return {'imported': imported, 'skipped': skipped}


@router.post('/debug/refresh')
def debug_refresh(db: Session = Depends(get_db),
                  user: User = Depends(require_user_api)) -> dict[str, Any]:
    """Non-destructive: drop the shared RAWG response cache and mark every stored
    game stale so the next page view refetches fresh data. Your list is untouched."""
    cache_cleared = db.query(APICache).delete()
    games_marked = db.query(Game).update({Game.last_rawg_fetch: None})
    db.commit()
    return {'cache_cleared': cache_cleared, 'games_marked_stale': games_marked}


@router.post('/debug/reset')
def debug_reset(db: Session = Depends(get_db),
                user: User = Depends(require_user_api)) -> dict[str, Any]:
    """Destructive: wipe THIS user's library — their entries and recommendation
    feedback. Shared game data and cache are left intact."""
    entries = db.query(Entry).filter(Entry.user_id == user.id).delete()
    feedback = db.query(RecommendationFeedback).filter(
        RecommendationFeedback.user_id == user.id
    ).delete()
    db.commit()
    return {'entries_deleted': entries, 'feedback_deleted': feedback}
