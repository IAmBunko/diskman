#!/usr/bin/env bash
# DiskMan launcher — ensures venv exists, then runs the app.
# Works on Linux and macOS (bash 3.2+).
set -euo pipefail

# Resolve symlinks so ROOT is always the app install dir
# (e.g. ~/.local/bin/diskman -> ~/Applications/DiskMan/run.sh)
SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
  DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  # macOS readlink has no -f; handle relative link targets manually
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
ROOT="$(cd "$(dirname "$SOURCE")" && pwd)"

VENV="$ROOT/.venv"
# Windows-style venv is not used; Unix layout on macOS/Linux
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

# Prefer python3; fall back to python if it is 3.x
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BOOTSTRAP=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON_BOOTSTRAP=python
else
  echo "error: python3 not found on PATH" >&2
  exit 1
fi

if [[ ! -x "$PY" ]]; then
  echo "Creating virtualenv at $VENV ..."
  "$PYTHON_BOOTSTRAP" -m venv "$VENV"
  "$PIP" install -U pip
  "$PIP" install -r "$ROOT/requirements.txt"
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m diskman "$@"
