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
mkdir -p "$ZIPS_DIR/repository.tamiltvserial"
cp "$REPO_ZIP" "$ZIPS_DIR/repository.tamiltvserial/repository.tamiltvserial-${REPO_VERSION}.zip"
# Keep only the current repository zip in the datadir.
find "$ZIPS_DIR/repository.tamiltvserial" -name 'repository.tamiltvserial-*.zip' ! -name "repository.tamiltvserial-${REPO_VERSION}.zip" -delete

echo "Created $REPO_ZIP"
echo "Published addon zip: zips/$ADDON_ID/${ADDON_ID}-${ADDON_VERSION}.zip"
echo "Published repo zip: zips/repository.tamiltvserial/repository.tamiltvserial-${REPO_VERSION}.zip"
echo "Updated addons.xml and checksum files"

# Bust jsDelivr CDN cache so TVs do not keep serving a stale addons.xml.
if command -v curl >/dev/null 2>&1; then
  for path in addons.xml addons.xml.md5 \
    "zips/${ADDON_ID}/${ADDON_ID}-${ADDON_VERSION}.zip" \
    "zips/repository.tamiltvserial/repository.tamiltvserial-${REPO_VERSION}.zip"; do
    curl -fsS "https://purge.jsdelivr.net/gh/gangop/plugin.video.tamiltvserial@main/${path}" \
      >/dev/null 2>&1 || true
  done
  echo "Requested jsDelivr purge for index and current zips"
fi
