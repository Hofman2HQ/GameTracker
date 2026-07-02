# GameTracker

A fast, self-hosted game tracking app inspired by MyAnimeList — built with FastAPI, SQLAlchemy, and the [RAWG](https://rawg.io) game database.

[![CI](https://github.com/Hofman2HQ/GameTracker/actions/workflows/ci.yml/badge.svg)](https://github.com/Hofman2HQ/GameTracker/actions/workflows/ci.yml)

## Features

- **Search & discover** — search RAWG's 500k+ game catalog with smart relevance ranking, autocomplete, and platform/genre filters
- **Track your library** — status (PLAN / PLAYING / COMPLETED / DROPPED), 0–10 ratings, hours played, start/end dates, favorites, comments
- **Stats dashboard** — totals, average rating, completion rate, hours, rating distribution, top genres/platforms, longest games
- **Personalized recommendations** — scored suggestions based on your ratings, favorites, and completed games
- **Data portability** — one-click CSV export plus full JSON backup and restore (`/api/export/json` → `/api/import/json`)
- **Offline-friendly** — RAWG responses are cached in SQLite (search 1h, game details 7d), so repeat browsing costs zero API quota
- **Resilient** — RAWG outages degrade gracefully with friendly banners instead of error pages; requests retry with backoff
- **Dark mode**, responsive mobile layout, and a clean JSON API with OpenAPI docs at `/api/docs`

## Quick start

Requires Python 3.11+ and a free [RAWG API key](https://rawg.io/apidocs).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env         # then put your RAWG_API_KEY in .env
uvicorn app.main:app --reload
```

Open http://localhost:8000

### Docker

```bash
echo "RAWG_API_KEY=your_key_here" > .env
docker compose up -d
```

Data persists in the `gametracker-data` volume. The container runs as a non-root user with a built-in health check.

## Pages & API

| Route | Purpose |
|---|---|
| `/list` | Your library with filtering and sorting |
| `/search` | Search / browse the RAWG catalog |
| `/game/{rawg_id}` | Game detail + your entry editor |
| `/stats` | Stats dashboard |
| `/recommendations` | Personalized suggestions |
| `/api/docs` | Interactive OpenAPI documentation |
| `/healthz` | Health check (DB connectivity) |

Key API endpoints: `GET/POST /api/entries`, `PATCH/DELETE /api/entries/{id}`, `GET /api/search`, `GET /api/export/csv`, `GET /api/export/json`, `POST /api/import/json`.

## Configuration

Set via environment variables or `.env` (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `RAWG_API_KEY` | — | **Required.** RAWG API key |
| `SECRET_KEY` | dev default | **Set in production.** Signs session cookies (`python -c "import secrets;print(secrets.token_hex(32))"`) |
| `DATABASE_URL` | `sqlite:///<project>/gametracker.db` | Any SQLAlchemy URL |
| `BCRYPT_ROUNDS` | `12` | Password hashing cost |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `HTTP_TIMEOUT_SECONDS` | `10` | RAWG request timeout |
| `HTTP_RETRIES` | `2` | RAWG retry attempts (backoff-spaced) |
| `GAME_REFRESH_DAYS` | `30` | How often stored game details are re-fetched from RAWG |
| `CACHE_TTL_SEARCH` | `86400` (24h) | Search result cache lifetime (seconds) |
| `CACHE_TTL_LIST` | `86400` (24h) | Browse/top-list cache lifetime (seconds) |
| `CACHE_TTL_CATALOG` | `604800` (7d) | Genre/platform catalog cache lifetime (seconds) |
| `CACHE_TTL_GAME` | `2592000` (30d) | Raw game payload cache lifetime (seconds) |

RAWG's free tier allows 20,000 requests/month; with these defaults the app asks RAWG for a given search or game at most once a day (or once a month for stored game details), so normal use stays in the hundreds of requests per month. Raise `GAME_REFRESH_DAYS` further if you care more about quota than fresh Metacritic scores.

## Development

```bash
pip install -r requirements-dev.txt
pytest            # 160 tests, no network needed
ruff check .      # lint
```

CI runs lint + tests on Python 3.11–3.13 and builds the Docker image on every push/PR.

## Architecture notes

- **Multi-user.** Email + password accounts with signed session cookies (bcrypt-hashed passwords). All library data is scoped per user; app pages require login, the JSON API returns 401 when unauthenticated. Public profiles are opt-in at `/u/{slug}`. Set a stable `SECRET_KEY` before deploying.
- **SQLite in WAL mode** with foreign keys enforced; one-entry-per-game is enforced **per user** by a DB unique constraint, not just app logic. For real concurrent load, point `DATABASE_URL` at Postgres.
- **RAWG access** goes through a shared pooled HTTP client with retries; all failures map to typed errors handled centrally (JSON for `/api/*`, friendly error page for views).
- **RAWG access** goes through a shared pooled HTTP client with retries; all failures map to typed errors handled centrally (JSON for `/api/*`, friendly error page for views).
- **Backups**: `GET /api/export/json` produces a self-contained snapshot (no RAWG calls needed to restore). Import skips entries that already exist — it never overwrites your data.
