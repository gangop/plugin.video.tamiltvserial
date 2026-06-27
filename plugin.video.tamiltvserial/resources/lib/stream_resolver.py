# -*- coding: utf-8 -*-

import http.cookiejar
import re
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
META_REFRESH_PATTERN = re.compile(
    r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^"\']*url=([^"\']+)["\']',
    re.I,
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
    return url.replace('\\u0026', '&').replace('\\/', '/')


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


def _best_stream_from_page(html, base_url):
    progressive_urls = _extract_vimeo_progressive_urls(html)
    if progressive_urls:
        stream_url = progressive_urls[-1]
        log(f'Found Vimeo progressive MP4: {stream_url}')
        return stream_url, 'https://player.vimeo.com/'

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


def _build_opener(cookie_jar):
    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar),
        NoRedirectHandler(),
    )


def _fetch(url, referer=BASE_URL, timeout=45, opener=None):
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
            return response.status, html, final_url, ''
    except urllib.error.HTTPError as exc:
        location = exc.headers.get('Location', '')
        body = ''
        if exc.fp is not None:
            body = exc.read().decode('utf-8', 'replace')
        return exc.code, body, url, location


def _follow_redirect_chain(start_url, referer=BASE_URL, max_hops=15):
    cookie_jar = http.cookiejar.CookieJar()
    opener = _build_opener(cookie_jar)
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
            status, html, final_url, location = _fetch(
                current_url,
                referer=current_referer,
                opener=opener,
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

        if status in (301, 302, 303, 307, 308) and location:
            redirect_targets.append(_normalize_url(location, final_url))

        for candidate in _extract_candidates(html, final_url):
            if not _is_probable_stream(candidate):
                if _is_embed_player(candidate):
                    redirect_targets.append(candidate)
                else:
                    other_targets.append(candidate)

        for pattern in (META_REFRESH_PATTERN, JS_REDIRECT_PATTERN):
            for match in pattern.findall(html or ''):
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
    maskr_urls = extract_maskr_urls(content_html)
    if not maskr_urls:
        log('No maskr URLs found in episode content')
        return '', ''

    referer = episode_link or BASE_URL
    log(f'Trying {len(maskr_urls)} play link(s)')
    return resolve_streams(maskr_urls, referer=referer)
