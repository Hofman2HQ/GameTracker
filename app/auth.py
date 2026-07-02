"""Authentication: password hashing, session lookup, and route guards."""

import re

import bcrypt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import settings
from .deps import get_db
from .models import User

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class NotAuthenticated(Exception):
    """Raised by view routes when no user is logged in; handled by a redirect to /login."""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


def slugify(value: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')
    return slug or 'user'


def login_user(request: Request, user: User) -> None:
    request.session['user_id'] = user.id


def logout_user(request: Request) -> None:
    request.session.pop('user_id', None)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """The logged-in user, or None. Never raises — use the guards below to require auth."""
    user_id = request.session.get('user_id')
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def require_user_view(user: User | None = Depends(get_current_user)) -> User:
    """For HTML routes: redirect to /login when not authenticated."""
    if user is None:
        raise NotAuthenticated()
    return user


def require_user_api(user: User | None = Depends(get_current_user)) -> User:
    """For JSON routes: 401 when not authenticated."""
    if user is None:
        raise HTTPException(status_code=401, detail='Authentication required')
    return user
