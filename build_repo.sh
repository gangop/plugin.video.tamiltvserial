#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$ROOT/repository.tamiltvserial"
REPO_VERSION="$(
  python3 -c "
import xml.etree.ElementTree as ET
print(ET.parse('${ROOT}/repository.tamiltvserial/addon.xml').getroot().get('version', '1.0.0'))
"
)"
REPO_ZIP="$ROOT/repository.tamiltvserial-${REPO_VERSION}.zip"
REPO_ZIP_ALIAS="$ROOT/repository.tamiltvserial.zip"
ZIPS_DIR="$ROOT/zips"
ADDON_ID="plugin.video.tamiltvserial"

if [[ ! -d "$REPO_DIR" ]]; then
  echo "Repository addon not found: $REPO_DIR" >&2
  exit 1
fi

"$ROOT/build_addon.sh"

ADDON_VERSION="$(
  python3 -c "
import xml.etree.ElementTree as ET
print(ET.parse('${ROOT}/plugin.video.tamiltvserial/addon.xml').getroot().get('version', ''))
"
)"

if [[ -z "$ADDON_VERSION" ]]; then
  echo "Could not read addon version from addon.xml" >&2
  exit 1
fi

mkdir -p "$ZIPS_DIR/$ADDON_ID"
rm -f "$ZIPS_DIR/$ADDON_ID"/${ADDON_ID}-*.zip
cp "$ROOT/plugin.video.tamiltvserial.zip" \
  "$ZIPS_DIR/$ADDON_ID/${ADDON_ID}-${ADDON_VERSION}.zip"

python3 "$ROOT/scripts/generate_repo_index.py"

rm -f "$REPO_ZIP" "$REPO_ZIP_ALIAS"
(
  cd "$ROOT"
  zip -r -X "$REPO_ZIP" "$(basename "$REPO_DIR")" \
    -x "*.DS_Store" -x "*/__MACOSX/*" -x "__MACOSX/*" -x "__pycache__/*" -x "*__pycache__*" -x "*.pyc"
)
cp "$REPO_ZIP" "$REPO_ZIP_ALIAS"

echo "Created $REPO_ZIP"
echo "Published addon zip: zips/$ADDON_ID/${ADDON_ID}-${ADDON_VERSION}.zip"
echo "Updated addons.xml and checksum files"
