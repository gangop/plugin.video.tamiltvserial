#!/usr/bin/env python3
"""Refresh fallback/tamildhool.json with exact episode -> BunnyCDN mappings.

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

SHOWS = (
    ('Marumagal', 5, 'marumagal'),
    ('Azhagae Azhagu', 3, 'azhagae'),
)


def slugify(value: str) -> str:
    value = re.sub(r'[^a-z0-9]+', '-', (value or '').lower()).strip('-')
    return re.sub(r'-{2,}', '-', value)


def parse_title(title: str):
    match = re.search(r'(\d{1,2})-(\d{1,2})-(\d{4})', title)
    if not match:
        return None
    date = f'{int(match.group(1)):02d}-{int(match.group(2)):02d}-{match.group(3)}'
    channel = ''
    lower = title.lower()
    for name in CHANNEL_SLUGS:
        if name in lower:
            channel = name
            break
    show = title.split('|', 1)[0]
    show = re.sub(r'\d{1,2}-\d{1,2}-\d{4}', '', show)
    show = re.sub(r'\s+', ' ', show).strip(' -|')
    return show, date, channel


def api_posts(search: str, categories: int, per_page: int = 8):
    params = {
        'search': search,
        'categories': categories,
        'per_page': per_page,
        '_embed': 1,
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


def main() -> int:
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
    )
    existing = {}
    if OUTPUT.is_file():
        existing = json.loads(OUTPUT.read_text(encoding='utf-8'))

    index = dict(existing)
    for search, category_id, prefix in SHOWS:
        for post in api_posts(search, category_id):
            title = re.sub(r'<[^>]+>', '', (post.get('title') or {}).get('rendered', ''))
            if not title.lower().startswith(prefix):
                continue
            meta = parse_title(title)
            if not meta:
                continue
            show, date, channel = meta
            if not channel:
                continue
            channel_slug, kind_slug = CHANNEL_SLUGS[channel]
            show_slug = slugify(show)
            page = (
                f'https://www.tamildhool.tech/{channel_slug}/{kind_slug}/'
                f'{show_slug}/{show_slug}-{date}-{kind_slug}/'
            )
            response = scraper.get(page, timeout=30)
            if response.status_code != 200 or 'just a moment' in response.text.lower()[:300]:
                print(f'SKIP {page} ({response.status_code})')
                continue
            bunny = re.findall(
                r'https://(vz-[a-z0-9-]+\.b-cdn\.net)/([0-9a-f-]{36})/',
                response.text,
                re.I,
            )
            dailymotion = re.findall(r'dai\.ly/([A-Za-z0-9]+)', response.text)
            key = f'{channel_slug}/{show_slug}/{date}'
            entry = {
                'title': title,
                'page': page,
                'updated': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            }
            if bunny:
                host, video_id = bunny[0]
                entry['stream'] = f'https://{host}/{video_id}/playlist.m3u8'
                entry['referer'] = page
            elif dailymotion:
                entry['dailymotion'] = dailymotion[0]
            else:
                print(f'NO SOURCE {key}')
                continue
            index[key] = entry
            print(f'OK {key}')

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(index, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'Wrote {OUTPUT} ({len(index)} episodes)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
