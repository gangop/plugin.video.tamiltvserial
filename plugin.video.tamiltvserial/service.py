# -*- coding: utf-8 -*-

import json
import sys
import time
from pathlib import Path

import xbmc
import xbmcgui

ADDON_PATH = Path(__file__).resolve().parent
sys.path.insert(0, str(ADDON_PATH / 'resources' / 'lib'))

from constants import (  # noqa: E402
    ADDON_ID,
    DEFAULT_PLAYBACK_START_TIMEOUT,
    PROP_AUTOPLAY_ACTIVE,
    PROP_FAILOVER_CANDIDATES,
    PROP_NEXT_CATEGORY,
    PROP_NEXT_POST,
    PROP_PLAY_WATCH,
)
from utils import addon, get_setting_bool, get_setting_int, log, log_error  # noqa: E402


class AutoplayMonitor(xbmc.Monitor):
    def onNotification(self, sender, method, data):
        if sender != 'xbmc':
            return

        window = xbmcgui.Window(10000)

        # Playback actually started — cancel failover watch.
        if method in ('Player.OnAVStart', 'Player.OnAVChange'):
            if window.getProperty(PROP_PLAY_WATCH) == '1':
                window.clearProperty(PROP_PLAY_WATCH)
                window.clearProperty(PROP_FAILOVER_CANDIDATES)
            return

        if method != 'Player.OnStop':
            return
        if not get_setting_bool('autoplay_next', True):
            return
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


def _playback_started(player):
    if not player.isPlaying():
        return False
    try:
        if player.getTime() > 0.25:
            return True
    except Exception:
        pass
    try:
        total = player.getTotalTime()
        if total and total > 0:
            return True
    except Exception:
        pass
    return False


def _watch_playback_start(monitor, timeout):
    """If the current stream does not start in time, try the next verified source."""
    window = xbmcgui.Window(10000)
    if window.getProperty(PROP_PLAY_WATCH) != '1':
        return

    player = xbmc.Player()
    deadline = time.time() + max(8, int(timeout))
    while time.time() < deadline:
        if monitor.abortRequested():
            return
        if window.getProperty(PROP_PLAY_WATCH) != '1':
            return
        if _playback_started(player):
            window.clearProperty(PROP_PLAY_WATCH)
            window.clearProperty(PROP_FAILOVER_CANDIDATES)
            log('Playback started; failover watch cleared')
            return
        if monitor.waitForAbort(0.5):
            return

    if window.getProperty(PROP_PLAY_WATCH) != '1':
        return

    raw = window.getProperty(PROP_FAILOVER_CANDIDATES)
    try:
        remaining = json.loads(raw) if raw else []
    except (TypeError, ValueError, json.JSONDecodeError):
        remaining = []

    window.clearProperty(PROP_PLAY_WATCH)
    if not remaining:
        log_error('Playback start timed out with no alternate sources')
        return

    log(f'Playback start timed out; failing over ({len(remaining)} alternate source(s))')
    try:
        if player.isPlaying():
            player.stop()
    except Exception as exc:
        log_error(f'Failed to stop player before failover: {exc}')

    xbmc.executebuiltin(
        f'Notification({addon().getAddonInfo("name")}, {addon().getLocalizedString(30049)}, 2500)'
    )
    xbmc.executebuiltin(f'RunPlugin(plugin://{ADDON_ID}/?action=play_failover)')


if __name__ == '__main__':
    monitor = AutoplayMonitor()
    log('Autoplay service started')
    while not monitor.abortRequested():
        window = xbmcgui.Window(10000)
        if window.getProperty(PROP_PLAY_WATCH) == '1':
            timeout = get_setting_int('playback_start_timeout', DEFAULT_PLAYBACK_START_TIMEOUT)
            _watch_playback_start(monitor, timeout)
            continue
        if monitor.waitForAbort(1):
            break
    log('Autoplay service stopped')
