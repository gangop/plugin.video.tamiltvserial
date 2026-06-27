#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
ADDON_DIR="$ROOT/plugin.video.tamiltvserial"
OUTPUT="$ROOT/plugin.video.tamiltvserial.zip"

if [[ ! -d "$ADDON_DIR" ]]; then
  echo "Addon directory not found: $ADDON_DIR" >&2
  exit 1
fi

rm -f "$OUTPUT"
(
  cd "$ROOT"
  zip -r "$OUTPUT" "$(basename "$ADDON_DIR")" \
    -x "*.DS_Store" -x "__pycache__/*" -x "*__pycache__*" -x "*.pyc"
)

echo "Created $OUTPUT"
