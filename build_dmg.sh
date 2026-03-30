#!/usr/bin/env bash
# ══════════════════════════════════════════════════════
#   STENOGRAPHER — build Stenographer.app + DMG
# ══════════════════════════════════════════════════════
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[1;31m'; YEL='\033[1;33m'; GRN='\033[0;32m'; BLU='\033[1;34m'; NC='\033[0m'
hr()   { echo -e "${BLU}══════════════════════════════════════════════${NC}"; }
step() { echo -e "\n${YEL}▸ $1${NC}"; }
ok()   { echo -e "  ${GRN}✓ $1${NC}"; }
die()  { echo -e "  ${RED}✗ $1${NC}"; exit 1; }

VERSION="${BUILD_VERSION:-$(git describe --tags --abbrev=0 2>/dev/null | sed 's/^v//' || echo "1.0.0")}"
DIST="$DIR/dist"
APP="$DIST/Stenographer.app"
DMG_STAGE="$DIST/dmg_stage"
DMG_OUT="$DIST/Stenographer-${VERSION}.dmg"

[ -t 1 ] && clear; hr
echo -e "${YEL}      ▶  STENOGRAPHER  build v${VERSION} ◀${NC}"
hr

# ── Prerequisites ──────────────────────────────────────────────────────────────
step "Checking prerequisites..."
command -v create-dmg &>/dev/null || die "create-dmg not found. Run: brew install create-dmg"
VENV="$DIR/app/venv"
[ -d "$VENV" ] || die "No venv found. Run install.command first."
"$VENV/bin/python" -c "import PyInstaller" &>/dev/null \
    || "$VENV/bin/pip" install pyinstaller
ok "Prerequisites OK"

# ── Clean previous build ───────────────────────────────────────────────────────
step "Cleaning previous build..."
rm -rf "$DIR/build" "$DIST"
ok "Cleaned"

# ── PyInstaller ────────────────────────────────────────────────────────────────
step "Building app bundle (this takes a few minutes)..."
cd "$DIR"
"$VENV/bin/pyinstaller" stenographer.spec --noconfirm
ok "App bundle created at dist/Stenographer.app"

# ── Build standalone CLI binary (separate spec avoids case-insensitive FS
#    conflict between dist/stenographer and dist/Stenographer/ on macOS) ────────
step "Building standalone CLI binary..."
"$VENV/bin/pyinstaller" cli.spec --noconfirm --distpath "$DIST/cli-build"
cp "$DIST/cli-build/stenographer" "$DIST/stenographer"
rm -rf "$DIST/cli-build"
ok "CLI binary created at dist/stenographer"

# ── Sanity check ──────────────────────────────────────────────────────────────
step "Verifying bundle..."
[ -f "$APP/Contents/MacOS/Stenographer" ] || die "GUI binary missing from bundle."
[ -f "$APP/Contents/MacOS/transcribe"   ] || die "CLI binary missing from bundle."
[ -f "$DIST/stenographer"               ] || die "stenographer CLI binary missing from dist/."
ok "All binaries present"

# ── DMG ────────────────────────────────────────────────────────────────────────
step "Creating DMG..."
mkdir -p "$DMG_STAGE"
cp -R "$APP" "$DMG_STAGE/"

ICON_ARG=""
[ -f "$DIR/assets/icon.icns" ] && ICON_ARG="--volicon $DIR/assets/icon.icns"

create-dmg \
    --volname "Stenographer" \
    --window-size 540 380 \
    --icon-size 128 \
    --icon "Stenographer.app" 130 180 \
    --hide-extension "Stenographer.app" \
    --app-drop-link 400 180 \
    $ICON_ARG \
    "$DMG_OUT" \
    "$DMG_STAGE"

rm -rf "$DMG_STAGE"
ok "DMG created: dist/Stenographer-${VERSION}.dmg"

# ── Done ───────────────────────────────────────────────────────────────────────
echo; hr
echo -e "${GRN}  ✓  BUILD COMPLETE${NC}"
echo -e "${YEL}     Output: dist/Stenographer-${VERSION}.dmg${NC}"
hr; echo
