#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
exec "${PYTHON_BIN:-python3}" "$SCRIPT_DIR/../legacy_solver.py" "$@"
