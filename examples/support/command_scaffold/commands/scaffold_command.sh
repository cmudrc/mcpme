#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: scaffold_command.sh OUTPUT_PATH" >&2
  exit 1
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
exec "${PYTHON_BIN:-python3}" -m mcpwrap.cli scaffold-command "$1" \
  --name run_beam_cli \
  -- sh "$SCRIPT_DIR/run_beam_cli.sh"
