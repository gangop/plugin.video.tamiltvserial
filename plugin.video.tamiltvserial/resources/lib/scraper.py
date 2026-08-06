# -*- coding: utf-8 -*-

import re

from utils import (
    api_get,
    get_featured_image,
    get_page_size,
    get_response_header,
    get_terms,
    log_error,
    strip_html,
)


MASKR_PATTERN = re.compile(r'https://maskr\.blog/[A-Za-z0-9]+')
MASKR_ONCLICK_PATTERN = re.compile(
    r'window\.open\(["\'](https://maskr\.blog/[A-Za-z0-9]+)["\']',
    re.I,
)
EPISODE_NUMBER_PATTERN = re.compile(r'Episode\s+(\d+)', re.I)
TITLE_DATE_PATTERN = re.compile(r'\s*\d{1,2}-\d{1,2}-\d{4}.*$')
TITLE_DATE_CAPTURE_PATTERN = re.compile(r'(\d{1,2})-(\d{1,2})-(\d{4})')


def extract_maskr_urls(html_content):
    content = html_content or ''
    urls = []
    seen = set()

    for pattern in (MASKR_PATTERN, MASKR_ONCLICK_PATTERN):
        for match in pattern.findall(content):
            if match not in seen:
                seen.add(match)
                urls.append(match)

    return urls


def list_posts(category_id=None, page=1, search=None):
    page_size = get_page_size(40)
    params = {
        '_embed': '1',
        'per_page': page_size,
        'page': page,
        'orderby': 'date',
        'order': 'desc',
    }
    if category_id:
        params['categories'] = category_id
    if search:
        params['search'] = search

    posts, headers = api_get('posts', params=params)
    total_pages = int(get_response_header(headers, 'X-WP-TotalPages', '1') or '1')
    return posts, page, total_pages


def list_child_categories(parent_id, include_empty=False):
    params = {
        'parent': parent_id,
        'per_page': 100,
        'orderby': 'name',
        'order': 'asc',
    }
    categories, _headers = api_get('categories', params=params)
    if include_empty:
        return categories
    return [cat for cat in categories if cat.get('count', 0) > 0]


def title_matches_serial(title, serial_name):
    if not title or not serial_name:
        return False
    return parse_show_title(title).lower() == serial_name.strip().lower()


def _serials_from_tamildhool_catalog(channel_id):
    """Build the serials menu from the CI-published consolidated catalog."""
    try:
        from tamildhool import load_active_serials
    except ImportError:
        return None

    entries = load_active_serials(channel_id)
    if not entries:
        return None

    serials = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = strip_html(entry.get('name') or '')
        if not name:
            continue
        category_id = entry.get('id')
        count = int(entry.get('count') or 0)
        item = {
            'id': category_id if category_id not in (None, '') else f'search:{name.lower()}',
            'name': name,
            'count': count,
        }
        if entry.get('folder'):
            item['folder'] = entry['folder']
        if entry.get('latest_date'):
            item['latest_date'] = entry['latest_date']
        if entry.get('latest_title'):
            item['latest_title'] = entry['latest_title']
        if entry.get('recent_episodes'):
            item['recent_episodes'] = entry['recent_episodes']
        # Empty / miscategorized TTS folders open via channel-scoped title search.
        if entry.get('search_query') or not category_id or count <= 0:
            item['search_query'] = entry.get('search_query') or name
            item['channel_id'] = entry.get('channel_id') or channel_id
        serials.append(item)

    # Always present serial folders A→Z regardless of catalog publish order.
    return sorted(serials, key=lambda item: (item.get('name') or '').lower()) or None


def catalog_recent_episodes(category_id=None, name=None, folder=None):
    """Return recent TamilDhool episodes from the published serials catalog."""
    try:
        from tamildhool import load_active_serials
    except ImportError:
        return []

    channels = load_active_serials(None)
    if not isinstance(channels, dict):
        return []

    name_key = (name or '').strip().lower()
    folder_key = (folder or '').strip().lower()
    for entries in channels.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if category_id and entry.get('id') == category_id:
                return list(entry.get('recent_episodes') or [])
            if category_id and str(entry.get('id')) == str(category_id):
                return list(entry.get('recent_episodes') or [])
            if folder_key and (entry.get('folder') or '').lower() == folder_key:
                return list(entry.get('recent_episodes') or [])
            if name_key and (entry.get('name') or '').strip().lower() == name_key:
                return list(entry.get('recent_episodes') or [])
    return []


def merge_catalog_episodes(posts, category_id=None, name=None, folder=None):
    """Append TamilDhool-only recent episodes that TamilTvSerial has not published yet."""
    recent = catalog_recent_episodes(category_id=category_id, name=name, folder=folder)
    if not recent:
        return posts

    seen_dates = set()
    for post in posts:
        title = strip_html(((post.get('title') or {}).get('rendered')) or post.get('title') or '')
        match = TITLE_DATE_CAPTURE_PATTERN.search(title)
        if match:
            seen_dates.add(
                f'{int(match.group(1)):02d}-{int(match.group(2)):02d}-{match.group(3)}'
            )

    extras = []
    for episode in recent:
        date = episode.get('date') or ''
        title = episode.get('title') or ''
        if not date or not title or date in seen_dates:
            continue
        seen_dates.add(date)
        # Synthetic WP-shaped post so normalize_post / play-by-title both work.
        extras.append({
            'id': f'td-{date}',
            'title': {'rendered': title},
            'excerpt': {'rendered': ''},
            'content': {'rendered': ''},
            'link': episode.get('page') or '',
            'date': '',
            'categories': [],
            '_td_only': True,
        })
    return extras + list(posts)


def list_serial_categories(channel_id):
    """List serial folders from the daily TamilDhool+TamilTvSerial consolidation.

    Falls back to live TamilTvSerial WP categories when the published catalog
    is missing.
    """
    catalog = _serials_from_tamildhool_catalog(channel_id)
    if catalog is not None:
        return catalog

    children = list_child_categories(channel_id, include_empty=True)
    serials = {}
    empty_by_name = {}

    for category in children:
        category_id = category.get('id')
        name = strip_html(category.get('name', ''))
        if not category_id or not name:
            continue
        if _is_show_channel_name(name):
            continue

        count = category.get('count', 0)
        if count > 0:
            serials[category_id] = {
                'id': category_id,
                'name': name,
                'count': count,
            }
            continue

        empty_by_name[name.lower()] = {
            'id': category_id,
            'name': name,
            'count': 0,
            'search_query': name,
            'channel_id': channel_id,
        }

    if empty_by_name:
        page = 1
        total_pages = 1
        while page <= total_pages and page <= 5:
            # Titles/dates only — skip _embed to shrink empty-category scans.
            posts, headers = api_get('posts', params={
                'categories': channel_id,
                'per_page': 100,
                'page': page,
                'orderby': 'date',
                'order': 'desc',
            })
            total_pages = int(get_response_header(headers, 'X-WP-TotalPages', '1') or '1')
            for post in posts:
                title = strip_html((post.get('title') or {}).get('rendered', ''))
                show_name = parse_show_title(title)
                key = show_name.lower()
                empty = empty_by_name.get(key)
                if not empty:
                    continue
                category_id = empty['id']
                if category_id not in serials:
                    serials[category_id] = {
                        'id': category_id,
                        'name': empty['name'],
                        'count': empty.get('count', 0),
                        'search_query': empty['name'],
                        'channel_id': channel_id,
                        'latest_title': title,
                        'latest_date': post.get('date', ''),
                    }
            page += 1

    return sorted(
        serials.values(),
        key=lambda item: (
            item.get('latest_date') or '',
            item.get('name') or '',
        ),
        reverse=True,
    )


def _is_show_channel_name(name):
    lower = (name or '').lower()
    return lower.endswith('tv shows') or lower == 'tamil tv shows' or lower.endswith('tv showz')


def _has_known_channel_title(title):
    lower = (title or '').lower()
    return any(
        token in lower
        for token in ('sun tv show', 'vijay tv show', 'zee tamil tv show')
    )


def _add_show_group(shows, category_id, name, latest=None, count=0, search_query=''):
    if not name:
        return
    key = category_id or f'search:{name.lower()}'
    if key in shows:
        return

    latest = latest or {}
    shows[key] = {
        'id': key,
        'name': name,
        'count': count,
        'latest_date': latest.get('date', ''),
        'latest_title': latest.get('title', ''),
        'latest_episode_number': latest.get('episode_number') or 0,
    }
    if search_query:
        shows[key]['search_query'] = search_query


def list_show_categories_by_latest_episode(
    channel_category_id,
    excluded_category_ids=None,
    show_channel_ids=None,
    only_unclassified=False,
):
    excluded = set(excluded_category_ids or [])
    excluded.add(channel_category_id)
    show_channels = set(show_channel_ids or [])
    shows = {}

    for category in list_child_categories(channel_category_id, include_empty=True):
        category_id = category.get('id')
        name = strip_html(category.get('name', ''))
        if not category_id or category_id in excluded or category_id in show_channels:
            continue
        if _is_show_channel_name(name):
            continue
        count = category.get('count', 0)
        _add_show_group(
            shows,
            category_id if count else '',
            name,
            count=count,
            search_query='' if count else name,
        )

    page = 1
    total_pages = 1

    while page <= total_pages and page <= 10:
        posts, headers = api_get('posts', params={
            'categories': channel_category_id,
            '_embed': '1',
            'per_page': 100,
            'page': page,
            'orderby': 'date',
            'order': 'desc',
        })
        total_pages = int(get_response_header(headers, 'X-WP-TotalPages', '1') or '1')

        for post in posts:
            latest = normalize_post(post)
            embedded = post.get('_embedded') or {}
            post_category_ids = set()
            for group in embedded.get('wp:term') or []:
                for term in group or []:
                    if term.get('taxonomy') == 'category' and term.get('id'):
                        post_category_ids.add(term.get('id'))

            if only_unclassified and (
                post_category_ids.intersection(show_channels)
                or _has_known_channel_title(latest.get('title', ''))
            ):
                continue

            found_show_category = False
            for group in embedded.get('wp:term') or []:
                for term in group or []:
                    if term.get('taxonomy') != 'category':
                        continue
                    category_id = term.get('id')
                    name = strip_html(term.get('name', ''))
                    if not category_id or category_id in excluded:
                        continue
                    if category_id in show_channels or _is_show_channel_name(name):
                        continue
                    found_show_category = True
                    if category_id not in shows or not shows[category_id].get('latest_date'):
                        shows.pop(category_id, None)
                        _add_show_group(
                            shows,
                            category_id,
                            name,
                            latest=latest,
                            count=term.get('count', 0),
                        )
            if not found_show_category:
                name = parse_show_title(latest.get('title', ''))
                _add_show_group(shows, '', name, latest=latest, search_query=name)
        page += 1

    return sorted(
        shows.values(),
        key=lambda item: (
            item.get('latest_date') or '',
            item.get('latest_episode_number') or 0,
            item.get('name') or '',
        ),
        reverse=True,
    )


def parse_episode_number(title):
    match = EPISODE_NUMBER_PATTERN.search(title or '')
    return int(match.group(1)) if match else None


def parse_show_title(title):
    title = strip_html(title or '')
    if '|' in title:
        title = title.split('|', 1)[0]
    title = TITLE_DATE_PATTERN.sub('', title)
    return re.sub(r'\s+', ' ', title).strip()


def normalize_post(post):
    content_html = (post.get('content') or {}).get('rendered', '')
    title = strip_html((post.get('title') or {}).get('rendered', 'Episode'))
    return {
        'id': post.get('id'),
        'title': title,
        'plot': strip_html((post.get('excerpt') or {}).get('rendered', '')),
        'thumb': get_featured_image(post),
        'link': post.get('link', ''),
        'date': post.get('date', ''),
        'categories': get_terms(post, 'category'),
        'content_html': content_html,
        'episode_number': parse_episode_number(title),
    }
