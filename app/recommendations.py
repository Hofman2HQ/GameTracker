import math
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from .models import Entry, Game, RecommendationFeedback
from .rawg import RawgClient
from .timeutil import utcnow

MAX_RECOMMENDATION_PAGE = 50

# How strongly a single "more/less like this" click shifts the taste profile,
# relative to library entries (whose per-entry affinity is roughly -3..+5).
FEEDBACK_GENRE_BOOST = 3.0
FEEDBACK_PLATFORM_BOOST = 1.5

# Candidate scoring blend: taste match dominates, quality and popularity
# break ties, recency nudges newer titles up.
GENRE_MATCH_WEIGHT = 3.0
PLATFORM_MATCH_WEIGHT = 1.0
QUALITY_WEIGHT = 2.0
POPULARITY_WEIGHT = 1.0
RECENCY_BONUS = 0.4
RECENT_RELEASE_DAYS = 900

# Greedy diversity re-rank: each already-picked game of the same lead genre
# costs the next candidate this much score.
DIVERSITY_PENALTY = 0.6

MAX_API_CALLS = 4


def clamp_page(page: int, max_page: int = MAX_RECOMMENDATION_PAGE) -> int:
    return max(1, min(page, max_page))


def entry_affinity(entry: Entry) -> float:
    """Signed taste signal for one library entry.

    Loving a game pushes its genres up; dropping it or rating it poorly pushes
    them down — a shelf full of abandoned shooters should stop producing
    shooter recommendations.
    """
    affinity = 0.5  # owning it at all shows mild interest
    if entry.status == 'COMPLETED':
        affinity += 1.0
    elif entry.status == 'PLAYING':
        affinity += 1.5  # what the user plays *now* is the freshest signal
    elif entry.status == 'DROPPED':
        affinity -= 1.5
    if entry.rating is not None:
        affinity += (entry.rating - 5.5) / 2.0  # 10 → +2.25, 1 → -2.25
    if entry.favorite:
        affinity += 2.0
    return affinity


def _is_recent(released: str | None) -> bool:
    if not released:
        return False
    cutoff = (utcnow() - timedelta(days=RECENT_RELEASE_DAYS)).date().isoformat()
    return released >= cutoff


def build_recommendations(
    db: Session,
    page: int = 1,
    page_size: int = 8,
    platform_ids: list[int] | None = None,
    force_refresh: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    page = clamp_page(page)
    page_size = max(1, min(page_size, 20))
    # Explicit platform filter (checkboxes) overrides the inferred platform,
    # and uses RAWG's comma-separated parent_platforms for "X or Y" semantics.
    platform_filter = ','.join(str(p) for p in platform_ids) if platform_ids else None
    entries = db.query(Entry).join(Game).all()
    owned_ids = {entry.game.rawg_id for entry in entries if entry.game}
    if not entries:
        return [], False

    feedback_rows = db.query(RecommendationFeedback).all()
    feedback_by_id = {f.rawg_id: f.direction for f in feedback_rows}
    # direction -1 = "less like this", 0 = dismissed; neither may reappear.
    hidden_ids = {f.rawg_id for f in feedback_rows if f.direction <= 0}

    client = RawgClient(db=db)
    genres_catalog = client.list_genres()
    platforms_catalog = client.list_platforms()
    genre_slug_map = {g['name'].lower(): g['slug'] for g in genres_catalog}
    platform_catalog = [
        {'id': p['id'], 'name': p['name'], 'name_lower': p['name'].lower()}
        for p in platforms_catalog
    ]
    platform_id_map = {platform['name']: platform['id'] for platform in platform_catalog}
    platform_catalog.sort(key=lambda item: len(item['name_lower']), reverse=True)

    def map_parent_platform(name: str) -> dict[str, Any] | None:
        lower = name.lower()
        for platform in platform_catalog:
            if platform['name_lower'] in lower:
                return platform
        return None

    # ── taste profile: signed genre/platform weights ────────────────────────
    genre_weights: dict[str, float] = {}
    platform_weights: dict[str, float] = {}
    for entry in entries:
        affinity = entry_affinity(entry)
        for genre in entry.game.genres:
            genre_weights[genre] = genre_weights.get(genre, 0) + affinity
        for platform in entry.game.platforms:
            parent = map_parent_platform(platform)
            if parent:
                platform_weights[parent['name']] = platform_weights.get(parent['name'], 0) + affinity

    # "More/less like this" feedback shifts the same weights (dismiss = 0 = no shift).
    for row in feedback_rows:
        for genre in row.genres:
            genre_weights[genre] = genre_weights.get(genre, 0) + FEEDBACK_GENRE_BOOST * row.direction
        for platform in row.platforms:
            parent = map_parent_platform(platform)
            if parent:
                platform_weights[parent['name']] = (
                    platform_weights.get(parent['name'], 0) + FEEDBACK_PLATFORM_BOOST * row.direction
                )

    top_genre_names = [
        name for name, weight in sorted(genre_weights.items(), key=lambda item: item[1], reverse=True)
        if name.lower() in genre_slug_map and weight > 0
    ][:3]
    top_genre_slugs = [genre_slug_map[name.lower()] for name in top_genre_names]
    top_platform_names = [
        name for name, weight in sorted(platform_weights.items(), key=lambda item: item[1], reverse=True)
        if weight > 0
    ][:2]
    top_platform_ids = [
        platform_id_map[name]
        for name in top_platform_names
        if name in platform_id_map
    ]

    # Normalized signed scores in [-1, 1] so scoring is proportional to how
    # much the user actually likes each genre, not just whether it matched.
    max_genre_weight = max((abs(w) for w in genre_weights.values()), default=1.0) or 1.0
    genre_scores = {name: weight / max_genre_weight for name, weight in genre_weights.items()}
    max_platform_weight = max((abs(w) for w in platform_weights.values()), default=1.0) or 1.0
    platform_scores = {name: weight / max_platform_weight for name, weight in platform_weights.items()}

    # When the user pins platforms, every query is constrained to them;
    # otherwise fall back to the platform inferred from their taste.
    def platform_for(query_platform: int | str | None) -> int | str | None:
        return platform_filter if platform_filter else query_platform

    # ── diverse query set (each response is cached for 24h) ─────────────────
    queries: list[dict[str, Any]] = []
    if top_genre_slugs:
        queries.append({
            'genres': top_genre_slugs[0],
            'parent_platforms': top_platform_ids[0] if top_platform_ids else None,
        })
        # Popularity ordering surfaces beloved games that lack a Metacritic score.
        queries.append({'genres': top_genre_slugs[0], 'ordering': '-added'})
    for slug in top_genre_slugs[1:]:
        queries.append({'genres': slug})
    queries.append({})  # generic top-rated, for breadth beyond known tastes

    seen_filters = set()
    unique_queries = []
    for item in queries:
        key = (item.get('genres'), item.get('parent_platforms'), item.get('ordering'))
        if key in seen_filters:
            continue
        seen_filters.add(key)
        unique_queries.append(item)

    # ── collect candidates ───────────────────────────────────────────────────
    candidates: dict[int, dict[str, Any]] = {}
    next_available = False
    target = page_size
    platform_id_set = set(platform_ids) if platform_ids else None

    def on_selected_platform(platforms: list[str]) -> bool:
        if platform_id_set is None:
            return True
        for name in platforms:
            parent = map_parent_platform(name)
            if parent and parent['id'] in platform_id_set:
                return True
        return False

    def add_candidates(data: dict[str, Any]) -> None:
        nonlocal next_available
        next_available = next_available or bool(data.get('next'))
        for g in data.get('results', []):
            gid = g.get('id')
            if not gid or gid in owned_ids or gid in hidden_ids or gid in candidates:
                continue
            genres = [genre.get('name') for genre in g.get('genres') or [] if genre.get('name')]
            platforms = [
                p.get('platform', {}).get('name')
                for p in g.get('platforms') or []
                if p.get('platform', {}).get('name')
            ]
            if not on_selected_platform(platforms):
                continue
            candidates[gid] = {
                'id': gid,
                'name': g.get('name'),
                'background_image': g.get('background_image'),
                'released': g.get('released'),
                'metacritic': g.get('metacritic'),
                'added': g.get('added') or 0,
                'genres': genres,
                'platforms': platforms,
            }

    api_calls = 0
    for query in unique_queries:
        if api_calls >= MAX_API_CALLS:
            break
        # Stop early once there is a healthy pool to rank from.
        if len(candidates) >= target * 3:
            break
        data = client.list_top_games(
            page_size=20,
            parent_platforms=platform_for(query.get('parent_platforms')),
            genres=query.get('genres'),
            ordering=query.get('ordering', '-metacritic'),
            page=page,
            force_refresh=force_refresh,
        )
        api_calls += 1
        add_candidates(data)

    # ── score ────────────────────────────────────────────────────────────────
    def score_candidate(c: dict[str, Any]) -> float:
        genre_affinity = sum(genre_scores.get(g, 0.0) for g in c['genres'])
        parent_names = {p['name'] for p in (map_parent_platform(name) for name in c['platforms']) if p}
        platform_affinity = sum(platform_scores.get(name, 0.0) for name in parent_names)
        quality = (c['metacritic'] or 0) / 100.0
        popularity = min(math.log10(c['added'] + 1) / 4.0, 1.0)
        score = (
            GENRE_MATCH_WEIGHT * max(min(genre_affinity, 2.0), -2.0)
            + PLATFORM_MATCH_WEIGHT * max(min(platform_affinity, 1.0), -1.0)
            + QUALITY_WEIGHT * quality
            + POPULARITY_WEIGHT * popularity
        )
        if _is_recent(c['released']):
            score += RECENCY_BONUS
        return score

    def liked_genres(c: dict[str, Any]) -> list[str]:
        """The candidate's own genres that match the user's taste, best first."""
        liked = [g for g in c['genres'] if genre_scores.get(g, 0) > 0.15]
        liked.sort(key=lambda g: genre_scores[g], reverse=True)
        return liked

    def display_genres(c: dict[str, Any]) -> list[str]:
        # Surface taste-matched genres first so a genre cited in the "strong
        # match" reason is always among the (truncated) genre chips on the card.
        liked = liked_genres(c)
        return liked + [g for g in c['genres'] if g not in liked]

    def build_reasons(c: dict[str, Any]) -> list[str]:
        reasons = []
        liked = liked_genres(c)
        if liked:
            reasons.append(f"Strong match for your taste in {', '.join(liked[:2])}.")
        matched_platforms = [name for name in c['platforms'] if name in top_platform_names]
        if matched_platforms:
            reasons.append(f"Available on {', '.join(matched_platforms[:2])}.")
        if c['metacritic']:
            if c['metacritic'] >= 85:
                reasons.append(f"Critically acclaimed — Metacritic {c['metacritic']}.")
            else:
                reasons.append(f"Metacritic {c['metacritic']}.")
        if c['added'] >= 5000:
            reasons.append("Popular with players.")
        if _is_recent(c['released']):
            reasons.append("Recent release.")
        if not reasons:
            reasons.append("A quality pick beyond your usual genres.")
        return reasons[:3]

    def display_platforms(platforms: list[str]) -> list[str]:
        # When platforms are pinned, surface the matching ones first so the
        # (truncated) platform chips visibly reflect the active filter.
        if not platform_id_set:
            return platforms
        matched, rest = [], []
        for name in platforms:
            parent = map_parent_platform(name)
            (matched if parent and parent['id'] in platform_id_set else rest).append(name)
        return matched + rest

    scored = [(score_candidate(c), c) for c in candidates.values()]
    scored.sort(key=lambda item: item[0], reverse=True)

    # ── greedy diversity re-rank: don't fill the page with one genre ────────
    picked: list[dict[str, Any]] = []
    lead_genre_counts: dict[str, int] = {}
    pool = scored[:]
    while pool and len(picked) < target:
        best_index = 0
        best_adjusted = float('-inf')
        for i, (score, c) in enumerate(pool):
            lead = c['genres'][0] if c['genres'] else ''
            adjusted = score - DIVERSITY_PENALTY * lead_genre_counts.get(lead, 0)
            if adjusted > best_adjusted:
                best_adjusted = adjusted
                best_index = i
        score, chosen = pool.pop(best_index)
        lead = chosen['genres'][0] if chosen['genres'] else ''
        lead_genre_counts[lead] = lead_genre_counts.get(lead, 0) + 1
        picked.append({
            'id': chosen['id'],
            'name': chosen['name'],
            'background_image': chosen['background_image'],
            'released': chosen['released'],
            'metacritic': chosen['metacritic'],
            'genres': display_genres(chosen),
            'platforms': display_platforms(chosen['platforms']),
            'reasons': build_reasons(chosen),
            'score': round(score, 2),
            'feedback': 'more' if feedback_by_id.get(chosen['id']) == 1 else None,
        })

    return picked, next_available
