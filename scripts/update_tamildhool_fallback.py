#!/usr/bin/env python3
"""Refresh fallback/tamildhool.json with exact episode -> BunnyCDN mappings.

Pulls recent TamilTvSerial posts for Sun/Vijay/Zee and maps each episode to
TamilDhool BunnyCDN (or Dailymotion) when available.

Requires: pip install cloudscraper
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    import cloudscraper
except ImportError as exc:
    raise SystemExit('Install cloudscraper first: pip install cloudscraper') from exc

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'fallback' / 'tamildhool.json'

CHANNEL_SLUGS = {
    'sun tv': ('sun-tv', 'sun-tv-serial'),
    'vijay tv': ('vijay-tv', 'vijay-tv-serial'),
    'zee tamil': ('zee-tamil', 'zee-tamil-serial'),
}

# Channel category IDs on TamilTvSerial.com
CHANNEL_CATEGORIES = (
    (5, 'Sun TV'),
    (3, 'Vijay TV'),
    (4, 'Zee Tamil'),
)

POSTS_PER_CHANNEL = 80
POSTS_PER_SERIAL = 8
TITLE_DATE_PATTERN = re.compile(r'(\d{1,2})-(\d{1,2})-(\d{4})')
BUNNY_PATTERN = re.compile(
    r'https://(vz-[a-z0-9-]+\.b-cdn\.net)/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/',
    re.I,
)
DAILYMOTION_PATTERN = re.compile(r'(?:dai\.ly/|dailymotion\.com/(?:embed/)?video/)([A-Za-z0-9]+)', re.I)


def slugify(value: str) -> str:
    value = re.sub(r'[^a-z0-9]+', '-', (value or '').lower()).strip('-')
    return re.sub(r'-{2,}', '-', value)


def strip_html(value: str) -> str:
    return re.sub(r'<[^>]+>', '', value or '')


def parse_title(title: str):
    title = strip_html(title).strip()
    match = TITLE_DATE_PATTERN.search(title)
    if not match:
        return None
    date = f'{int(match.group(1)):02d}-{int(match.group(2)):02d}-{match.group(3)}'
    channel = ''
    lower = title.lower()
    for name in CHANNEL_SLUGS:
        if name in lower:
            channel = name
            break
    if not channel:
        return None
    show = title.split('|', 1)[0]
    show = TITLE_DATE_PATTERN.sub('', show)
    show = re.sub(r'\s+', ' ', show).strip(' -|')
    if not show:
        return None
    return show, date, channel


def _ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def api_get(endpoint: str, params: dict):
    url = 'https://www.tamiltvserial.com/wp-json/wp/v2/' + endpoint
    if params:
        url += '?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(request, timeout=30, context=_ssl_context()) as response:
        return json.loads(response.read().decode('utf-8'))


def api_posts(category_id: int, page: int = 1, per_page: int = 40):
    return api_get(
        'posts',
        {
            'categories': category_id,
            'per_page': per_page,
            'page': page,
            'orderby': 'date',
            'order': 'desc',
        },
    )


def list_serial_categories(parent_id: int):
    return api_get(
        'categories',
        {
            'parent': parent_id,
            'per_page': 100,
            'orderby': 'name',
            'order': 'asc',
        },
    )


def _add_episode(episodes: dict, post: dict):
    title = strip_html((post.get('title') or {}).get('rendered', ''))
    meta = parse_title(title)
    if not meta:
        return
    show, date, channel = meta
    channel_slug, _kind = CHANNEL_SLUGS[channel]
    key = f'{channel_slug}/{slugify(show)}/{date}'
    if key not in episodes:
        episodes[key] = (title, show, date, channel)


def collect_episodes():
    """Collect recent episodes from channel feeds and each serial folder."""
    episodes = {}
    per_page = 40
    pages = max(1, (POSTS_PER_CHANNEL + per_page - 1) // per_page)

    for category_id, channel_name in CHANNEL_CATEGORIES:
        fetched = 0
        for page in range(1, pages + 1):
            try:
                posts = api_posts(category_id, page=page, per_page=per_page)
            except Exception as exc:
                print(f'API fail {channel_name} page {page}: {exc}')
                break
            if not posts:
                break
            for post in posts:
                _add_episode(episodes, post)
                fetched += 1
            if len(posts) < per_page or fetched >= POSTS_PER_CHANNEL:
                break
        print(f'Channel feed {channel_name}: {fetched} posts, unique {len(episodes)}')

        try:
            serials = list_serial_categories(category_id)
        except Exception as exc:
            print(f'Serial list fail {channel_name}: {exc}')
            continue

        for serial in serials:
            serial_id = serial.get('id')
            name = strip_html(serial.get('name', ''))
            count = int(serial.get('count') or 0)
            if not serial_id or count <= 0:
                continue
            try:
                posts = api_posts(serial_id, page=1, per_page=POSTS_PER_SERIAL)
            except Exception as exc:
                print(f'  serial fail {name}: {exc}')
                continue
            before = len(episodes)
            for post in posts:
                _add_episode(episodes, post)
            added = len(episodes) - before
            if added:
                print(f'  +{added} from {name}')

    print(f'Total unique episodes to resolve: {len(episodes)}')
    return episodes


EPISODE_SLUG_ALIASES = {
    'pudhu-vasantham': ('puthu-vasantham',),
}


def resolve_page(scraper, show: str, date: str, channel: str):
    channel_slug, kind_slug = CHANNEL_SLUGS[channel]
    show_slug = slugify(show)
    episode_bases = [show_slug] + [
        alias for alias in EPISODE_SLUG_ALIASES.get(show_slug, ()) if alias != show_slug
    ]

    pages = []
    for episode_slug_base in episode_bases:
        pages.append(
            f'https://www.tamildhool.tech/{channel_slug}/{kind_slug}/'
            f'{show_slug}/{episode_slug_base}-{date}-{kind_slug}/'
        )

    # If canonical URLs 404/410, discover the dated link from the show folder.
    show_index = f'https://www.tamildhool.tech/{channel_slug}/{kind_slug}/{show_slug}/'
    try:
        listing = scraper.get(show_index, timeout=30)
        if listing.status_code == 200:
            found = re.findall(
                rf'https://www\.tamildhool\.tech/{channel_slug}/{kind_slug}/{show_slug}/'
                rf'[^\"\']+-{re.escape(date)}-{kind_slug}/',
                listing.text,
                re.I,
            )
            for url in found:
                if url not in pages:
                    pages.append(url)
    except Exception as exc:
        print(f'  listing fail {show_slug}: {exc}')

    last_status = 0
    last_page = pages[0] if pages else ''
    for page in pages:
        last_page = page
        response = scraper.get(page, timeout=30)
        last_status = response.status_code
        if response.status_code != 200 or 'just a moment' in response.text.lower()[:400]:
            continue
        bunny = BUNNY_PATTERN.findall(response.text)
        dailymotion = DAILYMOTION_PATTERN.findall(response.text)
        stream = None
        dm = None
        if bunny:
            host, video_id = bunny[0]
            stream = f'https://{host}/{video_id}/playlist.m3u8'
        if dailymotion:
            dm = dailymotion[0]
        # teamstoday/?video=k... is often a Dailymotion id
        if not dm:
            for match in re.findall(r'teamstoday\.com/\?video=([A-Za-z0-9]+)', response.text, re.I):
                if match.startswith('k') and len(match) >= 10:
                    dm = match
                    break
        if stream or dm:
            return page, stream, dm, response.status_code
    return last_page, None, None, last_status


def main() -> int:
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
    )
    existing = {}
    if OUTPUT.is_file():
        existing = json.loads(OUTPUT.read_text(encoding='utf-8'))

    index = dict(existing)
    episodes = collect_episodes()
    print(f'Resolving {len(episodes)} unique episodes via TamilDhool...')

    ok = skip = fail = 0
    for key, (title, show, date, channel) in sorted(episodes.items()):
        page, stream, dm, status = resolve_page(scraper, show, date, channel)
        if not stream and not dm:
            print(f'SKIP {key} ({status})')
            skip += 1
            fail += 1
            continue
        entry = {
            'title': title,
            'page': page,
            'updated': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        }
        if stream:
            entry['stream'] = stream
            entry['referer'] = page
        if dm:
            entry['dailymotion'] = dm
        index[key] = entry
        ok += 1
        print(f'OK {key}')

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(index, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'Wrote {OUTPUT} ({len(index)} episodes; ok={ok} skip={skip})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
