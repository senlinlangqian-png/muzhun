#!/usr/bin/env sh
set -eu
MUZHUN_SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -x "$MUZHUN_SCRIPT_DIR/.venv/bin/python" ]; then
    exec "$MUZHUN_SCRIPT_DIR/.venv/bin/python" "$MUZHUN_SCRIPT_DIR/scripts/launch.py" "$@"
fi
exec python3 "$MUZHUN_SCRIPT_DIR/scripts/launch.py" "$@"
