# -*- coding: utf-8 -*-
"""Live fallback for tamildhol.my (WordPress + vkspeed embeds).

Used after TamilTvSerial and TamilDhool when an episode is missing or
unplayable. Listing uses the public WP REST API; playback unpacks the
vkspeed JWPlayer embed to a direct MP4.
"""

import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from constants import WOODVIOLET_USER_AGENT
from tamildhool import (
    extract_bunny_playlists,
    extract_dailymotion_ids,
    parse_episode_meta,
    resolve_dailymotion_stream,
    _channel_entry,
    _path_slugs,
    _show_path_aliases,
    _slugify,
)
from utils import log, log_error, strip_html


TAMILDHOL_BASE = 'https://tamildhol.my'
WP_POSTS_URL = TAMILDHOL_BASE + '/wp-json/wp/v2/posts'
VKSPEED_REFERER = 'https://vkspeed.com/'
SEARCH_CACHE_TTL_SECONDS = 900
TITLE_DATE_PATTERN = re.compile(r'(\d{1,2})-(\d{1,2})-(\d{4})')
VKSPEED_EMBED_PATTERN = re.compile(
    r'(?:https?:)?//(?:www\.)?vkspeed\.com/embed-([A-Za-z0-9]+)\.html',
    re.I,
)
EMBED_ATTR_PATTERN = re.compile(
    r'(?:src|data-src|data-litespeed-src)=["\']([^"\']+)["\']',
    re.I,
)
PACKED_JS_PATTERN = re.compile(
    r"eval\(function\(p,a,c,k,e,d\)\{.*?return p\}"
    r"\('((?:\\'|[^'])*)',(\d+),(\d+),'((?:\\'|[^'])*)'\.split\('\|'\)",
    re.S,
)
LABELED_FILE_PATTERN = re.compile(
    r'file\s*:\s*["\'](https?://[^"\']+\.(?:mp4|m3u8)[^"\']*)["\']'
    r'\s*,\s*label\s*:\s*["\']([^"\']+)["\']',
    re.I,
)
BARE_FILE_PATTERN = re.compile(
    r'file\s*:\s*["\'](https?://[^"\']+\.(?:mp4|m3u8)[^"\']*)["\']',
    re.I,
)
KIND_SUFFIXES = (
    'sun-tv-serial',
    'vijay-tv-serial',
    'zee-tamil-serial',
    'sun-tv-show',
    'vijay-tv-show',
    'zee-tamil-show',
)

_search_cache = {}


def _ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _headers(referer=TAMILDHOL_BASE + '/'):
    return {
        'User-Agent': WOODVIOLET_USER_AGENT,
        'Accept': 'text/html,application/json,application/xhtml+xml,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': referer,
    }


def _fetch_bytes(url, referer=TAMILDHOL_BASE + '/', timeout=15):
    request = urllib.request.Request(url, headers=_headers(referer))
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_ssl_context())
    )
    with opener.open(request, timeout=timeout) as response:
        return response.geturl(), response.read()


def _fetch_text(url, referer=TAMILDHOL_BASE + '/', timeout=15):
    final_url, payload = _fetch_bytes(url, referer=referer, timeout=timeout)
    return final_url, payload.decode('utf-8', 'replace')


def _fetch_json(url, timeout=15):
    try:
        _final_url, payload = _fetch_bytes(url, timeout=timeout)
        data = json.loads(payload.decode('utf-8', 'replace'))
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        ValueError,
    ) as exc:
        log_error(f'tamildhol.my JSON fetch failed for {url}: {exc}')
        return None
    return data


def _normalize_date(day, month, year):
    return f'{int(day):02d}-{int(month):02d}-{year}'


def _date_from_text(value):
    match = TITLE_DATE_PATTERN.search(value or '')
    if not match:
        return ''
    return _normalize_date(match.group(1), match.group(2), match.group(3))


def _kind_suffixes_for(title):
    show, _date, channel, _episode_number = parse_episode_meta(title)
    _channel_slug, kind_slug = _channel_entry(channel, title)
    suffixes = []
    if kind_slug:
        suffixes.append(kind_slug)
        alt = (
            kind_slug.replace('-serial', '-show')
            if kind_slug.endswith('-serial')
            else kind_slug.replace('-show', '-serial')
        )
        if alt != kind_slug:
            suffixes.append(alt)
    for suffix in KIND_SUFFIXES:
        if suffix not in suffixes:
            suffixes.append(suffix)
    return suffixes or list(KIND_SUFFIXES)


def _episode_slug_bases(title):
    show, _date, _channel, _episode_number = parse_episode_meta(title)
    if not show:
        return []
    show_slug = _slugify(show)
    _folder_slug, episode_bases = _path_slugs(show_slug)
    bases = []
    for value in (show_slug, *episode_bases):
        if value and value not in bases:
            bases.append(value)
    return bases


def _show_slug_set(name=None, folder=None, title=''):
    slugs = set()
    for value in (name, folder, title):
        slug = _slugify(value) if value else ''
        if slug:
            slugs.add(slug)
    aliases = _show_path_aliases()
    extra = set()
    for slug in list(slugs):
        extra.update(aliases.get(slug) or ())
        for key, values in aliases.items():
            if slug == key or slug in values:
                extra.add(key)
                extra.update(values)
    slugs.update(extra)
    return {item for item in slugs if item}


def build_episode_urls(title):
    """Build likely tamildhol.my permalinks for this show/date/channel."""
    show, date, _channel, _episode_number = parse_episode_meta(title)
    if not show or not date:
        return []

    urls = []
    seen = set()
    for base in _episode_slug_bases(title)[:3]:
        for kind in _kind_suffixes_for(title)[:2]:
            url = f'{TAMILDHOL_BASE}/{base}-{date}-{kind}/'
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def _unpack_packed_js(html):
    decoded_parts = []
    for payload, radix, count, dictionary in PACKED_JS_PATTERN.findall(html or ''):
        try:
            base = int(radix)
            words = dictionary.split('|')
        except (TypeError, ValueError):
            continue

        def replace_token(match):
            token = match.group(0)
            try:
                index = int(token, base)
            except ValueError:
                return token
            if 0 <= index < len(words) and words[index]:
                return words[index]
            return token

        decoded_parts.append(re.sub(r'\b[0-9a-zA-Z]+\b', replace_token, payload))
    return '\n'.join(decoded_parts)


def _quality_score(label, url):
    match = re.search(r'(\d+)\s*p', label or '', re.I)
    if match:
        return int(match.group(1))
    if (url or '').lower().endswith('.mp4'):
        return 1
    return 0


def _media_urls_from_player(html):
    decoded = _unpack_packed_js(html)
    text = (html or '') + '\n' + decoded
    ranked = []
    seen = set()
    for url, label in LABELED_FILE_PATTERN.findall(text):
        if url in seen:
            continue
        seen.add(url)
        ranked.append((_quality_score(label, url), url))
    for url in BARE_FILE_PATTERN.findall(text):
        if url in seen:
            continue
        seen.add(url)
        ranked.append((_quality_score('', url), url))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [url for _score, url in ranked]


def _extract_embed_urls(html):
    urls = []
    seen = set()

    def add(url):
        if not url:
            return
        url = url.strip()
        if url.startswith('//'):
            url = 'https:' + url
        if url in seen or url.startswith('about:'):
            return
        seen.add(url)
        urls.append(url)

    for match in VKSPEED_EMBED_PATTERN.findall(html or ''):
        add(f'https://vkspeed.com/embed-{match}.html')
    for raw in EMBED_ATTR_PATTERN.findall(html or ''):
        add(raw)
    return urls


def _prefer_vkspeed(urls):
    preferred = []
    rest = []
    for url in urls:
        if 'vkspeed.com' in (url or '').lower():
            preferred.append(url)
        elif any(token in (url or '').lower() for token in ('youtube.com', 'archive.org')):
            continue
        else:
            rest.append(url)
    return preferred + rest


def _resolve_vkspeed_embed(embed_url, page_url):
    log(f'tamildhol.my fetching vkspeed embed: {embed_url}')
    try:
        _final_url, html = _fetch_text(embed_url, referer=page_url or TAMILDHOL_BASE + '/')
    except urllib.error.HTTPError as exc:
        log_error(f'tamildhol.my vkspeed fetch failed: HTTP {exc.code}')
        return '', '', ''
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log_error(f'tamildhol.my vkspeed fetch failed: {exc}')
        return '', '', ''

    for stream_url in _media_urls_from_player(html):
        log(f'tamildhol.my vkspeed stream: {stream_url}')
        return stream_url, VKSPEED_REFERER, ''
    log('tamildhol.my vkspeed embed had no playable sources')
    return '', '', ''


def _resolve_from_html(html, page_url):
    bunny_urls = extract_bunny_playlists(html)
    if bunny_urls:
        return bunny_urls[0], page_url, ''

    for video_id in extract_dailymotion_ids(html):
        stream_url, referer = resolve_dailymotion_stream(video_id)
        if stream_url:
            return stream_url, referer or page_url, ''

    for embed_url in _prefer_vkspeed(_extract_embed_urls(html)):
        if 'vkspeed.com' in embed_url.lower():
            stream_url, referer, cookies = _resolve_vkspeed_embed(embed_url, page_url)
            if stream_url:
                return stream_url, referer, cookies
    return '', '', ''


def _wp_posts(params):
    query = urllib.parse.urlencode(params)
    data = _fetch_json(f'{WP_POSTS_URL}?{query}')
    return data if isinstance(data, list) else []


def _post_slug_prefix(slug, date):
    slug = (slug or '').strip('/').lower()
    marker = f'-{date}-'
    if date and marker in slug:
        return slug.split(marker, 1)[0]
    match = TITLE_DATE_PATTERN.search(slug)
    if match:
        return slug[:match.start()].strip('-')
    return slug


def _post_matches_show(post, slug_set):
    if not slug_set:
        return False
    slug = (post.get('slug') or '').lower()
    date = _date_from_text(slug) or _date_from_text(
        strip_html(((post.get('title') or {}).get('rendered')) or '')
    )
    prefix = _post_slug_prefix(slug, date)
    if prefix in slug_set:
        return True
    return any(
        prefix == candidate or prefix.startswith(candidate + '-')
        for candidate in slug_set
    )


def _wp_lookup_post(title):
    show, date, _channel, _episode_number = parse_episode_meta(title)
    if not show or not date:
        return None

    slug_set = _show_slug_set(name=show, title=title)
    fields = 'id,slug,link,title,content'
    posts = _wp_posts({
        'search': f'{show} {date}',
        '_fields': fields,
        'per_page': 8,
    })
    for post in posts:
        post_date = _date_from_text(post.get('slug') or '') or _date_from_text(
            strip_html(((post.get('title') or {}).get('rendered')) or '')
        )
        if post_date == date and _post_matches_show(post, slug_set):
            return post

    for base in _episode_slug_bases(title)[:2]:
        for kind in _kind_suffixes_for(title)[:2]:
            posts = _wp_posts({
                'slug': f'{base}-{date}-{kind}',
                '_fields': fields,
                'per_page': 1,
            })
            if posts:
                return posts[0]
    return None


def list_recent_episodes(name=None, folder=None, limit=12):
    """Return recent tamildhol.my episodes for a serial folder."""
    slug_set = _show_slug_set(name=name, folder=folder)
    if not slug_set:
        return []

    cache_key = f'{(name or "").strip().lower()}|{(folder or "").strip().lower()}'
    now = time.time()
    cached = _search_cache.get(cache_key)
    if cached and (now - cached[0]) < SEARCH_CACHE_TTL_SECONDS:
        return list(cached[1])[:limit]

    queries = []
    for value in (
        *sorted((item.replace('-', ' ') for item in slug_set), key=len, reverse=True),
        name,
        (folder or '').replace('-', ' '),
    ):
        text = re.sub(r'\s+', ' ', (value or '').strip())
        if text and text.lower() not in {item.lower() for item in queries}:
            queries.append(text)

    episodes = []
    seen_dates = set()
    for query in queries[:4]:
        posts = _wp_posts({
            'search': query,
            '_fields': 'id,slug,link,title',
            'per_page': 20,
            'orderby': 'date',
            'order': 'desc',
        })
        for post in posts:
            if not _post_matches_show(post, slug_set):
                continue
            slug = post.get('slug') or ''
            title = strip_html(((post.get('title') or {}).get('rendered')) or '')
            date = _date_from_text(slug) or _date_from_text(title)
            if not date or date in seen_dates:
                continue
            seen_dates.add(date)
            display = name or folder or title
            channel_label = 'Serial'
            lower_slug = slug.lower()
            if 'sun-tv' in lower_slug:
                channel_label = 'Sun TV Show' if 'show' in lower_slug else 'Sun TV Serial'
            elif 'vijay-tv' in lower_slug:
                channel_label = 'Vijay TV Show' if 'show' in lower_slug else 'Vijay TV Serial'
            elif 'zee-tamil' in lower_slug:
                channel_label = 'Zee Tamil Show' if 'show' in lower_slug else 'Zee Tamil Serial'
            episodes.append({
                'date': date,
                'title': f'{display} {date} | {channel_label}',
                'page': post.get('link') or f'{TAMILDHOL_BASE}/{slug}/',
            })
            if len(episodes) >= limit:
                break
        if len(episodes) >= limit:
            break

    _search_cache[cache_key] = (now, episodes)
    if episodes:
        log(f'tamildhol.my listed {len(episodes)} recent episode(s) for {name or folder!r}')
    return list(episodes)


def resolve_tamildhol_stream(title):
    """Resolve the exact episode from tamildhol.my."""
    show, date, channel, episode_number = parse_episode_meta(title)
    log(
        'tamildhol.my exact episode: '
        f'show={show!r} date={date} channel={channel} episode={episode_number}'
    )
    if not show or not date:
        return '', '', ''

    post = _wp_lookup_post(title)
    if post:
        page_url = post.get('link') or ''
        html = ((post.get('content') or {}).get('rendered')) or ''
        if html:
            stream_url, referer, cookies = _resolve_from_html(html, page_url)
            if stream_url:
                return stream_url, referer, cookies
        if page_url:
            try:
                _final_url, html = _fetch_text(page_url)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
                log_error(f'tamildhol.my page fetch failed for {page_url}: {exc}')
            else:
                stream_url, referer, cookies = _resolve_from_html(html, page_url)
                if stream_url:
                    return stream_url, referer, cookies

    for page_url in build_episode_urls(title):
        log(f'tamildhol.my fetching exact URL: {page_url}')
        try:
            final_url, html = _fetch_text(page_url)
        except urllib.error.HTTPError as exc:
            log_error(f'tamildhol.my fetch failed for {page_url}: HTTP {exc.code}')
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log_error(f'tamildhol.my fetch failed for {page_url}: {exc}')
            continue
        if not html:
            continue
        stream_url, referer, cookies = _resolve_from_html(html, final_url or page_url)
        if stream_url:
            return stream_url, referer, cookies

    log(f'tamildhol.my miss for {show} {date}')
    return '', '', ''
