#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: scaffold_openapi.sh OUTPUT_PATH" >&2
  exit 1
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
exec "${PYTHON_BIN:-python3}" -m mcpcraft.cli scaffold-openapi \
  "$SCRIPT_DIR/../solver_api.json" \
  "$1"
