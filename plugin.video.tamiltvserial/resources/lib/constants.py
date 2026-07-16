# -*- coding: utf-8 -*-

BASE_URL = 'https://www.tamiltvserial.com/'
API_URL = BASE_URL + 'wp-json/wp/v2/'

USER_AGENT = (
    'Mozilla/5.0 (Linux; Android 10; Kodi) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
)

WOODVIOLET_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)

CHANNEL_GROUPS = (
    {
        'name': 'Sun TV',
        'serials_id': 5,
        'shows_id': 6392,
    },
    {
        'name': 'Vijay TV',
        'serials_id': 3,
        'shows_id': 6383,
    },
    {
        'name': 'Zee Tamil',
        'serials_id': 4,
        'shows_id': 6402,
    },
    {
        'name': 'Others',
        'shows_id': 6382,
        'other_shows': True,
    },
)

TAMIL_TV_SHOWS_ID = 6382
SHOW_CHANNEL_IDS = tuple(
    channel['shows_id']
    for channel in CHANNEL_GROUPS
    if channel.get('shows_id') and not channel.get('other_shows')
)

ADDON_ID = 'plugin.video.tamiltvserial'
PROP_NEXT_POST = f'{ADDON_ID}.next_post_id'
PROP_NEXT_CATEGORY = f'{ADDON_ID}.next_category_id'
PROP_AUTOPLAY_ACTIVE = f'{ADDON_ID}.autoplay_active'
PROP_PLAY_WATCH = f'{ADDON_ID}.play_watch'
PROP_FAILOVER_CANDIDATES = f'{ADDON_ID}.failover_candidates'
PROP_FAILOVER_TITLE = f'{ADDON_ID}.failover_title'
PROP_FAILOVER_NEXT_POST = f'{ADDON_ID}.failover_next_post'
PROP_FAILOVER_CATEGORY = f'{ADDON_ID}.failover_category'
DEFAULT_PLAYBACK_START_TIMEOUT = 15
