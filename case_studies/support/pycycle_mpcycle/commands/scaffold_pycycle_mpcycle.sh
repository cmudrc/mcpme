#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: scaffold_pycycle_mpcycle.sh OUTPUT_PATH" >&2
  exit 1
fi

# Keep the case study pinned to the public scaffold command while narrowing the
# generated surface to the session-oriented `MPCycle` symbol.
exec "${PYTHON_BIN:-python3}" -m mcpme.cli scaffold-package pycycle.api "$1" \
  --symbol-include '^MPCycle$' \
  --max-generated-tools 12
