# -*- coding: utf-8 -*-

import re

from utils import api_get, get_featured_image, get_terms, get_setting_int, log_error, strip_html


MASKR_PATTERN = re.compile(r'https://maskr\.blog/[A-Za-z0-9]+')
MASKR_ONCLICK_PATTERN = re.compile(
    r'window\.open\(["\'](https://maskr\.blog/[A-Za-z0-9]+)["\']',
    re.I,
)
EPISODE_NUMBER_PATTERN = re.compile(r'Episode\s+(\d+)', re.I)


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


def list_child_categories(parent_id):
    params = {
        'parent': parent_id,
        'per_page': 100,
        'orderby': 'name',
        'order': 'asc',
    }
    categories, _headers = api_get('categories', params=params)
    return [cat for cat in categories if cat.get('count', 0) > 0]


def get_post_by_slug(slug):
    posts, _headers = api_get('posts', params={'slug': slug, '_embed': '1'})
    return posts[0] if posts else None


def parse_episode_number(title):
    match = EPISODE_NUMBER_PATTERN.search(title or '')
    return int(match.group(1)) if match else None


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
