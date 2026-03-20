#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: scaffold_su2_cli.sh OUTPUT_PATH" >&2
  exit 1
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
# Wrap the checked-in shell shim instead of `SU2_CFD` directly so the case
# study keeps an inspectable, repository-local command surface.
exec "${PYTHON_BIN:-python3}" -m mcpcraft.cli scaffold-command "$1" \
  --name run_su2_cfd \
  --help-probe-arg=-h \
  -- sh "$SCRIPT_DIR/su2_cfd.sh"
