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


def addon():
    return _addon


def localize(string_id):
    return _addon.getLocalizedString(string_id)


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
