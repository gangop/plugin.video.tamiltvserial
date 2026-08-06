#!/usr/bin/env python3
"""Refresh TamilDhool fallback data used by the Kodi addon.

Writes:
  - fallback/active_serials.json — daily consolidated Sun/Vijay/Zee serials menu
    from TamilDhool + recent TamilTvSerial posts (newest first); also mirrored into
    plugin.video.tamiltvserial/resources/data/
  - fallback/tamildhool.json — episode→stream map for recent serials and shows

The episode indexer is show-agnostic: it walks every Sun/Vijay/Zee serial and
show folder on TamilTvSerial and maps recent episodes to TamilDhool BunnyCDN /
Dailymotion streams.

Hand-maintained show folder aliases live in fallback/show_aliases.json.
Do not add individual episode keys by hand — run this script (or the
GitHub Action) instead.

Requires: pip install cloudscraper
"""

from __future__ import annotations

import html
import json
import re
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import cloudscraper
except ImportError as exc:
    raise SystemExit('Install cloudscraper first: pip install cloudscraper') from exc

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'fallback' / 'tamildhool.json'
ACTIVE_SERIALS_OUTPUT = ROOT / 'fallback' / 'active_serials.json'

CHANNEL_SLUGS = {
    'sun tv': 'sun-tv',
    'vijay tv': 'vijay-tv',
    'zee tamil': 'zee-tamil',
}

# Channel / show category IDs on TamilTvSerial.com
CHANNEL_CATEGORIES = (
    (5, 'Sun TV'),
    (3, 'Vijay TV'),
    (4, 'Zee Tamil'),
    (6392, 'Sun TV Shows'),
    (6383, 'Vijay TV Shows'),
    (6402, 'Zee Tamil TV Shows'),
)

# Serial parent categories used for the Kodi serials menu.
SERIAL_MENU_CHANNELS = (
    ('sun-tv', 5, 'https://www.tamildhool.tech/sun-tv/sun-tv-serial/'),
    ('vijay-tv', 3, 'https://www.tamildhool.tech/vijay-tv/vijay-tv-serial/'),
    ('zee-tamil', 4, 'https://www.tamildhool.tech/zee-tamil/zee-tamil-serial/'),
)

# Keep a serial in the consolidated menu if either source has an episode
# within this many days (TamilDhool-listed shows are always kept).
ACTIVE_SERIAL_DAYS = 21
TTS_RECENT_POST_PAGES = 5

# Extra TamilDhool folder → TTS category slug candidates (beyond show_aliases.json).
FOLDER_TO_TTS_SLUGS = {
    'ethir-neechal-thodargirathu': ('ethirneechal', 'ethir-neechal'),
    'samanthi': ('chamanthi', 'samanthi'),
    'moondru-mudichi': ('moondru-mudichu',),
    'pandian-stores-s-2': ('pandian-stores',),
    'chinna-siru-kiliye': ('chinnan-siru-kiliye', 'chinna-siru-kiliye'),
    'singapenne': ('singappenne',),
    'parijatham': ('paarijatham',),
    'pudhu-vasantham': ('pudhu-vasantham',),
    'puthu-vasantham': ('pudhu-vasantham',),
    'onna-irukka-kaththukkanum': ('onna-irukka-kaththukanum',),
    'sindhu-bairavi-kacheri-arambam': ('sindhu-bairavi',),
}

POSTS_PER_CHANNEL = 120
POSTS_PER_SERIAL = 16
TITLE_DATE_PATTERN = re.compile(r'(\d{1,2})-(\d{1,2})-(\d{4})')
BUNNY_PATTERN = re.compile(
    r'https://(vz-[a-z0-9-]+\.b-cdn\.net)/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/',
    re.I,
)
DAILYMOTION_PATTERN = re.compile(r'(?:dai\.ly/|dailymotion\.com/(?:embed/)?video/)([A-Za-z0-9]+)', re.I)

ALIASES_FILE = ROOT / 'fallback' / 'show_aliases.json'


def load_show_aliases() -> dict:
    """Show-level TamilDhool folder aliases (not episode-specific)."""
    if not ALIASES_FILE.is_file():
        return {}
    data = json.loads(ALIASES_FILE.read_text(encoding='utf-8'))
    return {str(k): tuple(v) for k, v in data.items() if isinstance(v, list) and v}


SHOW_PATH_ALIASES = load_show_aliases()


def slugify(value: str) -> str:
    value = re.sub(r'[^a-z0-9]+', '-', (value or '').lower()).strip('-')
    return re.sub(r'-{2,}', '-', value)


def strip_html(value: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', value or '')
    return html.unescape(re.sub(r'\s+', ' ', text)).strip()


def kind_slug(channel: str, title: str) -> str:
    channel_slug = CHANNEL_SLUGS[channel]
    kind = 'show' if 'tv show' in (title or '').lower() else 'serial'
    return f'{channel_slug}-{kind}'


def path_slugs(show_slug: str):
    aliases = SHOW_PATH_ALIASES.get(show_slug)
    if not aliases:
        return show_slug, [show_slug]
    folder_slug = aliases[0]
    episode_bases = []
    for alias in aliases:
        if alias and alias not in episode_bases:
            episode_bases.append(alias)
    if folder_slug not in episode_bases:
        episode_bases.insert(0, folder_slug)
    return folder_slug, episode_bases


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
    return show, date, channel, title


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
    show, date, channel, full_title = meta
    channel_slug = CHANNEL_SLUGS[channel]
    key = f'{channel_slug}/{slugify(show)}/{date}'
    if key not in episodes:
        episodes[key] = (full_title, show, date, channel)


def collect_episodes():
    """Collect recent episodes from channel feeds and each serial/show folder."""
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


def resolve_page(scraper, show: str, date: str, channel: str, title: str):
    channel_slug = CHANNEL_SLUGS[channel]
    kind = kind_slug(channel, title)
    show_slug = slugify(show)
    folder_slug, episode_bases = path_slugs(show_slug)

    pages = []
    for episode_slug_base in episode_bases:
        pages.append(
            f'https://www.tamildhool.tech/{channel_slug}/{kind}/'
            f'{folder_slug}/{episode_slug_base}-{date}-{kind}/'
        )
        pages.append(
            f'https://www.tamildhool.tech/{channel_slug}/{kind}/'
            f'{folder_slug}/{episode_slug_base}-{date}/'
        )

    # If canonical URLs 404/410, discover the dated link from the show folder.
    show_index = f'https://www.tamildhool.tech/{channel_slug}/{kind}/{folder_slug}/'
    try:
        listing = scraper.get(show_index, timeout=30)
        if listing.status_code == 200:
            # Allow suffixes like -grand-climax / -grand-finale before the kind tag.
            found = re.findall(
                rf'https://www\.tamildhool\.tech/{channel_slug}/{kind}/{folder_slug}/'
                rf'[^\"\']+-{re.escape(date)}[^\"\']*/',
                listing.text,
                re.I,
            )
            for url in found:
                if url not in pages:
                    pages.append(url)
    except Exception as exc:
        print(f'  listing fail {folder_slug}: {exc}')

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


def _tts_slug_candidates(folder: str, title: str):
    candidates = []
    for value in (
        folder,
        slugify(title),
        *FOLDER_TO_TTS_SLUGS.get(folder, ()),
        *SHOW_PATH_ALIASES.get(folder, ()),
        *SHOW_PATH_ALIASES.get(slugify(title), ()),
    ):
        # Reverse lookup: aliases map TTS slug → TamilDhool folders.
        for tts_slug, aliases in SHOW_PATH_ALIASES.items():
            if value == tts_slug or value in aliases:
                if tts_slug not in candidates:
                    candidates.append(tts_slug)
        if value and value not in candidates:
            candidates.append(value)
    return candidates


def _match_tts_category(folder: str, title: str, by_slug: dict):
    for candidate in _tts_slug_candidates(folder, title):
        if candidate in by_slug:
            return by_slug[candidate]
        for slug, category in by_slug.items():
            if slug == candidate or slug.startswith(candidate + '-') or candidate.startswith(slug + '-'):
                return category
    return None


def scrape_tamildhool_serials(scraper, base_url: str, pages: int = 6):
    """Return ordered {folder, title, latest_date} rows from TamilDhool serial pages."""
    folder_re = re.compile(
        r'/(sun-tv|vijay-tv|zee-tamil)/(?:sun-tv|vijay-tv|zee-tamil)-serial/([a-z0-9-]+)/',
        re.I,
    )
    title_re = re.compile(
        r'href=["\']https://www\.tamildhool\.tech/(sun-tv|vijay-tv|zee-tamil)/'
        r'(?:sun-tv|vijay-tv|zee-tamil)-serial/([a-z0-9-]+)/[^"\']*["\'][^>]*>\s*'
        r'([^<]+?)\s+(\d{1,2}-\d{1,2}-\d{4})',
        re.I,
    )
    skip = {'page', 'feed', 'amp'}
    shows = {}
    order = []

    for page in range(1, pages + 1):
        url = base_url if page == 1 else base_url.rstrip('/') + f'/page/{page}/'
        try:
            response = scraper.get(url, timeout=45)
        except Exception as exc:
            print(f'  TamilDhool page fail {url}: {exc}')
            break
        if response.status_code != 200:
            print(f'  TamilDhool page {url} -> {response.status_code}')
            break

        html = response.text
        for match in title_re.finditer(html):
            folder = match.group(2).lower()
            if folder in skip:
                continue
            title = re.sub(r'\s+', ' ', strip_html(match.group(3))).strip()
            date = match.group(4)
            if folder not in shows:
                shows[folder] = {'folder': folder, 'title': title, 'latest_date': date}
                order.append(folder)
            elif not shows[folder].get('latest_date'):
                shows[folder]['latest_date'] = date

        for match in folder_re.finditer(html):
            folder = match.group(2).lower()
            if folder in skip or folder in shows:
                continue
            shows[folder] = {
                'folder': folder,
                'title': folder.replace('-', ' ').title(),
                'latest_date': '',
            }
            order.append(folder)

    return [shows[folder] for folder in order]


def _parse_episode_date(value: str):
    """Return a date from DD-MM-YYYY or ISO timestamps, else None."""
    value = (value or '').strip()
    if not value:
        return None
    match = TITLE_DATE_PATTERN.search(value)
    if match:
        try:
            return datetime(
                int(match.group(3)),
                int(match.group(2)),
                int(match.group(1)),
                tzinfo=timezone.utc,
            ).date()
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).date()
    except ValueError:
        return None


def _format_episode_date(value) -> str:
    if hasattr(value, 'day'):
        return f'{value.day:02d}-{value.month:02d}-{value.year}'
    return str(value or '')


def _date_sort_key(value: str) -> str:
    parsed = _parse_episode_date(value)
    return parsed.isoformat() if parsed else ''


def _canonical_slugs(*values):
    slugs = []
    for value in values:
        slug = slugify(value or '')
        if not slug:
            continue
        for candidate in _tts_slug_candidates(slug, value or ''):
            if candidate and candidate not in slugs:
                slugs.append(candidate)
        if slug not in slugs:
            slugs.append(slug)
    return slugs


def _display_and_search_names(folder: str, title: str, category: dict | None):
    tts_name = strip_html((category or {}).get('name', ''))
    display_name = tts_name or title or folder
    search_name = tts_name or title or display_name
    if folder == 'ethir-neechal-thodargirathu' or slugify(search_name) in {
        'ethirneechal',
        'ethir-neechal',
    }:
        search_name = 'Ethir Neechal'
        display_name = 'Ethir Neechal'
    if folder == 'samanthi' or slugify(display_name) in {'samanthi', 'chamanthi'}:
        display_name = 'Samanthi'
        search_name = 'Samanthi'
    return display_name, search_name


def _skip_serial_name(name: str) -> bool:
    lower = (name or '').lower()
    return (
        not name
        or 'promo' in lower
        or lower.endswith('tv shows')
        or lower.endswith('tv showz')
        or lower == 'tamil tv shows'
    )


def collect_tts_recent_shows(parent_id: int, pages: int = TTS_RECENT_POST_PAGES):
    """Unique shows from recent TamilTvSerial channel posts, newest first."""
    shows = {}
    order = []
    for page in range(1, pages + 1):
        try:
            posts = api_posts(parent_id, page=page, per_page=100)
        except Exception as exc:
            print(f'  TTS recent posts fail parent={parent_id} page={page}: {exc}')
            break
        if not posts:
            break
        for post in posts:
            title = strip_html((post.get('title') or {}).get('rendered', ''))
            meta = parse_title(title)
            if meta:
                show_name, date, _channel, full_title = meta
            else:
                show_name = TITLE_DATE_PATTERN.sub('', title.split('|', 1)[0])
                show_name = re.sub(r'\s+', ' ', show_name).strip(' -|')
                date = ''
                full_title = title
            if _skip_serial_name(show_name) or 'tv show' in show_name.lower():
                continue
            key = slugify(show_name)
            if not key:
                continue
            if key not in shows:
                shows[key] = {
                    'name': show_name,
                    'latest_date': date,
                    'latest_title': full_title,
                    'folder': key,
                }
                order.append(key)
            elif date and _date_sort_key(date) > _date_sort_key(shows[key].get('latest_date', '')):
                shows[key]['latest_date'] = date
                shows[key]['latest_title'] = full_title
        if len(posts) < 100:
            break
    return [shows[key] for key in order]


def _entry_from_sources(
    *,
    parent_id: int,
    folder: str,
    title: str,
    category: dict | None,
    latest_date: str = '',
    latest_title: str = '',
    sources: list[str],
):
    display_name, search_name = _display_and_search_names(folder, title, category)
    count = int((category or {}).get('count') or 0)
    category_id = (category or {}).get('id')
    entry = {
        'name': display_name,
        'folder': folder or slugify(display_name),
        'count': count,
        'sources': sorted(set(sources)),
    }
    if latest_date:
        entry['latest_date'] = latest_date
        entry['latest_title'] = latest_title or f'{display_name} {latest_date}'
    if category_id:
        entry['id'] = category_id
    if not category_id or count <= 0:
        entry['search_query'] = search_name or display_name
        entry['channel_id'] = parent_id
    return entry


def _merge_key_for_entry(entry: dict, category: dict | None = None) -> str:
    parts = [
        entry.get('folder'),
        entry.get('name'),
        strip_html((category or {}).get('name', '')),
    ]
    if entry.get('id'):
        return f'id:{entry["id"]}'
    slugs = _canonical_slugs(*parts)
    return slugs[0] if slugs else slugify(entry.get('name') or 'unknown')


def build_active_serials_catalog(scraper) -> dict:
    """Daily consolidation: union TamilDhool + recent TamilTvSerial, newest first."""
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=ACTIVE_SERIAL_DAYS)
    channels = {}

    for channel_slug, parent_id, url in SERIAL_MENU_CHANNELS:
        print(f'Consolidating serials: {channel_slug}')
        td_shows = scrape_tamildhool_serials(scraper, url)
        tts_recent = collect_tts_recent_shows(parent_id)
        try:
            categories = list_serial_categories(parent_id)
        except Exception as exc:
            print(f'  TTS categories fail {channel_slug}: {exc}')
            categories = []

        by_slug = {}
        by_id = {}
        for category in categories:
            name = strip_html(category.get('name', ''))
            if not name or _skip_serial_name(name):
                continue
            by_slug[slugify(name)] = category
            if category.get('id'):
                by_id[category['id']] = category

        merged = {}

        def upsert(entry: dict, category: dict | None = None):
            key = _merge_key_for_entry(entry, category)
            # Also collide on shared slug aliases so TD/TTS rows become one folder.
            alias_keys = set(_canonical_slugs(entry.get('folder'), entry.get('name')))
            existing_key = key
            for other_key, other in merged.items():
                other_aliases = set(_canonical_slugs(other.get('folder'), other.get('name')))
                if (
                    other_key == key
                    or (entry.get('id') and other.get('id') == entry.get('id'))
                    or alias_keys.intersection(other_aliases)
                ):
                    existing_key = other_key
                    break

            current = merged.get(existing_key)
            if not current:
                merged[existing_key] = entry
                return

            sources = sorted(set(current.get('sources') or []) | set(entry.get('sources') or []))
            current['sources'] = sources
            if entry.get('id') and not current.get('id'):
                current['id'] = entry['id']
            if int(entry.get('count') or 0) > int(current.get('count') or 0):
                current['count'] = entry['count']
            if _date_sort_key(entry.get('latest_date', '')) >= _date_sort_key(
                current.get('latest_date', '')
            ):
                if entry.get('latest_date'):
                    current['latest_date'] = entry['latest_date']
                if entry.get('latest_title'):
                    current['latest_title'] = entry['latest_title']
            if 'tamildhool' in (entry.get('sources') or []) and entry.get('folder'):
                current['folder'] = entry['folder']
            if entry.get('search_query') and (
                not current.get('id') or int(current.get('count') or 0) <= 0
            ):
                current['search_query'] = entry['search_query']
                current['channel_id'] = entry.get('channel_id') or parent_id
            elif current.get('id') and int(current.get('count') or 0) > 0:
                current.pop('search_query', None)
                current.pop('channel_id', None)

        for info in td_shows:
            folder = info['folder']
            title = info['title']
            category = _match_tts_category(folder, title, by_slug)
            entry = _entry_from_sources(
                parent_id=parent_id,
                folder=folder,
                title=title,
                category=category,
                latest_date=info.get('latest_date') or '',
                latest_title='',
                sources=['tamildhool'],
            )
            upsert(entry, category)
            status = f"id={entry.get('id')} count={entry.get('count')}" if entry.get('id') else 'NO TTS MATCH'
            print(f'  TD  {entry["name"]} [{folder}] -> {status}')

        for info in tts_recent:
            name = info['name']
            folder = info.get('folder') or slugify(name)
            latest_date = info.get('latest_date') or ''
            parsed = _parse_episode_date(latest_date)
            # TTS-only rows need a recent episode; already-listed TD shows still get date merges.
            category = by_slug.get(slugify(name)) or _match_tts_category(folder, name, by_slug)
            already = False
            probe = _entry_from_sources(
                parent_id=parent_id,
                folder=(category and slugify(strip_html(category.get('name', '')))) or folder,
                title=name,
                category=category,
                latest_date=latest_date,
                latest_title=info.get('latest_title') or '',
                sources=['tamiltvserial'],
            )
            for other in merged.values():
                if other.get('id') and category and other.get('id') == category.get('id'):
                    already = True
                    break
                if set(_canonical_slugs(other.get('folder'), other.get('name'))).intersection(
                    _canonical_slugs(probe.get('folder'), probe.get('name'))
                ):
                    already = True
                    break

            if already:
                upsert(probe, category)
                print(f'  TTS merge {probe["name"]} ({latest_date})')
                continue

            if parsed and parsed < cutoff:
                print(f'  TTS skip stale {name} ({latest_date})')
                continue

            upsert(probe, category)
            print(f'  TTS add {probe["name"]} [{probe.get("folder")}] ({latest_date})')

        entries = sorted(
            merged.values(),
            key=lambda item: (
                _date_sort_key(item.get('latest_date', '')),
                item.get('name') or '',
            ),
            reverse=True,
        )
        channels[str(parent_id)] = entries
        print(f'  {len(entries)} consolidated serials for {channel_slug}')

    return {
        'updated': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'sources': ['tamildhool', 'tamiltvserial'],
        'active_days': ACTIVE_SERIAL_DAYS,
        'channels': channels,
    }


def write_active_serials(catalog: dict) -> None:
    ACTIVE_SERIALS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(catalog, indent=2, ensure_ascii=False) + '\n'
    ACTIVE_SERIALS_OUTPUT.write_text(payload, encoding='utf-8')

    bundled = ROOT / 'plugin.video.tamiltvserial' / 'resources' / 'data' / 'active_serials.json'
    bundled.parent.mkdir(parents=True, exist_ok=True)
    bundled.write_text(payload, encoding='utf-8')
    total = sum(len(v) for v in (catalog.get('channels') or {}).values())
    print(f'Wrote {ACTIVE_SERIALS_OUTPUT} and {bundled} ({total} serials)')


def mirror_crossover_entries(index: dict) -> int:
    """Copy mahasangamam/crossover streams onto every participating show key.

    Example: a page under lakshmi/…/lakshmi-iru-malargal-mahasangamam-DATE/…
    also becomes sun-tv/iru-malargal/DATE so either serial plays the shared upload.
    """
    shows_by_channel: dict[str, set[str]] = {}
    for key in index:
        parts = key.split('/')
        if len(parts) != 3:
            continue
        channel_slug, show_slug, _date = parts
        shows_by_channel.setdefault(channel_slug, set()).add(show_slug)

    added = 0
    for key, entry in list(index.items()):
        if not isinstance(entry, dict):
            continue
        page = (entry.get('page') or '').lower()
        if not page or not (entry.get('stream') or entry.get('dailymotion')):
            continue
        parts = key.split('/')
        if len(parts) != 3:
            continue
        channel_slug, primary_show, date = parts
        basename = page.rstrip('/').rsplit('/', 1)[-1]
        if 'mahasangamam' not in basename and 'sangamam' not in basename and 'crossover' not in basename:
            continue

        for show_slug in sorted(shows_by_channel.get(channel_slug, ()), key=len, reverse=True):
            if show_slug == primary_show or show_slug not in basename:
                continue
            alt_key = f'{channel_slug}/{show_slug}/{date}'
            existing = index.get(alt_key)
            if isinstance(existing, dict) and existing.get('stream'):
                existing_page = (existing.get('page') or '').lower()
                # Keep a real standalone episode; only fill gaps / replace other crossovers.
                if (
                    'mahasangamam' not in existing_page
                    and 'sangamam' not in existing_page
                    and 'crossover' not in existing_page
                ):
                    continue
            index[alt_key] = dict(entry)
            added += 1
            print(f'MIRROR {alt_key} <- {key}')
    return added


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--serials-only',
        action='store_true',
        help='Only refresh fallback/active_serials.json (skip episode stream index)',
    )
    args = parser.parse_args(argv)

    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
    )

    # Always refresh the serials menu catalog from TamilDhool first (fast).
    catalog = build_active_serials_catalog(scraper)
    write_active_serials(catalog)
    if args.serials_only:
        return 0

    existing = {}
    if OUTPUT.is_file():
        existing = json.loads(OUTPUT.read_text(encoding='utf-8'))

    index = dict(existing)
    episodes = collect_episodes()
    print(f'Resolving {len(episodes)} unique episodes via TamilDhool...')

    ok = skip = fail = 0
    for key, (title, show, date, channel) in sorted(episodes.items()):
        page, stream, dm, status = resolve_page(scraper, show, date, channel, title)
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

    mirrored = mirror_crossover_entries(index)
    print(f'Crossover mirrors added/updated: {mirrored}')

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(index, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'Wrote {OUTPUT} ({len(index)} episodes; ok={ok} skip={skip})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
