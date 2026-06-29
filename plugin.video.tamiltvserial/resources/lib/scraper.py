# -*- coding: utf-8 -*-

import re

from utils import api_get, get_featured_image, get_terms, get_setting_int, log_error, strip_html


MASKR_PATTERN = re.compile(r'https://maskr\.blog/[A-Za-z0-9]+')
MASKR_ONCLICK_PATTERN = re.compile(
    r'window\.open\(["\'](https://maskr\.blog/[A-Za-z0-9]+)["\']',
    re.I,
)
EPISODE_NUMBER_PATTERN = re.compile(r'Episode\s+(\d+)', re.I)
TITLE_DATE_PATTERN = re.compile(r'\s*\d{1,2}-\d{1,2}-\d{4}.*$')


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


def extract_maskr_url(html_content):
    urls = extract_maskr_urls(html_content)
    return urls[0] if urls else ''


def list_posts(category_id=None, page=1, search=None):
    page_size = get_setting_int('page_size', 40)
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
    total_pages = int(headers.get('X-WP-TotalPages', headers.get('x-wp-totalpages', '1')))
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
        total_pages = int(headers.get('X-WP-TotalPages', headers.get('x-wp-totalpages', '1')))

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


def get_post_by_slug(slug):
    posts, _headers = api_get('posts', params={'slug': slug, '_embed': '1'})
    return posts[0] if posts else None


def parse_episode_number(title):
    match = EPISODE_NUMBER_PATTERN.search(title or '')
    return int(match.group(1)) if match else None


def parse_show_title(title):
    title = strip_html(title or '')
    if '|' in title:
        title = title.split('|', 1)[0]
    title = TITLE_DATE_PATTERN.sub('', title)
    return re.sub(r'\s+', ' ', title).strip()


def find_next_post_id(category_id, current_post_id, current_title):
    target_number = parse_episode_number(current_title)
    if target_number is None:
        return ''

    wanted_number = target_number + 1
    page = 1
    total_pages = 1

    while page <= total_pages and page <= 10:
        posts, _, total_pages = list_posts(category_id=category_id, page=page)
        for post in posts:
            if post.get('id') == current_post_id:
                continue
            title = strip_html((post.get('title') or {}).get('rendered', ''))
            if parse_episode_number(title) == wanted_number:
                return str(post['id'])
        page += 1

    return ''


def next_post_id_from_list(posts, current_index):
    if current_index <= 0:
        return ''
    return str(posts[current_index - 1].get('id', ''))


def normalize_post(post):
    content_html = (post.get('content') or {}).get('rendered', '')
    return {
        'id': post.get('id'),
        'title': strip_html((post.get('title') or {}).get('rendered', 'Episode')),
        'plot': strip_html((post.get('excerpt') or {}).get('rendered', '')),
        'thumb': get_featured_image(post),
        'link': post.get('link', ''),
        'date': post.get('date', ''),
        'categories': get_terms(post, 'category'),
        'maskr_url': extract_maskr_url(content_html),
        'maskr_urls': extract_maskr_urls(content_html),
        'content_html': content_html,
        'episode_number': parse_episode_number(
            strip_html((post.get('title') or {}).get('rendered', ''))
        ),
    }
