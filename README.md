# GameTracker (FastAPI)

End-to-end game tracking app inspired by MyAnimeList.

- Add games from RAWG search
- Track status: PLAN, PLAYING, COMPLETED, DROPPED
- Ratings, comments, hours played, start/end dates, favorite
- Stats page with totals and average rating
- CSV export of your list (`/api/export/csv`)

## Setup

1) Ensure Python 3.10+

2) Install dependencies:

```
pip install -r requirements.txt
```

3) Configure your RAWG API key (already set by default):

- `.env`
```
RAWG_API_KEY=7038320ea036447db7d54309ac42cd54
```

4) Run the server:

```
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

- My List: `/list`
- Search: `/search`
- Game detail: `/game/{rawg_id}`
- Stats: `/stats`
- JSON API: `/api/*`

The SQLite DB is `gametracker.db` in the project root.

## Notes
- This is single-user by design. Adding auth/multi-user can be layered later.
- RAWG requests are server-side; your API key stays on the server.
- Image domains are loaded directly from RAWG’s URLs.
