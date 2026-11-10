#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -n "${PYTHON:-}" ]; then
    TEST_PYTHON=$PYTHON
elif [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    TEST_PYTHON="$ROOT_DIR/.venv/bin/python"
else
    TEST_PYTHON=python3
fi
cd "$ROOT_DIR"
PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}" exec "$TEST_PYTHON" -m unittest discover -s tests -v
