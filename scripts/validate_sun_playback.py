#!/usr/bin/env python3
"""Validate latest Sun TV playback using the local TamilDhool fallback index."""

import json
import ssl
import sys
import types
import urllib.error
import urllib.parse
import urllib.request


class FakeAddon:
    def getSetting(self, key):
        return '40' if key == 'page_size' else ''

    def log(self, _message, level=3):
        return None

    def getLocalizedString(self, _string_id):
        return ''

    def getAddonInfo(self, key):
        return {
            'name': 'Tamil TV Serial',
            'version': 'test',
            'enabled': 'true',
            'profile': '/tmp',
        }.get(key, '')


sys.modules['xbmcaddon'] = types.SimpleNamespace(Addon=lambda id=None: FakeAddon())
sys.path.insert(0, 'plugin.video.tamiltvserial/resources/lib')

import stream_resolver as sr  # noqa: E402
import tamildhool  # noqa: E402
import utils  # noqa: E402
from scraper import normalize_post  # noqa: E402
from utils import api_get  # noqa: E402


SHOWS = [
    'Aadukalam',
    'Annam',
    'Chellame Chellame',
    'Ethirneechal',
    'Iru Malargal',
    'Kayal',
    'Malli',
    'Manamagale Vaa',
    'Moondru Mudichu',
    'Poongodi',
    'Pudhu Vasantham',
    'Punitha',
    'Singappenne',
    'Thulasi',
    'Vinodhini',
]


def patch_network():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    def request_url_ssl(url, params=None, referer=utils.BASE_URL, method='GET', data=None, timeout=30):
        if params:
            query = urllib.parse.urlencode(params)
            url = f'{url}&{query}' if '?' in url else f'{url}?{query}'
        headers = {
            'User-Agent': utils.USER_AGENT,
            'Accept': 'application/json, text/html, */*',
            'Referer': referer,
        }
        body = None
        if data is not None:
            body = json.dumps(data).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=timeout, context=ctx) as response:
            return response.read(), dict(response.headers.items()), response.geturl()

    def build_opener(cookie_jar, verify_ssl=True):
        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        context = ssl.create_default_context() if verify_ssl else ctx
        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar),
            urllib.request.HTTPSHandler(context=context),
            NoRedirectHandler(),
        )

    def fetch(url, referer=sr.BASE_URL, timeout=20, opener=None):
        is_woodviolet = (
            'woodviolet.xyz' in (url or '').lower()
            or 'woodviolet.xyz' in (referer or '').lower()
        )
        headers = {
            'User-Agent': sr.WOODVIOLET_USER_AGENT if is_woodviolet else sr.USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Referer': referer,
        }
        if is_woodviolet:
            headers['Accept-Language'] = 'en-US,en;q=0.9'
        request = urllib.request.Request(url, headers=headers)
        opener = opener or urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
        try:
            with opener.open(request, timeout=timeout) as response:
                return (
                    sr._response_status(response),
                    response.read().decode('utf-8', 'replace'),
                    response.geturl(),
                    '',
                )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode('utf-8', 'replace') if exc.fp else ''
            return exc.code, body, url, exc.headers.get('Location', '')

    utils.request_url = request_url_ssl
    sr._build_opener = build_opener
    sr._fetch = fetch


def latest_episode(show):
    posts, _headers = api_get(
        'posts',
        params={
            'search': show,
            '_embed': '1',
            'per_page': 5,
            'orderby': 'date',
            'order': 'desc',
        },
    )
    compact_show = show.lower().replace(' ', '')
    for post in posts:
        episode = normalize_post(post)
        if compact_show in episode.get('title', '').lower().replace(' ', ''):
            return episode
    return normalize_post(posts[0]) if posts else None


def resolve_flow(episode):
    title = episode['title']
    indexed_url, indexed_referer, indexed_cookies = tamildhool.resolve_from_fallback_index(title)
    if indexed_url and sr.verify_stream_reachable(indexed_url, indexed_referer, indexed_cookies):
        return 'fallback-index', True, indexed_url

    stream_url, stream_referer, stream_cookies = sr.resolve_episode_stream(
        episode.get('content_html', ''),
        episode_link=episode.get('link', ''),
        episode_title=title,
        allow_fallback=False,
    )
    if stream_url:
        if not sr.stream_needs_preflight(stream_url, stream_referer):
            return 'primary', True, stream_url
        if sr.verify_stream_reachable(stream_url, stream_referer, stream_cookies):
            return 'primary', True, stream_url

    live_url, live_referer, live_cookies = sr.resolve_fallback_stream(title, use_index=False)
    if live_url and sr.verify_stream_reachable(live_url, live_referer, live_cookies):
        return 'fallback-live', True, live_url

    return 'failed', False, stream_url or live_url or ''


def main():
    patch_network()
    with open('fallback/tamildhool.json', encoding='utf-8') as handle:
        tamildhool._index_cache['data'] = json.load(handle)

    passed = 0
    for show in SHOWS:
        try:
            episode = latest_episode(show)
            if not episode:
                print(f'FAIL | {show} | no episode found')
                continue
            source, ok, stream_url = resolve_flow(episode)
            if ok:
                passed += 1
            print(
                f'{"PASS" if ok else "FAIL"} | {show} | {source} | '
                f'{episode["title"]} | {stream_url[:90]}'
            )
        except Exception as exc:
            print(f'ERROR | {show} | {type(exc).__name__}: {exc}')

    print(f'\nSUMMARY {passed}/{len(SHOWS)} passed')
    return 0 if passed == len(SHOWS) else 1


if __name__ == '__main__':
    raise SystemExit(main())
