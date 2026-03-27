#!/usr/bin/env bash
# OneClickTranscribe.command
# Double-click this file on macOS to install everything and open the GUI.
# On first run: installs Homebrew (if missing), Python 3, FFmpeg, and all
# Python dependencies, then opens the transcriber window.
# Subsequent runs skip straight to opening the window.

set -uo pipefail
cd "$(dirname "$0")"

# ── Helpers ──────────────────────────────────────────────────────────────────

LOG()  { echo "▸ $*"; }
WARN() { echo "⚠️  $*"; }

die() {
    echo ""
    echo "❌  Setup failed: $*"
    echo ""
    echo "Press Enter to close this window."
    read -r _
    exit 1
}

# Add Homebrew to PATH for both Apple Silicon (/opt/homebrew) and Intel (/usr/local)
enable_brew() {
    if [[ -x /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
}

# ── 1. Homebrew ───────────────────────────────────────────────────────────────

enable_brew

if ! command -v brew &>/dev/null; then
    LOG "Homebrew not found – installing it now."
    LOG "(You may be asked for your Mac login password.)"
    echo ""
    NONINTERACTIVE=1 /bin/bash -c \
        "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
        || die "Homebrew installation failed. Please install it from https://brew.sh and try again."
    enable_brew
    command -v brew &>/dev/null || die "Homebrew installed but 'brew' not found in PATH."
    LOG "Homebrew installed."
fi

# ── 2. Python 3 ───────────────────────────────────────────────────────────────

if ! command -v python3 &>/dev/null; then
    LOG "Python 3 not found – installing via Homebrew..."
    brew install python || die "Could not install Python 3."
    LOG "Python 3 installed."
fi

# ── 3. Tkinter (bundled separately by Homebrew) ───────────────────────────────

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if ! python3 -c "import tkinter" &>/dev/null; then
    LOG "Installing tkinter for Python ${PY_VER}..."
    brew install "python-tk@${PY_VER}" || die "Could not install python-tk@${PY_VER}."
    LOG "tkinter installed."
fi

# ── 4. FFmpeg ─────────────────────────────────────────────────────────────────

if ! command -v ffmpeg &>/dev/null; then
    LOG "FFmpeg not found – installing via Homebrew (this may take a minute)..."
    brew install ffmpeg || die "Could not install FFmpeg."
    LOG "FFmpeg installed."
fi

# ── 5. Virtual environment ────────────────────────────────────────────────────

if [[ ! -d venv ]]; then
    LOG "Creating Python virtual environment..."
    python3 -m venv venv || die "Could not create virtual environment."
fi

# ── 6. Python dependencies ────────────────────────────────────────────────────

if [[ ! -f .audio_transcriber_installed ]]; then
    LOG "Installing Python packages (first time – may take several minutes)..."
    venv/bin/pip install --quiet --upgrade pip
    venv/bin/pip install --quiet -r requirements.txt \
        || die "Failed to install Python packages. Check your internet connection and try again."
    touch .audio_transcriber_installed
    LOG "Packages installed."
fi

# ── 7. Launch GUI ─────────────────────────────────────────────────────────────

echo ""
LOG "Opening transcriber window…"
exec venv/bin/python one_click_ui.py
