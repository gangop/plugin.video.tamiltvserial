# -*- coding: utf-8 -*-

BASE_URL = 'https://www.tamiltvserial.com/'
API_URL = BASE_URL + 'wp-json/wp/v2/'

USER_AGENT = (
    'Mozilla/5.0 (Linux; Android 10; Kodi) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
)

CHANNELS = (
    {
        'id': 5,
        'label_id': 30013,
        'name': 'Sun TV Serials',
        'mode': 'serials',
    },
    {
        'id': 3,
        'label_id': 30014,
        'name': 'Vijay TV Serials',
        'mode': 'serials',
    },
    {
        'id': 4,
        'label_id': 30015,
        'name': 'Zee Tamil Serials',
        'mode': 'serials',
    },
    {
        'id': 6382,
        'label_id': 30016,
        'name': 'Tamil TV Shows',
        'mode': 'shows',
    },
)

TAMIL_TV_SHOWS_ID = 6382

ADDON_ID = 'plugin.video.tamiltvserial'
PROP_NEXT_POST = f'{ADDON_ID}.next_post_id'
PROP_NEXT_CATEGORY = f'{ADDON_ID}.next_category_id'
PROP_AUTOPLAY_ACTIVE = f'{ADDON_ID}.autoplay_active'

DEFAULT_PAGE_SIZE = 40
