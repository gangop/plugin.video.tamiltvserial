#!/usr/bin/env python3
"""Simulate Kodi play action without xbmc."""

import ssl
import sys
import types
import urllib.error
import urllib.request


class FakeAddon:
    def __init__(self, addon_id=None):
        self.addon_id = addon_id or 'plugin.video.tamiltvserial'

    def getSetting(self, setting_id):
        return '40' if setting_id == 'page_size' else ''

    def log(self, message, level=3):
        print(f'  [log:{level}] {message}')

    def getLocalizedString(self, string_id):
        return f'str{string_id}'

    def getAddonInfo(self, key):
        info = {
            'name': 'Tamil TV Serial',
            'version': 'test',
            'enabled': 'true',
            'profile': '/tmp/tamiltvserial-test-profile',
            'path': '/tmp/tamiltvserial-test-addon',
        }
        if self.addon_id == 'inputstream.adaptive':
            info['enabled'] = 'true'
        return info.get(key, '')


class FakeListItem:
    def __init__(self, label='', path=''):
        self.label = label
        self.path = path
        self.properties = {}
        self.art = {}

    def setLabel(self, label):
        self.label = label

    def setArt(self, art):
        self.art = art

    def setProperty(self, key, value):
        self.properties[key] = value

    def setMimeType(self, mime):
        self.properties['mimetype'] = mime

    def setPath(self, path):
        self.path = path

    def getPath(self):
        return self.path

    def setContentLookup(self, value):
        self.properties['contentlookup'] = value

    def getVideoInfoTag(self):
        raise AttributeError('no videoinfotag')

    def setInfo(self, kind, info):
        self.properties['info'] = info


RESOLVED = {'called': False, 'success': False, 'path': ''}


def fake_set_resolved(handle, success, list_item):
    RESOLVED['called'] = True
    RESOLVED['success'] = success
    RESOLVED['path'] = getattr(list_item, 'path', '')
    print(f'  setResolvedUrl({success}, path={RESOLVED["path"][:80]}...)')
    print(f'  properties: {getattr(list_item, "properties", {})}')


sys.modules['xbmcaddon'] = types.SimpleNamespace(Addon=lambda id=None: FakeAddon(id))
sys.modules['xbmcgui'] = types.SimpleNamespace(
    ListItem=FakeListItem,
    Dialog=lambda: types.SimpleNamespace(
        notification=lambda *a, **k: None,
        ok=lambda *a, **k: None,
    ),
    NOTIFICATION_INFO=1,
    NOTIFICATION_ERROR=2,
    Window=lambda *a: types.SimpleNamespace(
        getProperty=lambda k: '',
        setProperty=lambda k, v: None,
        clearProperty=lambda k: None,
    ),
)
sys.modules['xbmcplugin'] = types.SimpleNamespace(
    setResolvedUrl=fake_set_resolved,
    endOfDirectory=lambda *a, **k: print('  endOfDirectory'),
    addDirectoryItem=lambda *a, **k: None,
    setContent=lambda *a, **k: None,
    addSortMethod=lambda *a, **k: None,
    SORT_METHOD_DATE=1,
    SORT_METHOD_LABEL=2,
)
sys.modules['xbmc'] = types.SimpleNamespace(executebuiltin=lambda cmd: print(f'  builtin: {cmd[:80]}'))

PLUGIN_LIB = 'plugin.video.tamiltvserial/resources/lib'
sys.path.insert(0, PLUGIN_LIB)

import stream_resolver as sr
from scraper import list_posts, normalize_post
import utils

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

_orig_fetch = sr._fetch


def _fetch(url, referer=sr.BASE_URL, timeout=45, opener=None):
    headers = {
        'User-Agent': sr.USER_AGENT,
        'Accept': '*/*',
        'Referer': referer,
    }
    request = urllib.request.Request(url, headers=headers)
    opener = opener or urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=SSL_CTX),
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return (
                sr._response_status(response),
                response.read().decode('utf-8', 'replace'),
                response.geturl(),
                '',
            )
    except urllib.error.HTTPError as exc:
        location = exc.headers.get('Location', '')
        body = exc.read().decode('utf-8', 'replace') if exc.fp else ''
        return exc.code, body, url, location


sr._fetch = _fetch


def _build_opener(cookie_jar, verify_ssl=True):
    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    context = ssl.create_default_context() if verify_ssl else SSL_CTX
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar),
        urllib.request.HTTPSHandler(context=context),
        NoRedirectHandler(),
    )


sr._build_opener = _build_opener

_orig_request_url = utils.request_url


def _request_url_ssl(url, params=None, referer=utils.BASE_URL, method='GET', data=None, timeout=30):
    import json
    import urllib.parse

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


def main():
    from router import Router
    from scraper import normalize_post
    from utils import api_get

    posts, _headers = api_get('posts', params={
        'search': 'Ethir Neechal',
        '_embed': '1',
        'per_page': '1',
        'orderby': 'date',
        'order': 'desc',
    })
    if not posts:
        print('No posts found')
        return 1

    episode = normalize_post(posts[0])
    print(f'Episode: {episode["title"]}')

    router = Router('plugin://plugin.video.tamiltvserial/', 1)
    router.play({'action': 'play', 'post_id': str(episode['id'])})

    if not RESOLVED['called']:
        print('FAIL: setResolvedUrl never called')
        return 1
    if not RESOLVED['success']:
        print('FAIL: setResolvedUrl returned False')
        return 1
    if '.m3u8' not in RESOLVED['path'] or 'User-Agent=' not in RESOLVED['path']:
        print(f'FAIL: expected direct HLS playback URL with headers, got {RESOLVED["path"]}')
        return 1
    if 'vimeocdn.com' not in RESOLVED['path']:
        print('FAIL: playback URL missing stream host')
        return 1
    print('PASS: play action completed with direct HLS playback URL')
    return 0


if __name__ == '__main__':
    sys.exit(main())
