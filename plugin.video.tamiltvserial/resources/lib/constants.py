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
)

TAMIL_TV_SHOWS_ID = 6382

ADDON_ID = 'plugin.video.tamiltvserial'
PROP_NEXT_POST = f'{ADDON_ID}.next_post_id'
PROP_NEXT_CATEGORY = f'{ADDON_ID}.next_category_id'
PROP_AUTOPLAY_ACTIVE = f'{ADDON_ID}.autoplay_active'

DEFAULT_PAGE_SIZE = 40
