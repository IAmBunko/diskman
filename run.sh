#!/usr/bin/env bash
# DiskMan launcher — ensures venv exists, then runs the app.
set -euo pipefail

# Resolve symlinks so ROOT is always the app install dir
# (e.g. ~/.local/bin/diskman -> ~/Applications/DiskMan/run.sh)
SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
  DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
ROOT="$(cd "$(dirname "$SOURCE")" && pwd)"

VENV="$ROOT/.venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

if [[ ! -x "$PY" ]]; then
  echo "Creating virtualenv at $VENV ..."
  python3 -m venv "$VENV"
  "$PIP" install -U pip
  "$PIP" install -r "$ROOT/requirements.txt"
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m diskman "$@"
