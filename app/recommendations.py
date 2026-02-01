from typing import Any, Optional
from sqlalchemy.orm import Session

from .models import Game, Entry
from .rawg import RawgClient

MAX_RECOMMENDATION_PAGE = 50


def clamp_page(page: int, max_page: int = MAX_RECOMMENDATION_PAGE) -> int:
    return max(1, min(page, max_page))


async def build_recommendations(
    db: Session,
    page: int = 1,
    page_size: int = 8
) -> tuple[list[dict[str, Any]], bool]:
    page = clamp_page(page)
    page_size = max(1, min(page_size, 20))
    entries = db.query(Entry).join(Game).all()
    owned_ids = {entry.game.rawg_id for entry in entries if entry.game}
    if not entries:
        return [], False

    client = RawgClient()
    genres_catalog = await client.list_genres()
    platforms_catalog = await client.list_platforms()
    genre_slug_map = {g['name'].lower(): g['slug'] for g in genres_catalog}
    platform_catalog = [
        {'id': p['id'], 'name': p['name'], 'name_lower': p['name'].lower()}
        for p in platforms_catalog
    ]
    platform_id_map = {platform['name']: platform['id'] for platform in platform_catalog}
    platform_catalog.sort(key=lambda item: len(item['name_lower']), reverse=True)

    def map_parent_platform(name: str) -> Optional[dict[str, Any]]:
        lower = name.lower()
        for platform in platform_catalog:
            if platform['name_lower'] in lower:
                return platform
        return None

    genre_weights: dict[str, float] = {}
    platform_weights: dict[str, float] = {}
    for entry in entries:
        base = 1.0
        if entry.rating is not None:
            base += entry.rating / 2.0
        if entry.favorite:
            base += 2.0
        if entry.status == 'COMPLETED':
            base += 1.0
        for genre in entry.game.genres:
            genre_weights[genre] = genre_weights.get(genre, 0) + base
        for platform in entry.game.platforms:
            parent = map_parent_platform(platform)
            if parent:
                platform_weights[parent['name']] = platform_weights.get(parent['name'], 0) + base

    top_genre_names = [
        name for name, _ in sorted(genre_weights.items(), key=lambda item: item[1], reverse=True)
        if name.lower() in genre_slug_map
    ][:3]
    top_genre_slugs = [genre_slug_map[name.lower()] for name in top_genre_names[:2]]
    top_platform_names = [
        name for name, _ in sorted(platform_weights.items(), key=lambda item: item[1], reverse=True)
    ][:2]
    top_platform_ids = [
        platform_id_map[name]
        for name in top_platform_names
        if name in platform_id_map
    ]

    filters = []
    if top_genre_slugs and top_platform_ids:
        filters.append({'genres': top_genre_slugs[0], 'parent_platforms': top_platform_ids[0]})
    for slug in top_genre_slugs:
        filters.append({'genres': slug})
    for pid in top_platform_ids:
        filters.append({'parent_platforms': pid})
    if not filters:
        filters = [{}]

    seen_filters = set()
    unique_filters = []
    for item in filters:
        key = (item.get('genres'), item.get('parent_platforms'))
        if key in seen_filters:
            continue
        seen_filters.add(key)
        unique_filters.append(item)

    recommendations = []
    seen_ids = set()
    next_available = False
    target = page_size

    async def add_results(data: dict[str, Any]) -> None:
        nonlocal recommendations, next_available
        next_available = next_available or bool(data.get('next'))
        for g in data.get('results', []):
            gid = g.get('id')
            if not gid or gid in owned_ids or gid in seen_ids:
                continue
            genres = [genre.get('name') for genre in g.get('genres') or [] if genre.get('name')]
            platforms = [
                p.get('platform', {}).get('name')
                for p in g.get('platforms') or []
                if p.get('platform', {}).get('name')
            ]
            matched_genres = [name for name in genres if name in top_genre_names]
            matched_platforms = [name for name in platforms if name in top_platform_names]
            reasons = []
            if matched_genres:
                reasons.append(f"Matches your top genres: {', '.join(matched_genres[:2])}.")
            if matched_platforms:
                reasons.append(f"Available on {', '.join(matched_platforms[:2])}.")
            if g.get('metacritic'):
                reasons.append(f"Metacritic {g.get('metacritic')}.")
            if not reasons:
                reasons.append("Strong pick based on your list.")
            score = 0.0
            if g.get('metacritic'):
                score += g.get('metacritic') / 10.0
            score += len(matched_genres) * 2 + len(matched_platforms)
            recommendations.append({
                'id': gid,
                'name': g.get('name'),
                'background_image': g.get('background_image'),
                'released': g.get('released'),
                'metacritic': g.get('metacritic'),
                'genres': genres,
                'platforms': platforms,
                'reasons': reasons,
                'score': score,
            })
            seen_ids.add(gid)
            if len(recommendations) >= target:
                break

    for filter_set in unique_filters:
        data = await client.list_top_games(
            page_size=20,
            parent_platforms=filter_set.get('parent_platforms'),
            genres=filter_set.get('genres'),
            page=page
        )
        await add_results(data)
        if len(recommendations) >= target:
            break

    if len(recommendations) < target:
        data = await client.list_top_games(page_size=20, page=page)
        await add_results(data)

    recommendations.sort(key=lambda item: item['score'], reverse=True)
    return recommendations[:target], next_available
