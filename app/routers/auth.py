import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import (
    EMAIL_RE,
    get_current_user,
    hash_password,
    login_user,
    logout_user,
    slugify,
    verify_password,
)
from ..deps import get_db
from ..models import User
from ..templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


def _unique_slug(db: Session, base: str) -> str:
    slug = slugify(base)
    candidate = slug
    n = 1
    while db.query(User).filter(User.profile_slug == candidate).first():
        n += 1
        candidate = f"{slug}-{n}"
    return candidate


@router.get('/login')
def login_form(request: Request, next: str = '/list', user=Depends(get_current_user)):
    if user:
        return RedirectResponse(url='/list', status_code=303)
    return templates.TemplateResponse(request, 'login.html', {'next': next, 'error': None})


@router.post('/login')
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form('/list'),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request, 'login.html',
            {'next': next, 'error': 'Incorrect email or password.'},
            status_code=401,
        )
    login_user(request, user)
    return RedirectResponse(url=next if next.startswith('/') else '/list', status_code=303)


@router.get('/register')
def register_form(request: Request, user=Depends(get_current_user)):
    if user:
        return RedirectResponse(url='/list', status_code=303)
    return templates.TemplateResponse(request, 'register.html', {'error': None})


@router.post('/register')
def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(''),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    display_name = display_name.strip()

    def fail(msg: str):
        return templates.TemplateResponse(
            request, 'register.html', {'error': msg}, status_code=400
        )

    if not EMAIL_RE.match(email):
        return fail('Please enter a valid email address.')
    if len(password) < 8:
        return fail('Password must be at least 8 characters.')
    if db.query(User).filter(User.email == email).first():
        return fail('An account with that email already exists.')

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name or email.split('@')[0],
        profile_slug=_unique_slug(db, display_name or email.split('@')[0]),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return fail('An account with that email already exists.')
    db.refresh(user)
    login_user(request, user)
    return RedirectResponse(url='/list', status_code=303)


@router.post('/logout')
def logout(request: Request):
    logout_user(request)
    return RedirectResponse(url='/login', status_code=303)
