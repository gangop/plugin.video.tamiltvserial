#!/usr/bin/env python3
"""Generate Kodi repository index files from addon manifests."""

from __future__ import annotations

import hashlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _append_addon(root: ET.Element, addon_xml: Path) -> str:
    addon_elem = ET.parse(addon_xml).getroot()
    root.append(addon_elem)
    return addon_elem.get('version', '')


def generate(addon_xmls: list[Path], output_dir: Path) -> list[tuple[str, str]]:
    root = ET.Element('addons')
    versions: list[tuple[str, str]] = []
    for addon_xml in addon_xmls:
        version = _append_addon(root, addon_xml)
        versions.append((addon_xml.parent.name, version))

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
    return versions


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    manifests = [
        root / 'plugin.video.tamiltvserial' / 'addon.xml',
        root / 'repository.tamiltvserial' / 'addon.xml',
    ]
    for path in manifests:
        if not path.is_file():
            print(f'Addon manifest not found: {path}', file=sys.stderr)
            return 1

    versions = generate(manifests, root)
    for addon_id, version in versions:
        print(f'Indexed {addon_id} {version}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
