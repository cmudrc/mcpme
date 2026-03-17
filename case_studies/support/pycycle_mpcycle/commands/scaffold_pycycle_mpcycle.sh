#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: scaffold_pycycle_mpcycle.sh OUTPUT_PATH" >&2
  exit 1
fi

exec "${PYTHON_BIN:-python3}" -m mcpme.cli scaffold-package pycycle.api "$1" \
  --symbol-include '^MPCycle$' \
  --max-generated-tools 12
