#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: scaffold_tigl_cpacs.sh OUTPUT_PATH" >&2
  exit 1
fi

exec "${PYTHON_BIN:-python3}" -m mcpme.cli scaffold-package tigl_support "$1" \
  --symbol-include '^open_cpacs_summary$'
