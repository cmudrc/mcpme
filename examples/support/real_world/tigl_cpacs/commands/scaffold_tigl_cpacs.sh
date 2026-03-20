#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: scaffold_tigl_cpacs.sh OUTPUT_PATH" >&2
  exit 1
fi

# Scaffold only the tiny helper package so the real-world example teaches how to wrap a
# JSON-friendly adapter around a native-heavy upstream dependency.
exec "${PYTHON_BIN:-python3}" -m mcpcraft.cli scaffold-package tigl_support "$1" \
  --symbol-include '^open_cpacs_summary$'
