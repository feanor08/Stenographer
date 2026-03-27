#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

source ./bootstrap_python.sh
ensure_python3

if ! "$PYTHON_CMD" -c "import tkinter" >/dev/null 2>&1; then
  echo "Desktop GUI is not available because this Python build does not include tkinter."
  echo
  echo "Use one of these double-click launchers instead:"
  echo "  - ./InstallAudioTranscriber.command"
  echo "  - ./RunAudioTranscriber.command"
  echo
  echo "Press Enter to close this window."
  read -r _
  exit 0
fi

exec "$PYTHON_CMD" desktop_launcher.py
