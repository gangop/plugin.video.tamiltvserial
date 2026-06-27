#!/usr/bin/env python3
"""Standalone test for Tamil TV Serial stream resolution."""

import json
import re
import ssl
import sys
import types
import urllib.parse
import urllib.request

# Mock Kodi addon before importing plugin modules.
class FakeAddon:
    def getSetting(self, setting_id):
        return '40' if setting_id == 'page_size' else ''

    def log(self, message, level=3):
        print(f'  [log] {message}')

    def getLocalizedString(self, _string_id):
        return ''

    def getAddonInfo(self, key):
        return 'Tamil TV Serial'


sys.modules['xbmcaddon'] = types.SimpleNamespace(Addon=lambda: FakeAddon())

PLUGIN_LIB = 'plugin.video.tamiltvserial/resources/lib'
sys.path.insert(0, PLUGIN_LIB)

import stream_resolver as sr
from scraper import extract_maskr_urls, normalize_post
import utils
from utils import api_get, strip_html

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

_orig_request_url = utils.request_url


def _request_url_ssl(url, params=None, referer=utils.BASE_URL, method='GET', data=None, timeout=30):
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
    with urllib.request.urlopen(request, timeout=timeout, context=SSL_CTX) as response:
        payload = response.read()
        headers_out = dict(response.headers.items())
        return payload, headers_out, response.geturl()


utils.request_url = _request_url_ssl


def patch_fetch():
    def _fetch(url, referer=sr.BASE_URL, timeout=20, opener=None):
        is_woodviolet = (
            'woodviolet.xyz' in (url or '').lower()
            or 'woodviolet.xyz' in (referer or '').lower()
        )
        user_agent = sr.WOODVIOLET_USER_AGENT if is_woodviolet else sr.USER_AGENT
        headers = {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Referer': referer,
        }
        if is_woodviolet:
            headers['Accept-Language'] = 'en-US,en;q=0.9'
        request = urllib.request.Request(url, headers=headers)
        opener = opener or urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=SSL_CTX),
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                return getattr(response, 'status', response.getcode()), response.read().decode('utf-8', 'replace'), response.geturl(), ''
        except urllib.error.HTTPError as exc:
            location = exc.headers.get('Location', '')
            body = exc.read().decode('utf-8', 'replace') if exc.fp else ''
            return exc.code, body, url, location

    def _build_opener(cookie_jar, verify_ssl=True):
        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        context = SSL_CTX
        if verify_ssl:
            context = ssl.create_default_context()

        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar),
            urllib.request.HTTPSHandler(context=context),
            NoRedirectHandler(),
        )

    sr._fetch = _fetch
    sr._build_opener = _build_opener


def search_latest_episode(query='Ethir Neechal'):
    posts, _headers = api_get('posts', params={
        'search': query,
        '_embed': '1',
        'per_page': 1,
        'orderby': 'date',
        'order': 'desc',
    })
    return normalize_post(posts[0]) if posts else None


def main():
    patch_fetch()
    query = sys.argv[1] if len(sys.argv) > 1 else 'Ethir Neechal'

    print(f"Searching for: {query}")
    episode = search_latest_episode(query)
    if not episode:
        print('No episodes found.')
        return 1

    print(f"Latest: {episode['title']} ({episode['date'][:10]})")
    maskr_urls = extract_maskr_urls(episode['content_html'])
    print(f"Play links found: {len(maskr_urls)}")
    for index, url in enumerate(maskr_urls, 1):
        print(f"  Source {index}: {url}")

    stream_url, stream_referer = sr.resolve_episode_stream(
        episode['content_html'],
        episode_link=episode['link'],
    )

    if stream_url:
        print(f"\nSUCCESS: {stream_url}")
        print(f"Referer: {stream_referer}")
        return 0

    print('\nFAILED: Could not resolve stream URL')
    return 1


if __name__ == '__main__':
    sys.exit(main())
