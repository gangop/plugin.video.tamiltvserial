# -*- coding: utf-8 -*-

import sys
from pathlib import Path
from urllib.parse import parse_qsl

import xbmcaddon

ADDON_PATH = Path(__file__).resolve().parent
LIB_PATH = ADDON_PATH / 'resources' / 'lib'
sys.path.insert(0, str(LIB_PATH))

from router import Router  # noqa: E402


def main():
    plugin_url = sys.argv[0]
    handle = int(sys.argv[1])
    params = dict(parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
    Router(plugin_url, handle).run(params)


if __name__ == '__main__':
    main()
