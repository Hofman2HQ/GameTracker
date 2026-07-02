import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

if __package__ is None or __package__ == '':
    # Allow `python app/main.py` by adding the project root to sys.path.
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app import database, rawg
from app.auth import NotAuthenticated
from app.config import PROJECT_ROOT, settings
from app.database import SessionLocal, init_db
from app.models import User
from app.rawg import RawgAuthError, RawgError, RawgNotFoundError
from app.routers import api, auth, views
from app.templating import templates

logging.basicConfig(
    level=settings.log_level.upper(),
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger('gametracker')


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if not settings.rawg_api_key:
        logger.warning('RAWG_API_KEY is not set — search and game detail pages will fail. '
                       'Get a free key at https://rawg.io/apidocs and put it in .env')
    rawg.configure_shared_client()
    from app.cache import cleanup_expired_cache
    db = SessionLocal()
    try:
        deleted = cleanup_expired_cache(db)
        if deleted > 0:
            logger.info('Cleaned up %d expired cache entries', deleted)
    finally:
        db.close()
    yield
    rawg.close_shared_client()


app = FastAPI(
    title='GameTracker',
    version='1.0.0',
    lifespan=lifespan,
    docs_url='/api/docs',
    openapi_url='/api/openapi.json',
)

if settings.secret_key == 'dev-insecure-change-me-in-production':
    logger.warning('SECRET_KEY is the insecure dev default — set a stable random '
                   'SECRET_KEY in .env before deploying (sessions are forgeable otherwise).')

app.mount('/static', StaticFiles(directory=str(PROJECT_ROOT / 'app' / 'static')), name='static')

app.include_router(auth.router, tags=['auth'])
app.include_router(api.router, prefix='/api', tags=['api'])
app.include_router(views.router, tags=['views'])


@app.middleware('http')
async def load_user(request: Request, call_next):
    """Attach the logged-in user (or None) to request.state for templates/nav."""
    request.state.user = None
    if not request.url.path.startswith('/static'):
        user_id = request.session.get('user_id')
        if user_id:
            db = SessionLocal()
            try:
                request.state.user = db.query(User).filter(User.id == user_id).first()
            finally:
                db.close()
    return await call_next(request)


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, _exc: NotAuthenticated):
    return RedirectResponse(url=f'/login?next={request.url.path}', status_code=303)


CSP = (
    "default-src 'self'; "
    "img-src 'self' https: data:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "connect-src 'self'"
)


@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Content-Security-Policy', CSP)
    return response


# Added last so it is the OUTERMOST middleware: request.session must be
# populated before load_user (and the routes) read it.
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key,
                   session_cookie=settings.session_cookie, https_only=False,
                   same_site='lax')


@app.exception_handler(RawgError)
async def rawg_error_handler(request: Request, exc: RawgError):
    if isinstance(exc, RawgNotFoundError):
        status, message = 404, 'Game not found.'
    elif isinstance(exc, RawgAuthError):
        status, message = 502, 'The RAWG API key is missing or invalid. Set RAWG_API_KEY in .env.'
    else:
        status, message = 502, 'The RAWG game database is currently unreachable. Please try again shortly.'
    logger.warning('RAWG error on %s: %s', request.url.path, exc)
    if request.url.path.startswith('/api'):
        return JSONResponse(status_code=status, content={'detail': message})
    return templates.TemplateResponse(
        request,
        'error.html',
        {'status_code': status, 'message': message},
        status_code=status,
    )


@app.get('/healthz', include_in_schema=False)
def healthz():
    try:
        with database.engine.connect() as conn:
            conn.execute(text('SELECT 1'))
    except Exception:
        logger.exception('Health check failed')
        return JSONResponse(status_code=503, content={'status': 'error', 'database': 'unreachable'})
    return {'status': 'ok', 'version': app.version}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app.main:app', host='0.0.0.0', port=8000, reload=True)
