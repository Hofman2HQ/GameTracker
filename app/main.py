from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .database import init_db, SessionLocal

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield

app = FastAPI(title='GameTracker', lifespan=lifespan)

# Mount static files
app.mount('/static', StaticFiles(directory='app/static'), name='static')

# Templates (for views router)
templates = Jinja2Templates(directory='app/templates')

# Routers
from .routers import api, views  # noqa
app.include_router(api.router, prefix='/api', tags=['api'])
app.include_router(views.router, tags=['views'])

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=8000, reload=True)
