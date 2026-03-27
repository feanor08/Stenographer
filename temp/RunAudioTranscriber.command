#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

./run.sh

echo
echo "Press Enter to close this window."
read -r _
