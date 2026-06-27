# -*- coding: utf-8 -*-

import html as html_module
import http.cookiejar
import base64
import binascii
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from constants import BASE_URL, USER_AGENT
from scraper import extract_maskr_urls
from utils import log, log_error


STREAM_PATTERNS = (
    re.compile(r'["\']([^"\']+\.mp4(?:\?[^"\']*)?)["\']', re.I),
    re.compile(r'["\']([^"\']+\.m3u8(?:\?[^"\']*)?)["\']', re.I),
    re.compile(r'file\s*:\s*["\']([^"\']+)["\']', re.I),
    re.compile(r'source\s*:\s*["\']([^"\']+)["\']', re.I),
    re.compile(r'<source[^>]+src=["\']([^"\']+)["\']', re.I),
    re.compile(r'<video[^>]+src=["\']([^"\']+)["\']', re.I),
)

IFRAME_PATTERN = re.compile(r'<iframe[^>]+src=["\']([^"\']+)["\']', re.I)
META_REFRESH_CONTENT_PATTERN = re.compile(
    r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=([\'"])(.*?)\1',
    re.I | re.S,
)
JS_REDIRECT_PATTERN = re.compile(
    r"(?:redirectUrl|location(?:\.href)?)\s*=\s*['\"]([^'\"]+)['\"]",
    re.I,
)

SKIP_DOMAINS = (
    'google.com',
    'google.co.',
    'gstatic.com',
    'doubleclick.net',
    'googlesyndication.com',
    'openstream.co',
)

PRIORITY_EMBED_DOMAINS = (
    'woodviolet.xyz',
)

EMBED_PLAYER_DOMAINS = (
    'player.vimeo.com',
    'vimeo.com',
    'youtube.com',
    'youtube-nocookie.com',
    'dailymotion.com',
    'dai.ly',
)


def _clean_url(url):
    if not url:
        return ''
    url = url.replace('\\u0026', '&').replace('\\/', '/')
    return html_module.unescape(url)


def _normalize_url(url, base_url):
    if not url:
        return ''
    url = _clean_url(url.strip())
    if url.startswith('//'):
        return 'https:' + url
    if url.startswith('/'):
        parsed = urllib.parse.urlparse(base_url)
        return f'{parsed.scheme}://{parsed.netloc}{url}'
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9+\-.]*:', url):
        return urllib.parse.urljoin(base_url, url)
    return url


def _domain(url):
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except (ValueError, AttributeError):
        return ''


def _should_skip(url):
    domain = _domain(url)
    return any(token in domain for token in SKIP_DOMAINS)


def _unwrap_google_url(url):
    if 'google.' not in url or '/url' not in url:
        return url

    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    target = params.get('url', [''])[0]
    if target:
        return _normalize_url(target, url)
    return url


def _is_priority_embed(url):
    domain = _domain(url)
    return any(token in domain for token in PRIORITY_EMBED_DOMAINS)


def _is_embed_player(url):
    domain = _domain(url)
    return any(token in domain for token in EMBED_PLAYER_DOMAINS)


def _is_probable_stream(url):
    lower = url.lower()
    if any(token in lower for token in ('.m3u8', '.mp4', '.mpd', '/manifest', '/playlist')):
        return True
    if 'google.com/url' in lower:
        return False
    return False


def _extract_meta_refresh_urls(html, base_url):
    urls = []
    seen = set()

    for match in META_REFRESH_CONTENT_PATTERN.finditer(html or ''):
        content = html_module.unescape(match.group(2))
        url_match = re.search(r'url=(.+)', content, re.I)
        if not url_match:
            continue
        target = _normalize_url(url_match.group(1).strip().strip("'\""), base_url)
        if target and target not in seen:
            seen.add(target)
            urls.append(target)

    return urls


def _extract_candidates(html, base_url):
    candidates = []
    seen = set()

    for pattern in STREAM_PATTERNS:
        for match in pattern.findall(html or ''):
            url = _normalize_url(match, base_url)
            if url and url not in seen:
                seen.add(url)
                candidates.append(url)

    for match in IFRAME_PATTERN.findall(html or ''):
        url = _normalize_url(match, base_url)
        if url and url not in seen and not _should_skip(url):
            seen.add(url)
            candidates.append(url)

    return candidates


def _extract_vimeo_progressive_urls(html):
    urls = []
    seen = set()
    for match in re.finditer(r'"url"\s*:\s*"(https://[^"\\]+)"', html or ''):
        url = _clean_url(match.group(1).replace('\\/', '/'))
        if '.mp4' not in url.lower() or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _extract_woodviolet_stream(html, base_url):
    if 'woodviolet.xyz' not in (base_url or '').lower() and 'woodviolet.xyz' not in (html or '').lower():
        return ''

    decoded_player = _decode_juicycodes_payload(html)
    if decoded_player:
        url = _stream_from_woodviolet_config(decoded_player)
        if url:
            log(f'Found woodviolet decoded stream: {url}')
            return url

    for pattern in (
        re.compile(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', re.I),
        re.compile(r'["\'](https?://[^"\']+\.mp4[^"\']*)["\']', re.I),
        re.compile(r'\"file\"\s*:\s*\"(https?://[^\"\\]+)\"', re.I),
    ):
        for match in pattern.findall(html or ''):
            url = _clean_url(match.replace('\\/', '/'))
            if url:
                log(f'Found woodviolet stream: {url}')
                return url

    return ''


def _stream_from_woodviolet_config(decoded_player):
    config_match = re.search(r'var\s+config\s*=\s*(\{.*?\});\s*jwplayer', decoded_player, re.S)
    if config_match:
        try:
            config = json.loads(config_match.group(1))
            sources = config.get('sources') or {}
            url = sources.get('file') or ''
            if url:
                return _clean_url(url)
        except (TypeError, ValueError) as exc:
            log_error(f'Could not parse woodviolet config JSON: {exc}')

    source_match = re.search(r'"sources"\s*:\s*\{.*?"file"\s*:\s*"([^"]+)"', decoded_player, re.I | re.S)
    if source_match:
        return _clean_url(source_match.group(1))

    for pattern in (
        re.compile(r'"file"\s*:\s*"([^"]+\.m3u8[^"]*)"', re.I),
        re.compile(r'"file"\s*:\s*\'([^\']+\.m3u8[^\']*)\'', re.I),
        re.compile(r'"file"\s*:\s*"([^"]+\.mp4[^"]*)"', re.I),
        re.compile(r'"file"\s*:\s*\'([^\']+\.mp4[^\']*)\'', re.I),
    ):
        match = pattern.search(decoded_player)
        if match:
            return _clean_url(match.group(1))

    return ''


def _decode_juicycodes_payload(html):
    match = re.search(r'_juicycodes\((.*?)\);</script>', html or '', re.S)
    if not match:
        return ''

    first_arg = match.group(1).rsplit(',', 1)[0]
    encoded = ''.join(re.findall(r'"([^"]*)"', first_arg))
    if len(encoded) <= 3:
        return ''

    try:
        salt = int(''.join(str(ord(char) - 100) for char in encoded[-3:]))
        payload = encoded[:-3]
        padding = '=' * ((4 - len(payload) % 4) % 4)
        decoded = base64.b64decode(
            (payload + padding).replace('_', '+').replace('-', '/')
        ).decode('utf-8', 'replace')
    except (ValueError, TypeError, binascii.Error) as exc:
        log_error(f'Could not decode woodviolet payload: {exc}')
        return ''

    symbol_map = ['`', '%', '-', '+', '*', '$', '!', '_', '^', '=']
    try:
        digits = ''.join(str(symbol_map.index(char)) for char in decoded)
        return ''.join(
            chr((int(digits[index:index + 4]) % 1000) - salt)
            for index in range(0, len(digits) - 3, 4)
        )
    except (ValueError, TypeError) as exc:
        log_error(f'Could not unpack woodviolet payload: {exc}')
        return ''


def _best_stream_from_page(html, base_url):
    progressive_urls = _extract_vimeo_progressive_urls(html)
    if progressive_urls:
        stream_url = progressive_urls[-1]
        log(f'Found Vimeo progressive MP4: {stream_url}')
        return stream_url, 'https://player.vimeo.com/'

    woodviolet_stream = _extract_woodviolet_stream(html, base_url)
    if woodviolet_stream:
        return woodviolet_stream, base_url

    mp4_candidates = []
    m3u8_candidates = []
    for candidate in _extract_candidates(html, base_url):
        if not _is_probable_stream(candidate):
            continue
        if candidate.lower().split('?', 1)[0].endswith('.mp4'):
            mp4_candidates.append(candidate)
        else:
            m3u8_candidates.append(candidate)

    if mp4_candidates:
        stream_url = _clean_url(mp4_candidates[0])
        referer = 'https://player.vimeo.com/' if 'vimeocdn.com' in stream_url.lower() else base_url
        log(f'Found MP4 stream: {stream_url}')
        return stream_url, referer

    if m3u8_candidates:
        stream_url = _clean_url(m3u8_candidates[0])
        referer = 'https://player.vimeo.com/' if 'vimeocdn.com' in stream_url.lower() else base_url
        log(f'Found HLS stream: {stream_url}')
        return stream_url, referer

    return '', ''


def _ssl_context(verify_ssl=True):
    ctx = ssl.create_default_context()
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _build_opener(cookie_jar, verify_ssl=True):
    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    ctx = _ssl_context(verify_ssl)
    handlers = [
        urllib.request.HTTPSHandler(context=ctx),
        urllib.request.HTTPCookieProcessor(cookie_jar),
        NoRedirectHandler(),
    ]
    return urllib.request.build_opener(*handlers)


def _response_status(response):
    return getattr(response, 'status', response.getcode())


def _fetch(url, referer=BASE_URL, timeout=20, opener=None):
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': '*/*',
        'Referer': referer,
    }
    request = urllib.request.Request(url, headers=headers)
    opener = opener or urllib.request.build_opener()
    try:
        with opener.open(request, timeout=timeout) as response:
            final_url = response.geturl()
            html = response.read().decode('utf-8', 'replace')
            return _response_status(response), html, final_url, ''
    except urllib.error.HTTPError as exc:
        location = exc.headers.get('Location', '')
        body = ''
        if exc.fp is not None:
            body = exc.read().decode('utf-8', 'replace')
        return exc.code, body, url, location


def _fetch_with_ssl_fallback(url, referer, opener, cookie_jar):
    try:
        return _fetch(url, referer=referer, opener=opener), opener
    except urllib.error.URLError as exc:
        if 'CERTIFICATE_VERIFY_FAILED' not in str(exc):
            raise
        log('SSL verify failed, retrying without certificate check')
        opener = _build_opener(cookie_jar, verify_ssl=False)
        return _fetch(url, referer=referer, opener=opener), opener


def _follow_redirect_chain(start_url, referer=BASE_URL, max_hops=10):
    cookie_jar = http.cookiejar.CookieJar()
    opener = _build_opener(cookie_jar, verify_ssl=False)
    visited = set()
    queue = [(start_url, referer)]

    for _hop in range(max_hops):
        if not queue:
            break

        current_url, current_referer = queue.pop(0)
        current_url = _unwrap_google_url(current_url)
        if not current_url or current_url in visited:
            continue
        visited.add(current_url)

        try:
            (status, html, final_url, location), opener = _fetch_with_ssl_fallback(
                current_url,
                current_referer,
                opener,
                cookie_jar,
            )
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            log_error(f'Failed to fetch {current_url}: {exc}')
            continue

        stream_url, stream_referer = _best_stream_from_page(html, final_url)
        if stream_url:
            log(f'Resolved stream: {stream_url}')
            return stream_url, stream_referer

        redirect_targets = []
        other_targets = []

        redirect_targets.extend(_extract_meta_refresh_urls(html, final_url))

        if status in (301, 302, 303, 307, 308) and location:
            redirect_targets.append(_normalize_url(location, final_url))

        for candidate in _extract_candidates(html, final_url):
            if not _is_probable_stream(candidate):
                if _is_embed_player(candidate) or _is_priority_embed(candidate):
                    redirect_targets.append(candidate)
                else:
                    other_targets.append(candidate)

        for match in JS_REDIRECT_PATTERN.findall(html or ''):
            other_targets.append(_normalize_url(match, final_url))

        seen_targets = set()
        for candidate in redirect_targets + other_targets:
            candidate = _unwrap_google_url(candidate)
            if not candidate or candidate in visited or candidate in seen_targets:
                continue
            seen_targets.add(candidate)
            if _should_skip(candidate):
                continue
            queue.append((candidate, final_url))

    return '', ''


def _maskr_urls_from_episode_page(episode_link):
    if not episode_link:
        return []

    cookie_jar = http.cookiejar.CookieJar()
    opener = _build_opener(cookie_jar, verify_ssl=False)
    try:
        (status, html, _final_url, _location), _opener = _fetch_with_ssl_fallback(
            episode_link,
            BASE_URL,
            opener,
            cookie_jar,
        )
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        log_error(f'Failed to fetch episode page {episode_link}: {exc}')
        return []

    if status != 200 or not html:
        return []

    return extract_maskr_urls(html)


def resolve_stream(maskr_url, referer=BASE_URL):
    if not maskr_url:
        return '', ''

    log(f'Resolving stream from {maskr_url}')
    return _follow_redirect_chain(maskr_url, referer=referer)


def resolve_streams(maskr_urls, referer=BASE_URL):
    seen = set()
    for maskr_url in maskr_urls or []:
        if not maskr_url or maskr_url in seen:
            continue
        seen.add(maskr_url)

        stream_url, stream_referer = resolve_stream(maskr_url, referer=referer)
        if stream_url:
            return stream_url, stream_referer

    return '', ''


def resolve_episode_stream(content_html, episode_link=''):
    referer = episode_link or BASE_URL
    maskr_urls = extract_maskr_urls(content_html)
    seen = set(maskr_urls)

    if maskr_urls:
        log(f'Trying {len(maskr_urls)} play link(s) from API content')
        stream_url, stream_referer = resolve_streams(maskr_urls, referer=referer)
        if stream_url:
            return stream_url, stream_referer

    page_urls = _maskr_urls_from_episode_page(episode_link)
    extra_urls = [url for url in page_urls if url not in seen]
    if extra_urls:
        log(f'Trying {len(extra_urls)} play link(s) from episode page')
        stream_url, stream_referer = resolve_streams(extra_urls, referer=referer)
        if stream_url:
            return stream_url, stream_referer

    if not maskr_urls and not page_urls:
        log('No maskr URLs found in episode content or page')
    else:
        log_error('Could not resolve stream from any play link')

    return '', ''
