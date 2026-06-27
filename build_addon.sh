#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
ADDON_DIR="$ROOT/plugin.video.tamiltvserial"
OUTPUT="$ROOT/plugin.video.tamiltvserial.zip"

if [[ ! -d "$ADDON_DIR" ]]; then
  echo "Addon directory not found: $ADDON_DIR" >&2
  exit 1
fi

compile_po() {
  local po_file="$1"
  local mo_file="${po_file%.po}.mo"
  if command -v msgfmt &>/dev/null; then
    msgfmt -o "$mo_file" "$po_file"
  elif python3 -c "import polib" 2>/dev/null; then
    python3 -c "import polib; polib.pofile('${po_file}').save_as_mofile('${mo_file}')"
  else
    echo "Warning: could not compile ${po_file}; install gettext or polib" >&2
  fi
}

while IFS= read -r -d '' po_file; do
  compile_po "$po_file"
done < <(find "$ADDON_DIR/resources/language" -name strings.po -print0)

rm -f "$OUTPUT"
(
  cd "$ROOT"
  zip -r "$OUTPUT" "$(basename "$ADDON_DIR")" \
    -x "*.DS_Store" -x "__pycache__/*" -x "*__pycache__*" -x "*.pyc"
)

echo "Created $OUTPUT"
