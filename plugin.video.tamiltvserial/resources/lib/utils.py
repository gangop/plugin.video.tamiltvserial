# -*- coding: utf-8 -*-

import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from xbmcaddon import Addon

from constants import API_URL, BASE_URL, USER_AGENT


_addon = Addon()

_STRING_FALLBACKS = {
    30001: 'General',
    30002: 'Episodes per page',
    30003: 'Enable search',
    30010: 'Latest Episodes',
    30011: 'Browse by Channel',
    30012: 'Search',
    30013: 'Sun TV Serials',
    30014: 'Vijay TV Serials',
    30015: 'Zee Tamil Serials',
    30016: 'Tamil TV Shows',
    30017: 'Next page',
    30018: 'Enter search term',
    30019: 'No episodes found',
    30020: 'Could not resolve stream URL',
    30021: 'Resolving stream...',
    30022: 'Favorites',
    30023: 'Auto-play next episode',
    30031: 'Add to Favorites',
    30032: 'Remove from Favorites',
    30033: 'Added to favorites',
    30034: 'No favorites yet. Long-press a serial and choose Add to Favorites.',
    30035: 'Removed from favorites',
    30036: 'Playing next episode...',
}


def addon():
    return _addon


def localize(string_id):
    try:
        numeric_id = int(string_id)
    except (TypeError, ValueError):
        return str(string_id)

    value = _addon.getLocalizedString(numeric_id)
    if value:
        return value
    return _STRING_FALLBACKS.get(numeric_id, '')


def get_setting_int(setting_id, default=0):
    value = _addon.getSetting(setting_id)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_setting_bool(setting_id, default=False):
    value = _addon.getSetting(setting_id)
    if value in ('true', '1'):
        return True
    if value in ('false', '0', ''):
        return default
    return default


def log(message, level=3):
    _addon.log(str(message), level)


def log_error(message):
    log(message, level=4)


def build_plugin_url(base_url, **params):
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    return f'{base_url}?{query}' if query else base_url


def strip_html(text):
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', ' ', text)
    return html.unescape(re.sub(r'\s+', ' ', text)).strip()


def request_url(url, params=None, referer=BASE_URL, method='GET', data=None, timeout=30):
    if params:
        query = urllib.parse.urlencode(params)
        url = f'{url}&{query}' if '?' in url else f'{url}?{query}'

    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'application/json, text/html, */*',
        'Referer': referer,
    }
    body = None
    if data is not None:
        body = json.dumps(data).encode('utf-8')
        headers['Content-Type'] = 'application/json'

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            headers_out = dict(response.headers.items())
            return payload, headers_out, response.geturl()
    except urllib.error.HTTPError as exc:
        log_error(f'HTTP error {exc.code} for {url}')
        raise
    except urllib.error.URLError as exc:
        log_error(f'URL error for {url}: {exc.reason}')
        raise


def api_get(path, params=None):
    url = API_URL + path.lstrip('/')
    payload, headers, _final_url = request_url(url, params=params)
    data = json.loads(payload.decode('utf-8'))
    return data, headers


def get_featured_image(post):
    embedded = post.get('_embedded') or {}
    media_items = embedded.get('wp:featuredmedia') or []
    if not media_items:
        return ''
    media = media_items[0] or {}
    return media.get('source_url') or ''


def get_terms(post, taxonomy='category'):
    embedded = post.get('_embedded') or {}
    terms = embedded.get('wp:term') or []
    collected = []
    for group in terms:
        for term in group or []:
            if term.get('taxonomy') == taxonomy:
                collected.append(term.get('name', ''))
    return collected
