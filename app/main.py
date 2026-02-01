from contextlib import asynccontextmanager
from pathlib import Path
import sys

if __package__ is None or __package__ == '':
    # Allow `python app/main.py` by adding the project root to sys.path.
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.database import init_db, SessionLocal
from app.routers import api, views

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield

app = FastAPI(title='GameTracker', lifespan=lifespan)

# Mount static files
app.mount('/static', StaticFiles(directory='app/static'), name='static')

# Templates (for views router)
templates = Jinja2Templates(directory='app/templates')

app.include_router(api.router, prefix='/api', tags=['api'])
app.include_router(views.router, tags=['views'])

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=8000, reload=True)
