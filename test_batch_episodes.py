#!/usr/bin/env python3
"""Test stream resolution for the last N episodes of a serial."""

import json
import ssl
import sys
import types
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

FETCH_TIMEOUT = 12
EPISODE_TIMEOUT = 45
PER_PAGE = 8


class FakeAddon:
    def getSetting(self, setting_id):
        return '40' if setting_id == 'page_size' else ''

    def log(self, message, level=3):
        pass

    def getLocalizedString(self, _string_id):
        return ''

    def getAddonInfo(self, key):
        return 'Tamil TV Serial'


def setup():
    sys.modules['xbmcaddon'] = types.SimpleNamespace(Addon=lambda: FakeAddon())
    sys.path.insert(0, 'plugin.video.tamiltvserial/resources/lib')

    import stream_resolver as sr
    import utils

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    def request_url_ssl(url, params=None, referer=utils.BASE_URL, method='GET', data=None, timeout=30):
        if params:
            query = urllib.parse.urlencode(params)
            url = f'{url}&{query}' if '?' in url else f'{url}?{query}'
        request = urllib.request.Request(
            url,
            headers={
                'User-Agent': utils.USER_AGENT,
                'Accept': 'application/json, text/html, */*',
                'Referer': referer,
            },
            method=method,
        )
        with urllib.request.urlopen(request, timeout=timeout, context=ctx) as response:
            return response.read(), dict(response.headers.items()), response.geturl()

    def fetch(url, referer=sr.BASE_URL, timeout=FETCH_TIMEOUT, opener=None):
        request = urllib.request.Request(
            url,
            headers={
                'User-Agent': sr.USER_AGENT,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Referer': referer,
            },
        )
        opener = opener or urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.status, response.read().decode('utf-8', 'replace'), response.geturl(), ''
        except urllib.error.HTTPError as exc:
            body = exc.read().decode('utf-8', 'replace') if exc.fp else ''
            return exc.code, body, url, exc.headers.get('Location', '')

    def build_opener(cookie_jar):
        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar),
            urllib.request.HTTPSHandler(context=ctx),
            NoRedirectHandler(),
        )

    utils.request_url = request_url_ssl
    sr._fetch = fetch
    sr._build_opener = build_opener
    return sr, utils, ctx


def verify_m3u8(url, ctx):
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(request, timeout=12, context=ctx) as response:
            return response.status == 200 and b'#EXTM3U' in response.read(256)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False


def test_episode(sr, ctx, episode):
    from scraper import extract_maskr_urls

    stream = sr.resolve_episode_stream(
        episode['content_html'],
        episode_link=episode['link'],
    )
    return {
        'episode': episode.get('episode_number'),
        'date': episode['date'][:10],
        'title': episode['title'],
        'links': len(extract_maskr_urls(episode['content_html'])),
        'resolved': bool(stream),
        'playable': verify_m3u8(stream, ctx) if stream else False,
        'stream': stream,
    }


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else 'Ethir Neechal'
    count = int(sys.argv[2]) if len(sys.argv) > 2 else PER_PAGE

    sr, utils, ctx = setup()
    from scraper import normalize_post
    from utils import api_get

    categories, _ = api_get('categories', params={'search': query.split()[0], 'per_page': 20})
    category = None
    for item in categories:
        name = item.get('name', '').lower()
        if all(part.lower() in name for part in query.split()[:2]):
            category = item
            break
    if not category and categories:
        category = categories[0]
    if not category:
        print(f'No category found for {query!r}')
        return 1

    posts, _ = api_get('posts', params={
        'categories': category['id'],
        '_embed': '1',
        'per_page': count,
        'orderby': 'date',
        'order': 'desc',
    })
    episodes = [normalize_post(post) for post in posts]

    print(f"Testing last {len(episodes)} episodes of {category['name']}\n")
    print(f"{'Ep':>4} {'Date':<12} {'Links':>5} {'Stream':>8} {'Play':>6}")
    print('-' * 44)

    results = []
    with ThreadPoolExecutor(max_workers=1) as executor:
        for episode in episodes:
            future = executor.submit(test_episode, sr, ctx, episode)
            try:
                result = future.result(timeout=EPISODE_TIMEOUT)
            except FuturesTimeout:
                result = {
                    'episode': episode.get('episode_number'),
                    'date': episode['date'][:10],
                    'title': episode['title'],
                    'links': 0,
                    'resolved': False,
                    'playable': False,
                    'stream': '',
                    'timeout': True,
                }

            results.append(result)
            stream_label = 'OK' if result['resolved'] else ('TIMEOUT' if result.get('timeout') else 'FAIL')
            play_label = 'OK' if result['playable'] else '-'
            print(
                f"{str(result['episode']):>4} {result['date']:<12} "
                f"{result['links']:>5} {stream_label:>8} {play_label:>6}"
            )

    resolved = sum(1 for item in results if item['resolved'])
    playable = sum(1 for item in results if item['playable'])
    print('-' * 44)
    print(f"Resolved: {resolved}/{len(results)}   Playable: {playable}/{len(results)}")
    return 0 if playable == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
