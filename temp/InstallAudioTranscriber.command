#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

./install.sh

echo
echo "Press Enter to close this window."
read -r _
