# -*- coding: utf-8 -*-

import sys
import traceback
from pathlib import Path
from urllib.parse import parse_qsl

import xbmcgui
import xbmcplugin

ADDON_PATH = Path(__file__).resolve().parent
LIB_PATH = ADDON_PATH / 'resources' / 'lib'
sys.path.insert(0, str(LIB_PATH))

from router import Router  # noqa: E402
from utils import addon, log_error  # noqa: E402


def main():
    plugin_url = sys.argv[0]
    handle = int(sys.argv[1])
    params = dict(parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
    action = params.get('action', 'root')
    is_play = action == 'play'

    try:
        Router(plugin_url, handle).run(params)
    except Exception:
        log_error(traceback.format_exc())
        xbmcgui.Dialog().ok(
            addon().getAddonInfo('name'),
            'Something went wrong. Please try again.',
        )
        if is_play:
            xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        else:
            xbmcplugin.endOfDirectory(handle, succeeded=False)


if __name__ == '__main__':
    main()
