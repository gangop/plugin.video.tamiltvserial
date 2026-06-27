#!/usr/bin/env python3
"""Generate Kodi repository index files from the video addon manifest."""

from __future__ import annotations

import hashlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def generate(addon_xml: Path, output_dir: Path) -> str:
    addon_elem = ET.parse(addon_xml).getroot()
    version = addon_elem.get('version', '')

    root = ET.Element('addons')
    root.append(addon_elem)

    addons_xml = output_dir / 'addons.xml'
    xml_bytes = ET.tostring(root, encoding='UTF-8')
    addons_xml.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes + b'\n')

    payload = addons_xml.read_bytes()
    (output_dir / 'addons.xml.md5').write_text(
        hashlib.md5(payload).hexdigest() + '\n',
        encoding='utf-8',
    )
    (output_dir / 'addons.xml.sha256').write_text(
        hashlib.sha256(payload).hexdigest() + '\n',
        encoding='utf-8',
    )
    return version


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    addon_xml = root / 'plugin.video.tamiltvserial' / 'addon.xml'
    output_dir = root

    if not addon_xml.is_file():
        print(f'Addon manifest not found: {addon_xml}', file=sys.stderr)
        return 1

    version = generate(addon_xml, output_dir)
    print(f'Generated addons.xml for plugin.video.tamiltvserial {version}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
