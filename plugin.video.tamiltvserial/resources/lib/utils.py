# -*- coding: utf-8 -*-

import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import xbmc
from xbmcaddon import Addon

from constants import ADDON_ID, API_URL, BASE_URL, USER_AGENT


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
    30037: 'Install InputStream Adaptive from Kodi\'s official add-on repository (VideoPlayer InputStream), then try again.',
    30038: 'InputStream Adaptive required',
    30039: 'Could not reach TamilTvSerial.com. Check your internet connection and try again.',
    30040: 'Something went wrong. Please try again.',
    30041: 'InputStream Adaptive is installed but disabled. Go to My add-ons → VideoPlayer InputStream → InputStream Adaptive → Enable.',
    30042: 'Connection Test',
    30043: 'Connection test passed',
    30044: 'Connection test failed',
}


def encode_header_value(value):
    return urllib.parse.quote(str(value), safe='')


def set_list_label(list_item, label):
    if not label:
        return
    try:
        list_item.setLabel(label)
    except AttributeError:
        pass


def set_video_info(list_item, info_dict):
    try:
        info = list_item.getVideoInfoTag()
    except AttributeError:
        list_item.setInfo('video', info_dict)
        return

    title = info_dict.get('title')
    if title:
        info.setTitle(title)
    plot = info_dict.get('plot')
    if plot:
        info.setPlot(plot)
    media_type = info_dict.get('mediatype') or info_dict.get('media_type')
    if media_type:
        info.setMediaType(media_type)
    tvshowtitle = info_dict.get('tvshowtitle')
    if tvshowtitle:
        info.setTvShowTitle(tvshowtitle)
    episode = info_dict.get('episode')
    if episode is not None:
        info.setEpisode(episode)


def safe_api_get(path, params=None):
    try:
        return api_get(path, params=params)
    except Exception as exc:
        log_error(f'API request failed for {path}: {exc}')
        raise


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


def log(message, level=xbmc.LOGINFO):
    xbmc.log(f'[{ADDON_ID}] {message}', level)


def log_error(message):
    log(message, level=xbmc.LOGERROR)


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


def is_hls_url(url):
    lower = (url or '').lower()
    path = lower.split('?', 1)[0]
    return path.endswith('.m3u8') or '.m3u8' in path


def inputstream_adaptive_status():
    try:
        isa = Addon('inputstream.adaptive')
        enabled = isa.getAddonInfo('enabled')
        if enabled in ('true', '1', True):
            return 'ready'
        return 'disabled'
    except Exception as exc:
        log_error(f'InputStream Adaptive check failed: {exc}')
        return 'missing'


def has_inputstream_adaptive():
    return inputstream_adaptive_status() == 'ready'


def playback_referer(referer):
    referer = (referer or BASE_URL).strip()
    lower = referer.lower()
    if 'vimeocdn.com' in lower:
        return 'https://player.vimeo.com/'
    return referer or BASE_URL


def build_stream_headers(referer=None):
    referer = playback_referer(referer)
    parts = [
        f'User-Agent={encode_header_value(USER_AGENT)}',
        f'Referer={encode_header_value(referer)}',
    ]
    return '&'.join(parts)


def build_playback_url(stream_url, referer=None):
    headers = build_stream_headers(referer)
    return f'{stream_url}|{headers}' if headers else stream_url


def apply_stream_properties(list_item, stream_url, referer=None):
    headers = build_stream_headers(referer)
    playback_url = build_playback_url(stream_url, referer)
    list_item.setPath(playback_url)

    if is_hls_url(stream_url):
        list_item.setMimeType('application/vnd.apple.mpegurl')
        list_item.setProperty('inputstream', 'inputstream.adaptive')
        list_item.setProperty('inputstreamaddon', 'inputstream.adaptive')
        list_item.setProperty('inputstream.adaptive.manifest_type', 'hls')
        list_item.setProperty('inputstream.adaptive.manifest_headers', headers)
        list_item.setProperty('inputstream.adaptive.stream_headers', headers)
        list_item.setProperty('inputstream.adaptive.common_headers', headers)
        list_item.setProperty('inputstream.adaptive.is_realtime_stream', 'false')
        return

    try:
        if stream_url.lower().split('?', 1)[0].endswith('.mp4'):
            list_item.setMimeType('video/mp4')
            return
    except Exception as exc:
        log_error(f'Failed to set stream properties: {exc}')
