# -*- coding: utf-8 -*-

import json
import re
import ssl
import urllib.error
import urllib.request

from constants import WOODVIOLET_USER_AGENT
from utils import log, log_error, strip_html


TAMILDHOOL_BASE = 'https://www.tamildhool.tech'
# Pin to the commit that published the current index (raw/main CDN can lag).
# Update INDEX_REF after running scripts/update_tamildhool_fallback.py and pushing.
INDEX_REF = '7320c325a67a8de4d30ad57e6d232305f04d5ec4'
FALLBACK_INDEX_URL = (
    f'https://raw.githubusercontent.com/gangop/plugin.video.tamiltvserial/{INDEX_REF}/'
    'fallback/tamildhool.json'
)
TITLE_DATE_PATTERN = re.compile(r'(\d{1,2})-(\d{1,2})-(\d{4})')
EPISODE_NUMBER_PATTERN = re.compile(r'Episode\s+(\d+)', re.I)
BUNNY_PATTERN = re.compile(
    r'https://(vz-[a-z0-9-]+\.b-cdn\.net)/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/',
    re.I,
)
DAILYMOTION_PATTERN = re.compile(
    r'(?:dai\.ly/|dailymotion\.com/(?:embed/)?video/)([A-Za-z0-9]+)',
    re.I,
)
TEAMSTODAY_PATTERN = re.compile(
    r'teamstoday\.com/\?video=([A-Za-z0-9]+)',
    re.I,
)
CHANNEL_SLUGS = (
    ('sun tv', 'sun-tv', 'sun-tv-serial'),
    ('vijay tv', 'vijay-tv', 'vijay-tv-serial'),
    ('zee tamil', 'zee-tamil', 'zee-tamil-serial'),
)

# TamilDhool sometimes uses a different episode-path slug than the show folder.
# folder slug -> extra episode-path slugs to try (folder slug is always tried first).
EPISODE_SLUG_ALIASES = {
    'pudhu-vasantham': ('puthu-vasantham',),
}

_index_cache = {'data': None}


def _slugify(value):
    value = re.sub(r'[^a-z0-9]+', '-', (value or '').lower()).strip('-')
    return re.sub(r'-{2,}', '-', value)


def _normalize_date(day, month, year):
    return f'{int(day):02d}-{int(month):02d}-{year}'


def parse_episode_meta(title):
    """Return (show, date DD-MM-YYYY, channel_name, episode_number)."""
    title = (title or '').strip()
    if not title:
        return '', '', '', None

    date_match = TITLE_DATE_PATTERN.search(title)
    date = ''
    if date_match:
        date = _normalize_date(date_match.group(1), date_match.group(2), date_match.group(3))

    episode_number = None
    episode_match = EPISODE_NUMBER_PATTERN.search(title)
    if episode_match:
        episode_number = int(episode_match.group(1))

    channel = ''
    lower = title.lower()
    for name, _channel_slug, _kind_slug in CHANNEL_SLUGS:
        if name in lower:
            channel = name
            break

    show = title
    if '|' in show:
        show = show.split('|', 1)[0]
    show = TITLE_DATE_PATTERN.sub('', show)
    show = re.sub(r'\s+', ' ', show).strip(' -|')
    return show, date, channel, episode_number


def _channel_entry(channel_name):
    for name, channel_slug, kind_slug in CHANNEL_SLUGS:
        if name == channel_name:
            return channel_slug, kind_slug
    return '', ''


def episode_index_key(title):
    show, date, channel, _episode_number = parse_episode_meta(title)
    channel_slug, _kind_slug = _channel_entry(channel)
    if not show or not date or not channel_slug:
        return ''
    return f'{channel_slug}/{_slugify(show)}/{date}'


def _episode_path_slugs(show_slug):
    slugs = [show_slug]
    for alias in EPISODE_SLUG_ALIASES.get(show_slug, ()):
        if alias and alias not in slugs:
            slugs.append(alias)
    return slugs


def build_episode_urls(title):
    """Build exact TamilDhool episode URLs for this show/date/channel."""
    show, date, channel, _episode_number = parse_episode_meta(title)
    if not show or not date or not channel:
        log(
            'TamilDhool: need show, date, and channel for exact match '
            f'(show={show!r}, date={date!r}, channel={channel!r})'
        )
        return []

    channel_slug, kind_slug = _channel_entry(channel)
    if not channel_slug:
        return []

    show_slug = _slugify(show)
    urls = []
    for episode_slug_base in _episode_path_slugs(show_slug):
        episode_slug = f'{episode_slug_base}-{date}-{kind_slug}'
        urls.append(
            f'{TAMILDHOOL_BASE}/{channel_slug}/{kind_slug}/{show_slug}/{episode_slug}/'
        )
    return urls



def _ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _is_challenge_page(html):
    lower = (html or '').lower()
    if '<title>just a moment...</title>' in lower:
        return True
    if 'just a moment' in lower and 'enable javascript and cookies to continue' in lower:
        return True
    return False


def _page_matches_episode(final_url, html, show, date, channel):
    show_slug = _slugify(show)
    channel_slug, kind_slug = _channel_entry(channel)
    if not show_slug or not date or not channel_slug:
        return False

    url_lower = (final_url or '').lower().rstrip('/') + '/'
    if f'/{channel_slug}/' not in url_lower or f'/{show_slug}/' not in url_lower:
        return False

    matched_path = False
    for episode_slug_base in _episode_path_slugs(show_slug):
        expected_tail = f'/{show_slug}/{episode_slug_base}-{date}-{kind_slug}/'
        alt_tail = f'/{show_slug}/{episode_slug_base}-{date}/'
        if expected_tail in url_lower or alt_tail in url_lower:
            matched_path = True
            break
    if not matched_path:
        return False

    title_match = re.search(r'<title[^>]*>(.*?)</title>', html or '', re.I | re.S)
    page_title = strip_html(title_match.group(1) if title_match else '')
    page_lower = page_title.lower()
    if show.lower() not in page_lower:
        return False
    if date not in page_title and date not in (html or '')[:4000]:
        return False
    if channel not in page_lower and channel_slug.replace('-', ' ') not in page_lower:
        return False
    return True


def _fetch_page(url, timeout=20):
    headers = {
        'User-Agent': WOODVIOLET_USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': TAMILDHOOL_BASE + '/',
    }
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ssl_context()))
    with opener.open(request, timeout=timeout) as response:
        html = response.read().decode('utf-8', 'replace')
        return response.geturl(), html


def _load_fallback_index():
    if _index_cache['data'] is not None:
        return _index_cache['data']

    request = urllib.request.Request(
        FALLBACK_INDEX_URL,
        headers={'User-Agent': WOODVIOLET_USER_AGENT, 'Accept': 'application/json'},
    )
    try:
        with urllib.request.urlopen(request, timeout=15, context=_ssl_context()) as response:
            data = json.loads(response.read().decode('utf-8', 'replace'))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
        log_error(f'TamilDhool fallback index unavailable: {exc}')
        data = {}

    if not isinstance(data, dict):
        data = {}
    _index_cache['data'] = data
    return data


def resolve_from_fallback_index(title):
    """Resolve exact episode from the published GitHub index (no Cloudflare)."""
    key = episode_index_key(title)
    if not key:
        return '', '', ''

    entry = _load_fallback_index().get(key) or {}
    stream_url = entry.get('stream') or ''
    if stream_url:
        referer = entry.get('referer') or entry.get('page') or (TAMILDHOOL_BASE + '/')
        log(f'TamilDhool index hit for {key}: {stream_url}')
        return stream_url, referer, ''

    video_id = entry.get('dailymotion') or ''
    if video_id:
        stream_url, referer = resolve_dailymotion_stream(video_id)
        if stream_url:
            log(f'TamilDhool index Dailymotion hit for {key}')
            return stream_url, referer, ''

    log(f'TamilDhool index miss for {key}')
    return '', '', ''


def extract_bunny_playlists(html):
    playlists = []
    seen = set()
    for host, video_id in BUNNY_PATTERN.findall(html or ''):
        playlist = f'https://{host}/{video_id}/playlist.m3u8'
        if playlist not in seen:
            seen.add(playlist)
            playlists.append(playlist)
    return playlists


def extract_dailymotion_ids(html):
    ids = []
    seen = set()
    for match in DAILYMOTION_PATTERN.findall(html or ''):
        video_id = match if isinstance(match, str) else next((part for part in match if part), '')
        if video_id and video_id not in seen:
            seen.add(video_id)
            ids.append(video_id)
    # Newer TamilDhool cards wrap Dailymotion ids in teamstoday.com links.
    for video_id in TEAMSTODAY_PATTERN.findall(html or ''):
        if video_id.startswith('k') and len(video_id) >= 10 and video_id not in seen:
            seen.add(video_id)
            ids.append(video_id)
    return ids


def resolve_dailymotion_stream(video_id):
    if not video_id:
        return '', ''

    metadata_url = f'https://www.dailymotion.com/player/metadata/video/{video_id}'
    headers = {
        'User-Agent': WOODVIOLET_USER_AGENT,
        'Accept': 'application/json',
        'Referer': 'https://www.dailymotion.com/',
    }
    request = urllib.request.Request(metadata_url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15, context=_ssl_context()) as response:
            data = json.loads(response.read().decode('utf-8', 'replace'))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
        log_error(f'Dailymotion metadata failed for {video_id}: {exc}')
        return '', ''

    qualities = data.get('qualities') or {}
    auto = qualities.get('auto') or []
    if auto and isinstance(auto, list):
        stream_url = (auto[0] or {}).get('url') or ''
        if stream_url:
            return stream_url, 'https://www.dailymotion.com/'
    return '', ''


def resolve_tamildhool_stream(title, use_index=True):
    """Resolve the exact same episode via published index, then live page fetch."""
    show, date, channel, episode_number = parse_episode_meta(title)
    log(
        'TamilDhool exact episode: '
        f'show={show!r} date={date} channel={channel} episode={episode_number}'
    )

    if use_index:
        stream_url, referer, cookies = resolve_from_fallback_index(title)
        if stream_url:
            return stream_url, referer, cookies

    urls = build_episode_urls(title)
    if not urls:
        return '', '', ''

    for page_url in urls:
        log(f'TamilDhool fetching exact URL: {page_url}')
        try:
            final_url, html = _fetch_page(page_url)
        except urllib.error.HTTPError as exc:
            log_error(f'TamilDhool fetch failed for {page_url}: HTTP {exc.code}')
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log_error(f'TamilDhool fetch failed for {page_url}: {exc}')
            continue

        if _is_challenge_page(html):
            log_error('TamilDhool returned a Cloudflare challenge page')
            continue
        if not html:
            continue

        if not _page_matches_episode(final_url, html, show, date, channel):
            log_error(
                f'TamilDhool page did not match selected episode '
                f'(wanted {show} {date} {channel}, got {final_url})'
            )
            continue

        bunny_urls = extract_bunny_playlists(html)
        if bunny_urls:
            stream_url = bunny_urls[0]
            log(f'TamilDhool BunnyCDN stream for exact episode: {stream_url}')
            return stream_url, final_url, ''

        for video_id in extract_dailymotion_ids(html):
            stream_url, dm_referer = resolve_dailymotion_stream(video_id)
            if stream_url:
                log(f'TamilDhool Dailymotion stream for exact episode: {stream_url}')
                return stream_url, dm_referer or final_url, ''

        log(f'TamilDhool exact page had no playable sources: {final_url}')

    return '', '', ''
