#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: scaffold_package.sh OUTPUT_PATH" >&2
  exit 1
fi

exec "${PYTHON_BIN:-python3}" -m mcpme.cli scaffold-package demo_pkg "$1"
