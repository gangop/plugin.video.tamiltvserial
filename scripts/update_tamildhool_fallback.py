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


def api_posts(category_id: int, page: int = 1, per_page: int = 40):
    params = {
        'categories': category_id,
        'per_page': per_page,
        'page': page,
        'orderby': 'date',
        'order': 'desc',
    }
    url = 'https://www.tamiltvserial.com/wp-json/wp/v2/posts?' + urllib.parse.urlencode(params)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(request, timeout=30, context=ctx) as response:
        return json.loads(response.read().decode('utf-8'))


def collect_episodes():
    """Return dict key -> (title, show, date, channel) for recent channel posts."""
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
                title = strip_html((post.get('title') or {}).get('rendered', ''))
                meta = parse_title(title)
                if not meta:
                    continue
                show, date, channel = meta
                channel_slug, _kind = CHANNEL_SLUGS[channel]
                key = f'{channel_slug}/{slugify(show)}/{date}'
                if key not in episodes:
                    episodes[key] = (title, show, date, channel)
                fetched += 1
            if len(posts) < per_page or fetched >= POSTS_PER_CHANNEL:
                break
        print(f'Collected from {channel_name}: {fetched} posts, unique so far {len(episodes)}')
    return episodes


def resolve_page(scraper, show: str, date: str, channel: str):
    channel_slug, kind_slug = CHANNEL_SLUGS[channel]
    show_slug = slugify(show)
    page = (
        f'https://www.tamildhool.tech/{channel_slug}/{kind_slug}/'
        f'{show_slug}/{show_slug}-{date}-{kind_slug}/'
    )
    response = scraper.get(page, timeout=30)
    if response.status_code != 200 or 'just a moment' in response.text.lower()[:400]:
        return page, None, None, response.status_code
    bunny = BUNNY_PATTERN.findall(response.text)
    dailymotion = DAILYMOTION_PATTERN.findall(response.text)
    stream = None
    dm = None
    if bunny:
        host, video_id = bunny[0]
        stream = f'https://{host}/{video_id}/playlist.m3u8'
    if dailymotion:
        dm = dailymotion[0]
    return page, stream, dm, response.status_code


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
