# -*- coding: utf-8 -*-

import base64
import html
import json
import os
import re
import time
from urllib.parse import parse_qs, urlparse

from utils import addon, log_error, request_url


LIVE_TV_INDEX_URL = 'https://tamilradios.org/free-tamil-live-tv'
LIVE_TV_REFERER = 'https://tamilradios.org/'
CACHE_TTL_SECONDS = 6 * 60 * 60
CACHE_FILE = 'livetv_channels.json'

_SECTION_FREE = 'Free Tamil Live TV'
_SECTION_LOCAL = 'Tamil Local TV Channels'

_LINK_RE = re.compile(
    r'<a[^>]+href="(https://tamilradios\.org/livetv/([^"]+))"[^>]*title="([^"]*)"[^>]*>'
    r'\s*<img[^>]+src="([^"]+)"',
    re.I | re.S,
)
_PLAYER_RE = re.compile(r'class="myplayer2">(.*?)</div>', re.I | re.S)
_OBFUSCATED_MPD_RE = re.compile(
    r'^https((?:[a-z0-9-]+\.)+(?:dev|com|net|org|tv|io|app|xyz|live|cloud|info|me|cc))(.+)$',
    re.I,
)


def _cache_path():
    return os.path.join(addon().getAddonInfo('profile'), CACHE_FILE)


def _load_cache():
    path = _cache_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if time.time() - float(payload.get('fetched_at') or 0) > CACHE_TTL_SECONDS:
        return None
    sections = payload.get('sections')
    if not isinstance(sections, list) or not sections:
        return None
    return sections


def _save_cache(sections):
    path = _cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({'fetched_at': time.time(), 'sections': sections}, handle)
    except OSError as exc:
        log_error(f'Live TV cache write failed: {exc}')


def _clean_title(title):
    title = html.unescape(title or '').strip()
    lower = title.lower()
    if lower.startswith('watch live '):
        title = title[11:].strip()
    return title


def _parse_index_html(page_html):
    free_at = page_html.find('>Free Tamil Live TV<')
    local_at = page_html.find('>Tamil Local TV Channels<')
    if free_at < 0:
        free_at = 0
    if local_at < 0:
        local_at = len(page_html)

    chunks = (
        (_SECTION_FREE, page_html[free_at:local_at]),
        (_SECTION_LOCAL, page_html[local_at:]),
    )
    sections = []
    seen = set()
    for section_name, chunk in chunks:
        channels = []
        for href, slug, title, thumb in _LINK_RE.findall(chunk):
            slug = slug.strip('/')
            if not slug or slug in seen:
                continue
            seen.add(slug)
            channels.append({
                'slug': slug,
                'title': _clean_title(title) or slug.replace('-', ' ').title(),
                'url': href.split('?', 1)[0],
                'thumb': html.unescape(thumb),
            })
        if channels:
            sections.append({'name': section_name, 'channels': channels})
    return sections


def list_live_tv_sections(force_refresh=False):
    if not force_refresh:
        cached = _load_cache()
        if cached:
            return cached

    payload, _headers, _final = request_url(
        LIVE_TV_INDEX_URL,
        referer=LIVE_TV_REFERER,
        timeout=30,
    )
    page_html = payload.decode('utf-8', 'replace')
    sections = _parse_index_html(page_html)
    if sections:
        _save_cache(sections)
    return sections


def deobfuscate_stream_url(value):
    value = html.unescape(value or '').strip()
    if not value:
        return ''
    if value.startswith('http://') or value.startswith('https://'):
        return value.rstrip('?') if value.endswith('?') else value
    match = _OBFUSCATED_MPD_RE.match(value)
    if match:
        return f'https://{match.group(1)}/{match.group(2).lstrip("/")}'
    return value


def _stream_from_player_url(player_url):
    parsed = urlparse(html.unescape(player_url))
    query = parse_qs(parsed.query)
    stream_url = deobfuscate_stream_url((query.get('mpd') or [''])[0])
    if not stream_url:
        return None
    key_id = (query.get('keyId') or [None])[0]
    key = (query.get('key') or [None])[0]
    lower = stream_url.lower().split('?', 1)[0]
    stream_type = 'dash' if lower.endswith('.mpd') else 'hls'
    return {
        'type': stream_type,
        'url': stream_url,
        'key_id': key_id,
        'key': key,
        'referer': LIVE_TV_REFERER,
    }


def resolve_live_stream(page_url):
    """Fetch a channel page and extract the playable stream descriptor."""
    payload, _headers, _final = request_url(
        page_url,
        referer=LIVE_TV_INDEX_URL,
        timeout=30,
    )
    page_html = payload.decode('utf-8', 'replace')
    match = _PLAYER_RE.search(page_html)
    block = html.unescape(match.group(1) if match else page_html)

    yt = re.search(r'youtube\.com/embed/([A-Za-z0-9_-]+)', block)
    if yt:
        return {
            'type': 'youtube',
            'video_id': yt.group(1),
            'url': f'https://www.youtube.com/watch?v={yt.group(1)}',
            'referer': LIVE_TV_REFERER,
        }

    for iframe in re.findall(r'<iframe[^>]+src="([^"]+)"', block, re.I):
        if 'dashplayer.php' in iframe or 'playermpd.html' in iframe:
            resolved = _stream_from_player_url(iframe)
            if resolved:
                return resolved

    for src in re.findall(r'<source[^>]+src="([^"]+)"', block, re.I):
        if 'dashplayer.php' in src or 'playermpd.html' in src:
            resolved = _stream_from_player_url(src)
            if resolved:
                return resolved
        if '.m3u8' in src:
            return {
                'type': 'hls',
                'url': html.unescape(src),
                'referer': LIVE_TV_REFERER,
            }
        if '.mpd' in src:
            return {
                'type': 'dash',
                'url': html.unescape(src),
                'referer': LIVE_TV_REFERER,
            }

    log_error(f'No live stream found on {page_url}')
    return None


def clearkey_license_payload(key_id, key):
    """Build InputStream Adaptive ClearKey license JSON from hex kid/key."""
    if not key_id or not key:
        return ''
    try:
        kid_raw = bytes.fromhex(key_id)
        key_raw = bytes.fromhex(key)
    except ValueError:
        log_error('Invalid ClearKey hex values for live TV stream')
        return ''

    def b64url(raw):
        return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')

    return json.dumps({
        'keys': [{'kty': 'oct', 'kid': b64url(kid_raw), 'k': b64url(key_raw)}],
        'type': 'temporary',
    })
