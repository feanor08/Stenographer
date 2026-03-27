#!/usr/bin/env bash
# ══════════════════════════════════════════════════════
#   STENOGRAPHER — Installer
# ══════════════════════════════════════════════════════
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$DIR/app"
VENV="$APP/venv"

# ANSI colours matching the app palette
RED='\033[1;31m'
YEL='\033[1;33m'
BLU='\033[1;34m'
GRN='\033[0;32m'
DIM='\033[2m'
NC='\033[0m'

hr()   { echo -e "${BLU}══════════════════════════════════════════════${NC}"; }
step() { echo -e "\n${YEL}▸ $1${NC}"; }
ok()   { echo -e "  ${GRN}✓ $1${NC}"; }
warn() { echo -e "  ${RED}⚠  $1${NC}"; }
die()  { echo -e "  ${RED}✗ $1${NC}"; exit 1; }

clear
hr
echo -e "${YEL}      ▶  STENOGRAPHER  ◀${NC}"
echo -e "${DIM}         installer v1.0${NC}"
hr

# ── 1. Python 3 ────────────────────────────────────────────────────────────────
step "Checking Python 3..."
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1)
    ok "Found $PY_VER"
else
    die "Python 3 not found. Install from https://python.org and re-run."
fi

# ── 1b. tkinter ────────────────────────────────────────────────────────────────
step "Checking tkinter..."
if python3 -c "import tkinter" &>/dev/null; then
    ok "tkinter available"
else
    warn "tkinter not found — attempting to install via Homebrew..."
    if command -v brew &>/dev/null; then
        PY_MINOR=$(python3 -c "import sys; print(f'{sys.version_info.minor}')")
        brew install "python-tk@3.${PY_MINOR}" \
            || die "brew install python-tk failed. Try downloading Python from https://python.org and re-run."
        if python3 -c "import tkinter" &>/dev/null; then
            ok "tkinter installed successfully"
        else
            die "tkinter still not found after install. Download Python from https://python.org and re-run."
        fi
    else
        die "tkinter not found and Homebrew is not installed. Download Python from https://python.org (includes tkinter) and re-run."
    fi
fi

# ── 2. Virtual environment ─────────────────────────────────────────────────────
step "Setting up virtual environment..."
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV" || die "Failed to create virtual environment."
    ok "Created venv at app/venv/"
else
    ok "venv already exists — skipping creation"
fi

# ── 3. pip packages ────────────────────────────────────────────────────────────
step "Upgrading pip..."
"$VENV/bin/pip" install --upgrade pip || die "Could not upgrade pip."

step "Installing packages..."
"$VENV/bin/pip" install \
    "click>=8.1.7" \
    "faster-whisper>=1.0.0" \
    "rich>=13.7.0" \
    "typer>=0.12.0" \
    || die "Package install failed — see error above."
ok "Packages installed"

# ── 4. ffmpeg ──────────────────────────────────────────────────────────────────
step "Checking ffmpeg..."
if command -v ffmpeg &>/dev/null; then
    ok "ffmpeg found: $(ffmpeg -version 2>&1 | head -1)"
else
    warn "ffmpeg not found — audio duration probing will be skipped."
    echo -e "  ${DIM}Install it with:  brew install ffmpeg${NC}"
fi

# ── 5. Create the transcribe launcher ─────────────────────────────────────────
step "Writing transcribe launcher..."
cat > "$DIR/transcribe.command" << 'LAUNCHER'
#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f "$DIR/app/venv/bin/python" ]; then
    echo "ERROR: Installation incomplete. Run install.command first." >&2
    exit 1
fi
"$DIR/app/venv/bin/python" "$DIR/app/one_click_ui.py"
LAUNCHER
chmod +x "$DIR/transcribe.command"
ok "transcribe.command launcher created"

# ── Done ───────────────────────────────────────────────────────────────────────
echo
hr
echo -e "${GRN}  ✓  INSTALL COMPLETE${NC}"
echo -e "${YEL}     Double-click transcribe.command to open Stenographer${NC}"
hr
echo
