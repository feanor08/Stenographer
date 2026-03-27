#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

source ./bootstrap_python.sh
ensure_python3

exec "$PYTHON_CMD" audio_transcriber_cli.py install "$@"
