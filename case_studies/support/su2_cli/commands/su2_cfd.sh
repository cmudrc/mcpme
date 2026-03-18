#!/bin/sh
set -eu

# Keep the wrapper intentionally thin so the generated facade still reflects
# the real upstream CLI semantics.
exec SU2_CFD "$@"
