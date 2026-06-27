# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path

import xbmc
import xbmcgui

ADDON_ID = 'plugin.video.tamiltvserial'
ADDON_PATH = Path(__file__).resolve().parent
sys.path.insert(0, str(ADDON_PATH / 'resources' / 'lib'))

from constants import PROP_AUTOPLAY_ACTIVE, PROP_NEXT_CATEGORY, PROP_NEXT_POST  # noqa: E402
from utils import addon, get_setting_bool, log  # noqa: E402


class AutoplayMonitor(xbmc.Monitor):
    def onNotification(self, sender, method, data):
        if sender != 'xbmc' or method != 'Player.OnStop':
            return
        if not get_setting_bool('autoplay_next', True):
            return

        window = xbmcgui.Window(10000)
        if window.getProperty(PROP_AUTOPLAY_ACTIVE) != '1':
            return

        try:
            info = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            info = {}

        next_post_id = window.getProperty(PROP_NEXT_POST)
        next_category_id = window.getProperty(PROP_NEXT_CATEGORY)

        self._clear_autoplay(window)

        if not info.get('end') or not next_post_id:
            return

        plugin_url = (
            f'plugin://{ADDON_ID}/?action=play'
            f'&post_id={next_post_id}'
            f'&category_id={next_category_id}'
        )
        log(f'Autoplaying next episode: {next_post_id}')
        xbmc.executebuiltin(
            f'Notification({addon().getAddonInfo("name")}, {addon().getLocalizedString(30036)}, 3000)'
        )
        xbmc.executebuiltin(f'RunPlugin({plugin_url})')

    @staticmethod
    def _clear_autoplay(window):
        window.clearProperty(PROP_NEXT_POST)
        window.clearProperty(PROP_NEXT_CATEGORY)
        window.clearProperty(PROP_AUTOPLAY_ACTIVE)


if __name__ == '__main__':
    monitor = AutoplayMonitor()
    log('Autoplay service started')
    while not monitor.abortRequested():
        if monitor.waitForAbort(1):
            break
    log('Autoplay service stopped')
