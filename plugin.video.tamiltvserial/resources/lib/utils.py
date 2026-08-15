# -*- coding: utf-8 -*-

import html
import os
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from xbmcaddon import Addon
try:
    import xbmc
except ImportError:
    xbmc = None

from constants import ADDON_ID, API_URL, BASE_URL, USER_AGENT, WOODVIOLET_USER_AGENT


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
    30045: 'Serials',
    30046: 'Shows',
    30047: 'This episode\'s stream host is temporarily unavailable. Try again later, or play a different serial.',
    30048: 'Playback start timeout (seconds)',
    30049: 'Trying alternate stream source...',
    30050: 'Playback failed to start. Try another episode or check your connection.',
    30051: 'Live TV',
    30052: 'No live TV channels found',
    30053: 'Could not play this live channel. Try another channel or try again later.',
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


# Enum labels for settings.xml page_size (index → count).
_PAGE_SIZE_CHOICES = (20, 40, 60, 80, 100)


def get_page_size(default=40):
    """Episodes per page from settings (enum index or legacy numeric value)."""
    raw = (_addon.getSetting('page_size') or '').strip()
    if raw == '':
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default

    # settings.xml enum stores the selected index (0..4).
    if raw in {'0', '1', '2', '3', '4'}:
        return _PAGE_SIZE_CHOICES[value]

    # Legacy free-number setting.
    if value in _PAGE_SIZE_CHOICES:
        return value
    if value < 10:
        return default
    return min(value, 100)


def get_setting_bool(setting_id, default=False):
    value = _addon.getSetting(setting_id)
    if value in ('true', '1'):
        return True
    if value in ('false', '0', ''):
        return default
    return default


def log(message, level=None):
    if level is None:
        level = getattr(xbmc, 'LOGINFO', 1)
    if xbmc and hasattr(xbmc, 'log'):
        xbmc.log(f'[{ADDON_ID}] {message}', level)
        return
    try:
        _addon.log(str(message), level)
    except Exception:
        sys.stderr.write(f'[{ADDON_ID}] {message}\n')


def log_error(message):
    log(message, level=getattr(xbmc, 'LOGERROR', 4))


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


def get_response_header(headers, name, default=''):
    if not headers:
        return default

    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value or default

    return default


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


def is_dash_url(url):
    lower = (url or '').lower()
    path = lower.split('?', 1)[0]
    return path.endswith('.mpd') or '.mpd' in path


def inputstream_adaptive_status():
    """Return 'ready', 'disabled', or 'missing' for inputstream.adaptive.

    Prefer Kodi boolean conditions / JSON-RPC. ``Addon('inputstream.adaptive')``
    often raises ``Unknown addon id`` on Android/Google TV even when ISA is
    installed — that was wrongly showing the install dialog.
    """
    addon_id = 'inputstream.adaptive'

    if xbmc and hasattr(xbmc, 'getCondVisibility'):
        try:
            has_addon = xbmc.getCondVisibility(f'System.HasAddon({addon_id})')
            if has_addon:
                # AddonIsEnabled exists on Kodi 18+; if missing, assume enabled.
                try:
                    enabled = xbmc.getCondVisibility(f'System.AddonIsEnabled({addon_id})')
                except Exception:
                    enabled = True
                if not enabled:
                    return 'disabled'
                return 'ready'
            # HasAddon is false — double-check via JSON-RPC before declaring missing.
        except Exception as exc:
            log_error(f'InputStream Adaptive HasAddon check failed: {exc}')

    if xbmc and hasattr(xbmc, 'executeJSONRPC'):
        try:
            query = (
                '{"jsonrpc":"2.0","id":1,"method":"Addons.GetAddonDetails",'
                '"params":{"addonid":"%s","properties":["enabled","installed"]}}'
                % addon_id
            )
            raw = xbmc.executeJSONRPC(query)
            data = json.loads(raw) if raw else {}
            result = (data.get('result') or {}).get('addon') or {}
            if result.get('installed') or result.get('addonid') == addon_id:
                if result.get('enabled') is False:
                    return 'disabled'
                return 'ready'
            # explicit error from JSON-RPC → likely not installed
            if data.get('error'):
                err = str(data.get('error'))
                if 'invalid' in err.lower() or 'not found' in err.lower() or '-32602' in err:
                    return 'missing'
        except Exception as exc:
            log_error(f'InputStream Adaptive JSON-RPC check failed: {exc}')

    # Last resort: Addon() — unreliable on some Android builds (raises Unknown
    # addon id even when ISA is installed). Prefer playing over blocking.
    try:
        Addon(addon_id)
        return 'ready'
    except Exception as exc:
        log_error(f'InputStream Adaptive Addon() check failed: {exc}')
        return 'ready'


def playback_referer(referer, stream_url=None):
    stream_lower = (stream_url or '').lower()
    if 'vkcdn' in stream_lower or 'vkspeed.com' in stream_lower:
        return 'https://vkspeed.com/'
    if 'b-cdn.net' in stream_lower or 'tamildhool' in stream_lower:
        return 'https://www.tamildhool.tech/'
    referer = (referer or BASE_URL).strip()
    lower = referer.lower()
    if 'vimeocdn.com' in lower:
        return 'https://player.vimeo.com/'
    if 'tamildhool' in lower or 'b-cdn.net' in lower:
        return 'https://www.tamildhool.tech/'
    return referer or BASE_URL


def _use_woodviolet_headers(referer=None, stream_url=None):
    referer_lower = (referer or '').lower()
    stream_lower = (stream_url or '').lower()
    if 'woodviolet' in referer_lower or 'woodviolet' in stream_lower:
        return True
    return '.click/stream/' in stream_lower or (
        '/stream/variant/' in stream_lower and stream_lower.endswith('.m3u8')
    )


def build_stream_headers(referer=None, cookies=None, stream_url=None):
    referer = playback_referer(referer, stream_url=stream_url)
    use_woodviolet = _use_woodviolet_headers(referer, stream_url)
    stream_lower = (stream_url or '').lower()
    user_agent = WOODVIOLET_USER_AGENT if use_woodviolet else USER_AGENT
    parts = [
        f'User-Agent={encode_header_value(user_agent)}',
        f'Referer={encode_header_value(referer)}',
    ]
    if use_woodviolet:
        parts.extend([
            'Origin=https%3A%2F%2Fwoodviolet.xyz',
            'Accept-Language=en-US%2Cen%3Bq%3D0.9',
        ])
    elif 'b-cdn.net' in stream_lower or 'tamildhool' in (referer or '').lower():
        # BunnyCDN rejects playlist/key/segment requests without these.
        parts.append('Origin=' + encode_header_value('https://www.tamildhool.tech'))
        parts.append('Accept=' + encode_header_value('*/*'))
    if cookies:
        parts.append(f'Cookie={encode_header_value(cookies)}')
    return '&'.join(parts)


def prefer_media_playlist(stream_url, referer=None, timeout=8):
    """If stream_url is an HLS master, return the first media playlist URL."""
    if not stream_url or not is_hls_url(stream_url):
        return stream_url
    if '/480p/' in stream_url or '/720p/' in stream_url or '/360p/' in stream_url:
        return stream_url

    headers = {
        'User-Agent': USER_AGENT,
        'Accept': '*/*',
        'Referer': playback_referer(referer),
    }
    if 'b-cdn.net' in stream_url.lower():
        headers['Origin'] = 'https://www.tamildhool.tech'
    try:
        body = _http_get_bytes(stream_url, headers, timeout=timeout).decode('utf-8', 'replace')
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return stream_url

    if '#EXT-X-STREAM-INF' not in body:
        return stream_url

    base = stream_url.rsplit('/', 1)[0] + '/'
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        child = line if line.startswith('http') else urllib.parse.urljoin(base, line)
        if is_hls_url(child) or child.endswith('.m3u8'):
            return child
    return stream_url


def _http_get_bytes(url, headers, timeout=12, retries=3):
    context = None
    try:
        import ssl
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    except Exception:
        context = None

    last_exc = None
    for attempt in range(max(1, int(retries))):
        request = urllib.request.Request(url, headers=headers)
        try:
            try:
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return response.read()
            except TypeError:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return response.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            last_exc = exc
            code = getattr(exc, 'code', None)
            if attempt + 1 < retries and (code in (403, 429, 500, 502, 503) or code is None):
                try:
                    import time
                    time.sleep(0.4 * (attempt + 1))
                except Exception:
                    pass
                continue
            raise
    raise last_exc


def _profile_paths():
    """Return (play_path, filesystem_dir) for the addon profile.

    play_path prefers special:// so ListItem works on Android/Google TV;
    filesystem_dir is where we write bunny_play.m3u8.
    """
    try:
        import xbmcvfs
        special = _addon.getAddonInfo('profile')
        if special and not xbmcvfs.exists(special):
            xbmcvfs.mkdirs(special)
        if special:
            try:
                fs_dir = xbmcvfs.translatePath(special)
            except Exception:
                fs_dir = special
            return special.rstrip('/').rstrip('\\'), fs_dir
    except Exception:
        pass
    import tempfile
    tmp = tempfile.gettempdir()
    return tmp, tmp


def _profile_dir():
    """Writable addon profile filesystem path (creates the folder when needed)."""
    _play, fs_dir = _profile_paths()
    return fs_dir


def _force_mpegts_url(url):
    """Bunny serves MPEG-TS as .dts; ISA/FFmpeg may reject or misread that extension."""
    if not url or '|' in url:
        return url
    path = url.split('#', 1)[0].split('?', 1)[0]
    if not path.lower().endswith('.dts'):
        return url
    if '?.ts' in url or '&.ts' in url or url.endswith('#.ts'):
        return url
    return url + ('&.ts' if '?' in url else '?.ts')


def _file_uri(path):
    """Absolute filesystem path as a file:// URI for HLS EXT-X-KEY."""
    if not path:
        return path
    normalized = os.path.abspath(path).replace('\\', '/')
    if not normalized.startswith('/'):
        normalized = '/' + normalized
    return 'file://' + urllib.parse.quote(normalized, safe='/:')



def prepare_bunny_playback_url(stream_url, referer=None, timeout=12):
    """Prepare BunnyCDN playback via a localhost HLS proxy.

    Local file playlists are unreliable on Google TV. The proxy serves:
      - playlist with .ts segment URLs
      - AES key from memory (no remote key Referer issues)
      - segments fetched server-side with tamildhool Referer
    """
    if not stream_url or 'b-cdn.net' not in stream_url.lower():
        return stream_url

    referer = 'https://www.tamildhool.tech/'
    media_url = prefer_media_playlist(stream_url, referer=referer, timeout=timeout)
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': '*/*',
        'Referer': referer,
        'Origin': 'https://www.tamildhool.tech',
    }
    try:
        playlist = _http_get_bytes(media_url, headers, timeout=timeout).decode('utf-8', 'replace')
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        log_error(f'Bunny playlist fetch failed: {exc}')
        return media_url

    base = media_url.rsplit('/', 1)[0] + '/'
    parsed = urllib.parse.urlparse(media_url)
    host_base = f'{parsed.scheme}://{parsed.netloc}' if parsed.scheme and parsed.netloc else ''

    key_bytes = b''
    segments = []
    extinf = []
    target_duration = 4
    pending_extinf = '4.000000'

    for line in playlist.splitlines():
        stripped = line.strip()
        if stripped.startswith('#EXT-X-TARGETDURATION:'):
            try:
                target_duration = int(float(stripped.split(':', 1)[1].strip()))
            except (TypeError, ValueError):
                pass
            continue
        if stripped.startswith('#EXTINF:'):
            pending_extinf = stripped.split(':', 1)[1].rstrip(',').strip() or '4.000000'
            continue
        if stripped.startswith('#EXT-X-KEY:'):
            match = re.search(r'URI="([^"]+)"', stripped)
            if not match:
                continue
            key_src = match.group(1)
            if key_src.startswith('data:'):
                continue
            if key_src.startswith('http'):
                key_url = key_src
            elif key_src.startswith('/'):
                key_url = host_base + key_src
            else:
                key_url = urllib.parse.urljoin(base, key_src)
            try:
                key_bytes = _http_get_bytes(key_url, headers, timeout=timeout)
                log(f'Bunny AES key fetched for proxy ({len(key_bytes)} bytes)')
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
                log_error(f'Bunny AES key fetch failed: {exc}')
            continue
        if stripped and not stripped.startswith('#'):
            seg = stripped if stripped.startswith('http') else urllib.parse.urljoin(base, stripped)
            segments.append(seg)
            extinf.append(pending_extinf)
            pending_extinf = '4.000000'

    if not segments or not key_bytes:
        log_error('Bunny proxy prepare incomplete; falling back to remote media URL')
        return media_url

    try:
        from bunny_proxy import register_bunny_session
        proxy_url = register_bunny_session(
            key_bytes,
            segments,
            headers=headers,
            target_duration=target_duration,
            extinf=extinf,
        )
    except Exception as exc:
        log_error(f'Bunny proxy register failed: {exc}')
        return media_url

    if not proxy_url:
        return media_url

    log(f'Bunny proxy playlist ready: {proxy_url} ({len(segments)} segments)')
    return proxy_url


def is_local_bunny_playlist(path):
    """True when path is our rewritten local Bunny playlist (not a remote URL)."""
    if not path:
        return False
    lower = path.lower().replace('\\', '/')
    if lower.startswith('http://') or lower.startswith('https://'):
        return False
    return lower.endswith('bunny_play.m3u8') or lower.endswith('bunny_play.m3u')


def apply_stream_properties(
    list_item,
    stream_url,
    referer=None,
    cookies=None,
    license_type=None,
    license_key=None,
    is_live=False,
):
    """Configure ListItem for playback. For ISA, never put |headers on the path."""
    is_bunny = is_hls_url(stream_url) and 'b-cdn.net' in (stream_url or '').lower()
    referer = playback_referer(referer, stream_url=stream_url)
    if is_bunny:
        stream_url = prepare_bunny_playback_url(stream_url, referer=referer)

    try:
        from bunny_proxy import is_bunny_proxy_url
    except Exception:
        def is_bunny_proxy_url(_url):
            return False

    # Localhost proxy: default player (key + .ts segments; CDN headers applied by proxy).
    if is_bunny_proxy_url(stream_url):
        list_item.setPath(stream_url)
        list_item.setMimeType('application/vnd.apple.mpegurl')
        try:
            list_item.setContentLookup(False)
        except Exception:
            pass
        return

    headers = build_stream_headers(
        referer,
        cookies=cookies,
        stream_url=stream_url if not is_bunny else 'https://vz.b-cdn.net/x',
    )

    local_bunny = is_local_bunny_playlist(stream_url)
    use_hls = local_bunny or is_hls_url(stream_url)
    use_dash = (not use_hls) and is_dash_url(stream_url)
    if use_hls or use_dash:
        list_item.setPath(stream_url)
        list_item.setMimeType(
            'application/vnd.apple.mpegurl' if use_hls else 'application/dash+xml'
        )
        try:
            list_item.setContentLookup(False)
        except Exception:
            pass
        list_item.setProperty('inputstream', 'inputstream.adaptive')
        list_item.setProperty('inputstreamaddon', 'inputstream.adaptive')
        list_item.setProperty(
            'inputstream.adaptive.manifest_type',
            'hls' if use_hls else 'mpd',
        )
        list_item.setProperty('inputstream.adaptive.manifest_headers', headers)
        list_item.setProperty('inputstream.adaptive.stream_headers', headers)
        list_item.setProperty('inputstream.adaptive.common_headers', headers)
        list_item.setProperty(
            'inputstream.adaptive.is_realtime_stream',
            'true' if is_live else 'false',
        )
        if license_type and license_key:
            list_item.setProperty('inputstream.adaptive.license_type', license_type)
            list_item.setProperty('inputstream.adaptive.license_key', license_key)
        elif is_bunny and (stream_url or '').startswith('http'):
            list_item.setProperty('inputstream.adaptive.license_key', '|' + headers)
        return

    playback_url = f'{stream_url}|{headers}' if headers else stream_url
    list_item.setPath(playback_url)
    try:
        if stream_url.lower().split('?', 1)[0].endswith('.mp4'):
            list_item.setMimeType('video/mp4')
            return
    except Exception as exc:
        log_error(f'Failed to set stream properties: {exc}')