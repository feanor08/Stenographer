#!/usr/bin/env python3
"""
One-click GUI for Stenographer.

Architecture
------------
tkinter is single-threaded: every widget mutation MUST happen on the main
thread or Tk will crash with a cryptic Tcl error.  Work that blocks
(ffprobe duration probing, the transcription subprocess) runs on daemon
threads and communicates back via a thread-safe queue.Queue.  The main
thread drains that queue every 40 ms via root.after(_poll) — giving the
UI smooth redraws while background work proceeds.

Thread inventory
  _analyze_files  — probes audio durations with ffprobe; posts ("duration", float)
  _worker         — runs transcribe.py as a child process; posts ("log", str)
                    and ("done", bool) messages
  main thread     — _poll() drains the queue and updates widgets safely
"""
import json
import logging
import os
import platform
import shutil
import sys
import re
import subprocess
import threading
import queue
import time
import traceback
from pathlib import Path
from typing import List, Optional
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

# ── Logging ───────────────────────────────────────────────────────────────────
def _app_log_dir() -> Path:
    _s = platform.system()
    if _s == "Windows":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Stenographer" / "Logs"
    if _s == "Darwin":
        return Path.home() / "Library" / "Logs" / "Stenographer"
    return Path.home() / ".local" / "share" / "Stenographer" / "logs"

_LOG_DIR  = _app_log_dir()
_LOG_FILE = _LOG_DIR / "stenographer.log"
try:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        handlers=[
            logging.FileHandler(_LOG_FILE, encoding="utf-8"),
        ],
    )
except Exception:
    logging.basicConfig(level=logging.DEBUG)   # fallback: stderr only

log = logging.getLogger("stenographer")
log.info("=== Stenographer starting (pid %s) ===", os.getpid())
log.info("Python %s  frozen=%s", sys.version, getattr(sys, "frozen", False))

def _excepthook(exc_type, exc_value, exc_tb):
    log.critical("Unhandled exception:\n%s", "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _excepthook

# ── PATH fixup (macOS .app bundles strip PATH to /usr/bin:/bin) ───────────────
def _fixup_path() -> None:
    """
    Inject well-known binary directories into PATH so that ffmpeg/ffprobe are
    found regardless of how the app was launched (double-click, Spotlight, etc).
    On macOS the shell profile is never sourced for .app bundles, so Homebrew's
    /opt/homebrew/bin (Apple Silicon) and /usr/local/bin (Intel) are missing.
    """
    _candidates = [
        "/opt/homebrew/bin",   # Apple Silicon Homebrew
        "/usr/local/bin",      # Intel Homebrew / manual installs
        "/usr/bin",
    ]
    current = os.environ.get("PATH", "")
    additions = [p for p in _candidates if p not in current and os.path.isdir(p)]
    if additions:
        os.environ["PATH"] = os.pathsep.join(additions) + os.pathsep + current
        log.info("PATH extended with: %s", additions)

_fixup_path()

# DnD support — optional; falls back to file-dialog-only if not installed
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND_AVAILABLE = True
    log.info("tkinterdnd2 loaded OK")
except ImportError as _dnd_err:
    _DND_AVAILABLE = False
    log.warning("tkinterdnd2 not available: %s", _dnd_err)

from shared import MODEL_INFO, MODEL_ORDER, fmt_dur, fmt_clock
import updater

PROJECT_DIR = Path(__file__).parent


def _asset_path(filename: str) -> Optional[Path]:
    """
    Resolve a file inside the assets/ folder whether running from source or
    inside a PyInstaller frozen bundle.

    PyInstaller extracts datas into sys._MEIPASS at runtime; for a onedir
    build (Windows) they also land under <exe_dir>/_internal/.
    """
    if getattr(sys, "frozen", False):
        for base in [
            Path(getattr(sys, "_MEIPASS", "")),
            Path(sys.executable).parent / "_internal",
            Path(sys.executable).parent,
        ]:
            p = base / "assets" / filename
            if p.exists():
                return p
    else:
        p = PROJECT_DIR.parent / "assets" / filename
        if p.exists():
            return p
    return None


def bundled_transcribe_path(bundle_dir: Path, system: Optional[str] = None) -> Path:
    system = system or platform.system()
    return bundle_dir / ("transcribe.exe" if system == "Windows" else "transcribe")


if getattr(sys, "frozen", False):
    # Running inside a PyInstaller bundle.
    # The GUI executable and bundled transcribe helper are sibling binaries.
    _bundle_dir = Path(sys.executable).parent
    PYTHON = bundled_transcribe_path(_bundle_dir)
    SCRIPT: Optional[Path] = None          # transcribe is a standalone binary
else:
    PYTHON = (
        PROJECT_DIR / "venv" / "Scripts" / "python.exe"
        if platform.system() == "Windows"
        else PROJECT_DIR / "venv" / "bin" / "python"
    )
    SCRIPT = PROJECT_DIR / "transcribe.py"

MODELS    = MODEL_ORDER
LANGUAGES = ["auto", "en", "hi", "ta", "fr", "es", "de", "zh", "ja", "ko", "ar", "pt", "ru"]
MAX_FILES = 5  # maximum files selectable at once

# ── Colour palette ─────────────────────────────────────────────────────────────
C = {
    "bg":           "#F8FAFC",  # page background
    "bg_card":      "#FFFFFF",  # card / panel surface
    "bg_input":     "#F1F5F9",  # terminal / input background
    "border":       "#E2E8F0",  # default border
    "text":         "#1E293B",  # primary text
    "text_muted":   "#64748B",  # secondary / label text
    "text_hi":      "#0F172A",  # emphasis
    "accent":       "#3B82F6",  # blue accent
    "accent_hov":   "#2563EB",  # darker blue on hover
    "accent_fg":    "#000000",  # text on accent background
    "success":      "#16A34A",  # green
    "success_light":"#DCFCE7",  # light green background
    "error":        "#DC2626",  # red
    "error_light":  "#FEE2E2",  # light red background
    "bar_track":    "#E2E8F0",  # progress bar track
    "sel_bg":       "#EFF6FF",  # hovered / selected row
    "warn_bg":      "#FEF3C7",  # amber banner background
    "warn_fg":      "#92400E",  # amber banner text
}

# Accuracy badge colours (readable on white)
ACC_COLORS = {
    "tiny":     "#DC2626",  # red
    "base":     "#EA580C",  # orange
    "small":    "#CA8A04",  # amber
    "medium":   "#16A34A",  # green
    "large-v3": "#2563EB",  # blue
}

# Platform-appropriate fonts
_sys = platform.system()
if _sys == "Darwin":
    FONT = "SF Pro Display"
    MONO = "SF Mono"
elif _sys == "Windows":
    FONT = "Segoe UI"
    MONO = "Consolas"
else:
    FONT = "DejaVu Sans"
    MONO = "DejaVu Sans Mono"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][AB]")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def open_file(path: str):
    if _sys == "Windows":
        os.startfile(path)
        return
    if _sys == "Darwin":
        subprocess.run(["open", path], check=False)
        return
    if _sys == "Linux":
        subprocess.run(["xdg-open", path], check=False)
        return
    raise RuntimeError(f"Unsupported platform: {_sys}")


def show_in_file_manager(path: str):
    if _sys == "Windows":
        subprocess.run(["explorer", "/select,", path])
        return
    if _sys == "Darwin":
        subprocess.run(["open", "-R", path], check=False)
        return
    if _sys == "Linux":
        subprocess.run(["xdg-open", str(Path(path).parent)], check=False)
        return
    raise RuntimeError(f"Unsupported platform: {_sys}")


SETTINGS_FILE = Path.home() / ".stenographer_settings.json"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(settings: dict) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except Exception:
        pass


def merge_settings(existing: dict, updates: dict) -> dict:
    merged = dict(existing)
    merged.update(updates)
    return merged


def _resolve_bin(name: str) -> Optional[str]:
    """
    Return the full path for a binary, checking PATH then common Homebrew
    locations. Returns None if not found anywhere.
    """
    found = shutil.which(name)
    if found:
        return found
    for candidate in [
        f"/opt/homebrew/bin/{name}",
        f"/usr/local/bin/{name}",
        f"/usr/bin/{name}",
    ]:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def get_audio_duration(path: str) -> float:
    ffprobe = _resolve_bin("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        return max(0.0, float(result.stdout.strip()))
    except Exception:
        return 0.0


# ── Flat progress bar ──────────────────────────────────────────────────────────
class SmoothBar(tk.Canvas):
    def __init__(self, parent, **kw):
        kw.setdefault("bg", C["bg_card"])
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("height", 6)
        super().__init__(parent, **kw)
        self._pct = 0.0
        self._indeterminate = False
        self._bounce_x = 0.0
        self._bounce_dir = 2.0
        self._pulse_id: Optional[str] = None
        self.bind("<Configure>", lambda _e: self._draw())

    def set(self, pct: float):
        self._pct = max(0.0, min(100.0, pct))
        self._draw()

    def pulse(self):
        """Start indeterminate bouncing animation."""
        self._indeterminate = True
        self._bounce_x = 0.0
        self._bounce_dir = 2.0
        self._pulse_step()

    def stop_pulse(self):
        """Stop indeterminate animation and revert to determinate mode."""
        self._indeterminate = False
        if self._pulse_id:
            self.after_cancel(self._pulse_id)
            self._pulse_id = None
        self._draw()

    def _pulse_step(self):
        if not self._indeterminate:
            return
        W = self.winfo_width()
        seg_w = max(1, int(W * 0.28)) if W > 4 else 1
        self._bounce_x += self._bounce_dir
        if self._bounce_x + seg_w >= W:
            self._bounce_x = max(0.0, W - seg_w)
            self._bounce_dir = -2.0
        elif self._bounce_x <= 0:
            self._bounce_x = 0.0
            self._bounce_dir = 2.0
        self._draw()
        self._pulse_id = self.after(25, self._pulse_step)

    def _draw(self):
        self.delete("all")
        W = self.winfo_width()
        H = self.winfo_height()
        if W < 4 or H < 4:
            return
        self.create_rectangle(0, 0, W, H, fill=C["bar_track"], outline="")
        if self._indeterminate:
            seg_w = max(1, int(W * 0.28))
            left  = int(self._bounce_x)
            right = min(W, left + seg_w)
            self.create_rectangle(left, 0, right, H, fill=C["accent"], outline="")
        else:
            fill_w = max(0, int(W * self._pct / 100))
            if fill_w > 0:
                colour = C["success"] if self._pct >= 100 else C["accent"]
                self.create_rectangle(0, 0, fill_w, H, fill=colour, outline="")


# ── ttk style ──────────────────────────────────────────────────────────────────
def _apply_style():
    style = ttk.Style()
    try:
        style.theme_use("default")
    except Exception:
        pass
    style.configure(
        "App.TCombobox",
        fieldbackground=C["bg_card"],
        background=C["bg_card"],
        foreground=C["text"],
        selectbackground=C["sel_bg"],
        selectforeground=C["text"],
        insertcolor=C["text"],
        arrowcolor=C["text_muted"],
        bordercolor=C["border"],
        lightcolor=C["border"],
        darkcolor=C["border"],
        relief="flat",
        font=(FONT, 11),
    )
    style.map(
        "App.TCombobox",
        fieldbackground=[("readonly", C["bg_card"])],
        foreground=[("readonly", C["text"])],
        bordercolor=[("focus", C["accent"])],
        background=[("active", C["sel_bg"])],
    )


# ── Main app ───────────────────────────────────────────────────────────────────
class TranscriberApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Stenographer")
        self.root.configure(bg=C["bg"])
        self.root.resizable(True, True)

        self.selected_files: List[str] = []
        self._output_files: List[str] = []   # paths captured from OUTPUT: lines
        self._failed_files: List[str] = []
        self.q: queue.Queue = queue.Queue()
        self.total_audio_seconds: float = 0.0
        self.transcription_start: Optional[float] = None
        self.estimated_total_s: float = 0.0
        self._tick_id:  Optional[str] = None
        self._poll_id:  Optional[str] = None
        self._proc: Optional[subprocess.Popen] = None
        self._settings: dict = load_settings()

        _apply_style()
        log.info("Building UI…")
        self._build_ui()
        log.info("UI built successfully")
        self._poll()
        threading.Thread(target=self._check_for_update, daemon=True).start()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        if self._poll_id:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        if self._tick_id:
            self.root.after_cancel(self._tick_id)
            self._tick_id = None
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self.root.destroy()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=C["bg_card"])
        hdr.pack(fill="x")

        hdr_inner = tk.Frame(hdr, bg=C["bg_card"], padx=24, pady=20)
        hdr_inner.pack(fill="x")

        tk.Label(hdr_inner, text="Stenographer",
                 font=(FONT, 20, "bold"), bg=C["bg_card"],
                 fg=C["text_hi"]).pack(anchor="w")
        tk.Label(hdr_inner,
                 text="Convert audio to text — runs entirely on your computer",
                 font=(FONT, 11), bg=C["bg_card"],
                 fg=C["text_muted"]).pack(anchor="w", pady=(3, 0))

        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")

        # ── Update banner (hidden until an update is detected) ─────────────────
        # Outer container always packed so inner banner appears in correct position
        _banner_outer = tk.Frame(self.root, bg=C["bg"])
        _banner_outer.pack(fill="x")
        self._update_banner = tk.Frame(_banner_outer, bg=C["warn_bg"])
        banner_inner = tk.Frame(self._update_banner, bg=C["warn_bg"], padx=24, pady=8)
        banner_inner.pack(fill="x")
        self._update_label = tk.Label(
            banner_inner, text="", bg=C["warn_bg"], fg=C["warn_fg"], font=(FONT, 11),
        )
        self._update_label.pack(side="left")
        self._btn(
            banner_inner, "⬇  Download update", self._open_download,
            font=(FONT, 10), pady=4,
        ).pack(side="left", padx=(16, 0))
        self._btn(
            banner_inner, "Dismiss", self._dismiss_update,
            font=(FONT, 10), pady=4,
        ).pack(side="left", padx=(8, 0))

        # ── FFmpeg warning banner (shown immediately if ffmpeg is missing) ────
        _ffmpeg_missing = _resolve_bin("ffmpeg") is None
        if _ffmpeg_missing:
            ffmpeg_banner = tk.Frame(self.root, bg=C["warn_bg"])
            ffmpeg_banner.pack(fill="x")
            inner = tk.Frame(ffmpeg_banner, bg=C["warn_bg"], padx=24, pady=12)
            inner.pack(fill="x")

            # Title row
            title_row = tk.Frame(inner, bg=C["warn_bg"])
            title_row.pack(fill="x")
            tk.Label(title_row, text="⚠  FFmpeg not installed",
                     bg=C["warn_bg"], fg=C["warn_fg"],
                     font=(FONT, 12, "bold")).pack(side="left")

            # Subtitle
            subtitle = (
                "FFmpeg is required for time estimates and broad audio format support. "
                "Transcription may still work for common formats without it."
            )
            tk.Label(inner, text=subtitle,
                     bg=C["warn_bg"], fg=C["warn_fg"],
                     font=(FONT, 10), justify="left", anchor="w",
                     wraplength=580).pack(fill="x", pady=(4, 8))

            def _cmd_row(parent, label, cmd):
                """A labelled command line with a Copy button."""
                row = tk.Frame(parent, bg=C["warn_bg"])
                row.pack(fill="x", pady=2)
                tk.Label(row, text=label, bg=C["warn_bg"], fg=C["warn_fg"],
                         font=(FONT, 9, "bold"), width=10, anchor="w").pack(side="left")
                tk.Label(row, text=cmd, bg=C["bg_input"], fg=C["text"],
                         font=(MONO, 9), padx=8, pady=4,
                         relief="flat", anchor="w").pack(side="left", fill="x", expand=True, padx=(4, 8))
                def _copy(c=cmd):
                    self.root.clipboard_clear()
                    self.root.clipboard_append(c)
                    self.root.update()
                self._btn(row, "Copy", _copy,
                          font=(FONT, 9), pady=4).pack(side="left")

            if _sys == "Windows":
                tk.Label(inner, text="Option 1 — Install via winget (run in Command Prompt or PowerShell):",
                         bg=C["warn_bg"], fg=C["warn_fg"],
                         font=(FONT, 9, "bold")).pack(anchor="w")
                _cmd_row(inner, "", "winget install Gyan.FFmpeg")
                tk.Label(inner, text="Option 2 — Download from ffmpeg.org/download.html and add the bin\\ folder to PATH.",
                         bg=C["warn_bg"], fg=C["warn_fg"],
                         font=(FONT, 9), justify="left").pack(anchor="w", pady=(6, 0))
            else:
                has_brew = _resolve_bin("brew") is not None
                brew_cmd   = '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
                ffmpeg_cmd = "brew install ffmpeg"
                if not has_brew:
                    tk.Label(inner, text="Step 1 — Install Homebrew (paste into Terminal):",
                             bg=C["warn_bg"], fg=C["warn_fg"],
                             font=(FONT, 9, "bold")).pack(anchor="w")
                    _cmd_row(inner, "", brew_cmd)
                    tk.Label(inner, text="Step 2 — Install FFmpeg:",
                             bg=C["warn_bg"], fg=C["warn_fg"],
                             font=(FONT, 9, "bold")).pack(anchor="w", pady=(6, 0))
                    _cmd_row(inner, "", ffmpeg_cmd)
                else:
                    tk.Label(inner, text="Run in Terminal:",
                             bg=C["warn_bg"], fg=C["warn_fg"],
                             font=(FONT, 9, "bold")).pack(anchor="w")
                    _cmd_row(inner, "", ffmpeg_cmd)

        # ── File picker ────────────────────────────────────────────────────────
        file_section = self._card(self.root, title="Audio Files")

        file_row = tk.Frame(file_section, bg=C["bg_card"])
        file_row.pack(fill="x", padx=16, pady=(4, 4))

        self._btn(file_row, "📂  Choose Files", self._browse).pack(side="left")
        self._btn(file_row, "✕  Clear All", self._clear_files,
                  font=(FONT, 10)).pack(side="left", padx=(8, 0))

        self.file_label = tk.Label(
            file_row, text="No files selected",
            fg=C["text_muted"], bg=C["bg_card"],
            font=(FONT, 11), anchor="w",
        )
        self.file_label.pack(side="left", padx=12)

        # Per-file list (populated by _refresh_file_list)
        self._file_rows_frame = tk.Frame(file_section, bg=C["bg_card"])
        self._file_rows_frame.pack(fill="x")

        # Drop zone
        if _DND_AVAILABLE:
            self._drop_zone = tk.Label(
                file_section,
                text="⬆  Drop up to 5 audio files here",
                bg=C["bg_input"], fg=C["text_muted"],
                font=(FONT, 10), pady=12, anchor="center",
            )
            self._drop_zone.pack(fill="x", padx=16, pady=(4, 12))
            try:
                self._drop_zone.drop_target_register(DND_FILES)
                self._drop_zone.dnd_bind("<<Drop>>", self._on_drop)
                self._drop_zone.dnd_bind(
                    "<<DragEnter>>",
                    lambda e: self._drop_zone.config(bg=C["sel_bg"], fg=C["accent"]),
                )
                self._drop_zone.dnd_bind(
                    "<<DragLeave>>",
                    lambda e: self._drop_zone.config(bg=C["bg_input"], fg=C["text_muted"]),
                )
                log.info("Drop target registered OK")
            except Exception as _dnd_reg_err:
                log.exception("Failed to register drop target: %s", _dnd_reg_err)
        else:
            tk.Frame(file_section, bg=C["bg_card"], height=10).pack(fill="x")

        # ── Options ────────────────────────────────────────────────────────────
        opt_section = self._card(self.root, title="Settings")

        opt_row = tk.Frame(opt_section, bg=C["bg_card"])
        opt_row.pack(fill="x", padx=16, pady=(4, 14))

        tk.Label(opt_row, text="Model", fg=C["text_muted"], bg=C["bg_card"],
                 font=(FONT, 11)).pack(side="left")
        self.model_var = tk.StringVar(value=self._settings.get("model", "medium"))
        model_cb = ttk.Combobox(opt_row, textvariable=self.model_var,
                                 values=MODELS, state="readonly", width=12,
                                 style="App.TCombobox")
        model_cb.pack(side="left", padx=(8, 28))
        model_cb.bind("<<ComboboxSelected>>", lambda _e: self._refresh_estimates())

        tk.Label(opt_row, text="Language", fg=C["text_muted"], bg=C["bg_card"],
                 font=(FONT, 11)).pack(side="left")
        self.lang_var = tk.StringVar(value=self._settings.get("language", "auto"))
        ttk.Combobox(opt_row, textvariable=self.lang_var,
                     values=LANGUAGES, state="readonly", width=9,
                     style="App.TCombobox").pack(side="left", padx=(8, 0))

        tk.Label(opt_row, text="Format", fg=C["text_muted"], bg=C["bg_card"],
                 font=(FONT, 11)).pack(side="left", padx=(28, 0))
        self.format_var = tk.StringVar(value=self._settings.get("format", "txt"))
        ttk.Combobox(opt_row, textvariable=self.format_var,
                     values=["txt", "srt", "vtt"], state="readonly", width=6,
                     style="App.TCombobox").pack(side="left", padx=(8, 0))

        # ── Estimates panel (revealed when files are selected) ─────────────────
        self.estimates_outer = tk.Frame(self.root, bg=C["bg"])
        self._build_estimates_panel()
        self._highlight_selected_model()

        # ── Progress panel (revealed when transcription starts) ────────────────
        self.progress_outer = tk.Frame(self.root, bg=C["bg"])
        self._build_progress_panel()

        # ── Transcribe button ──────────────────────────────────────────────────
        self.btn_row = tk.Frame(self.root, bg=C["bg"], padx=24, pady=12)
        self.btn_row.pack(fill="x")

        self.run_btn = self._btn(
            self.btn_row, "Transcribe",
            self._run,
            font=(FONT, 13, "bold"),
            pady=10,
            width=20,
            primary=True,
        )
        self.run_btn.pack(side="left")

        self.stop_btn = self._btn(
            self.btn_row, "⏹  Stop",
            self._stop,
            font=(FONT, 13, "bold"),
            pady=10,
            width=10,
            danger=True,
        )

        self.open_btn = self._btn(
            self.btn_row, "✅  Open Result",
            self._open_result,
            font=(FONT, 13, "bold"),
            pady=10,
            width=16,
            success=True,
        )

        self.show_btn = self._btn(
            self.btn_row, "📂  Show in Finder",
            self._show_in_finder,
            font=(FONT, 13, "bold"),
            pady=10,
            width=18,
        )

        self.retry_btn = self._btn(
            self.btn_row, "🔁  Retry Failed",
            self._retry,
            font=(FONT, 13, "bold"),
            pady=10,
            width=16,
            danger=True,
        )

        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x", pady=(4, 0))

        # ── Console ────────────────────────────────────────────────────────────
        log_frame = tk.Frame(self.root, bg=C["bg"], padx=24, pady=16)
        log_frame.pack(fill="x")

        tk.Label(log_frame, text="Console Output",
                 font=(FONT, 10, "bold"), bg=C["bg"],
                 fg=C["text_muted"]).pack(anchor="w", pady=(0, 6))

        self.out = scrolledtext.ScrolledText(
            log_frame, width=72, height=14, state="disabled",
            bg=C["bg_input"], fg=C["text"], font=(MONO, 10),
            relief="flat", bd=1,
            insertbackground=C["text"],
            wrap="word",
            selectbackground=C["sel_bg"],
            selectforeground=C["text"],
        )
        self.out.pack(fill="x")

        self.root.update()
        self.root.minsize(self.root.winfo_width(), self.root.winfo_height())

    # ── Widget helpers ─────────────────────────────────────────────────────────

    def _card(self, parent, title: str) -> tk.Frame:
        """White card with a muted section title. Returns the inner frame."""
        wrapper = tk.Frame(parent, bg=C["bg"], padx=24, pady=0)
        wrapper.pack(fill="x", pady=(10, 0))

        border = tk.Frame(wrapper, bg=C["border"], padx=1, pady=1)
        border.pack(fill="x")

        inner = tk.Frame(border, bg=C["bg_card"])
        inner.pack(fill="x")

        tk.Label(inner, text=title,
                 font=(FONT, 9, "bold"), bg=C["bg_card"],
                 fg=C["text_muted"], padx=16, pady=9,
                 anchor="w").pack(fill="x")
        tk.Frame(inner, bg=C["border"], height=1).pack(fill="x")

        return inner

    def _btn(self, parent, text, command,
             font=None, pady=7, width=None,
             primary=False, success=False, danger=False) -> tk.Button:
        f = font or (FONT, 11)
        if primary:
            bg, fg, abg, afg = C["accent"],        C["accent_fg"], C["accent_hov"], C["accent_fg"]
        elif success:
            bg, fg, abg, afg = C["success_light"], C["success"],   C["success"],    C["accent_fg"]
        elif danger:
            bg, fg, abg, afg = C["error_light"],   C["error"],     C["error"],      C["accent_fg"]
        else:
            bg, fg, abg, afg = C["bg_card"],       C["text"],      C["sel_bg"],     C["text"]

        kw: dict = dict(
            font=f, fg=fg, bg=bg,
            activeforeground=afg, activebackground=abg,
            relief="flat", bd=0, pady=pady,
            highlightthickness=1,
            highlightbackground=C["border"],
            command=command,
        )
        if width:
            kw["width"] = width
        return tk.Button(parent, text=text, **kw)

    # ── Estimates panel ────────────────────────────────────────────────────────

    def _build_estimates_panel(self):
        outer = self.estimates_outer

        sub = tk.Frame(outer, bg=C["bg"], padx=24)
        sub.pack(fill="x", pady=(10, 0))

        hdr_row = tk.Frame(sub, bg=C["bg"])
        hdr_row.pack(fill="x", pady=(0, 6))

        tk.Label(hdr_row, text="Estimates",
                 font=(FONT, 9, "bold"), bg=C["bg"],
                 fg=C["text_muted"]).pack(side="left")

        self.audio_dur_label = tk.Label(hdr_row, text="",
                                         bg=C["bg"], fg=C["text_muted"],
                                         font=(FONT, 10))
        self.audio_dur_label.pack(side="left", padx=(8, 0))

        tbl_border = tk.Frame(sub, bg=C["border"], padx=1, pady=1)
        tbl_border.pack(fill="x")

        tbl = tk.Frame(tbl_border, bg=C["bg_card"])
        tbl.pack(fill="x")

        col_specs = [
            ("Model",      10),
            ("Speed",      11),
            ("Accuracy",   10),
            ("Est. time",  11),
            ("Finishes ~", 12),
        ]
        for col, (label, w) in enumerate(col_specs):
            tk.Label(tbl, text=label,
                     bg=C["bg_input"], fg=C["text_muted"],
                     font=(FONT, 9, "bold"), width=w,
                     pady=7, anchor="center",
                     ).grid(row=0, column=col, padx=1, pady=(0, 1), sticky="nsew")

        self._est_rows: dict = {}
        for r, model in enumerate(MODEL_ORDER, 1):
            info   = MODEL_INFO[model]
            row_bg = C["bg_input"] if r % 2 == 0 else C["bg_card"]
            cells: dict = {}

            def _lbl(col, text, fg=C["text"], bold=False, _bg=row_bg):
                f = (FONT, 10, "bold") if bold else (FONT, 10)
                w = col_specs[col][1]
                lbl = tk.Label(tbl, text=text, bg=_bg, fg=fg,
                               font=f, width=w, pady=7, anchor="center",
                               )
                lbl.grid(row=r, column=col, padx=1, pady=1, sticky="nsew")
                return lbl

            cells["model"]    = _lbl(0, model,            fg=C["text_hi"],           bold=True)
            cells["speed"]    = _lbl(1, info["speed"],    fg=C["text_muted"])
            cells["accuracy"] = _lbl(2, info["accuracy"], fg=ACC_COLORS.get(model, C["text"]), bold=True)
            cells["est_time"] = _lbl(3, "—",              fg=C["text_muted"])
            cells["finish"]   = _lbl(4, "—",              fg=C["text_muted"])

            self._est_rows[model] = {"cells": cells, "alt_bg": row_bg}

            def _make_select(m):
                def _on_click(_e):
                    self.model_var.set(m)
                    self._refresh_estimates()
                return _on_click

            def _make_hover(m, enter):
                def _on_hover(_e):
                    if self.model_var.get() == m:
                        return
                    bg = C["sel_bg"] if enter else self._est_rows[m]["alt_bg"]
                    for cell in self._est_rows[m]["cells"].values():
                        cell.config(bg=bg)
                return _on_hover

            click_cb     = _make_select(model)
            hover_in_cb  = _make_hover(model, enter=True)
            hover_out_cb = _make_hover(model, enter=False)
            for cell in cells.values():
                cell.bind("<Button-1>", click_cb)
                cell.bind("<Enter>",    hover_in_cb)
                cell.bind("<Leave>",    hover_out_cb)

    def _highlight_selected_model(self):
        """Apply selection highlight to the estimates table (no duration needed)."""
        selected = self.model_var.get()
        for model in MODEL_ORDER:
            row    = self._est_rows[model]
            cells  = row["cells"]
            is_sel = (model == selected)
            row_bg = C["sel_bg"] if is_sel else row["alt_bg"]
            for cell in cells.values():
                cell.config(bg=row_bg)
            if is_sel:
                cells["model"].config(fg=C["accent"], text=f"▶  {model}")
                cells["speed"].config(fg=C["text"])
                cells["est_time"].config(fg=C["accent"])
                cells["finish"].config(fg=C["accent"])
            else:
                cells["model"].config(fg=C["text_hi"], text=model)
                cells["speed"].config(fg=C["text_muted"])
                cells["est_time"].config(fg=C["text_muted"])
                cells["finish"].config(fg=C["text_muted"])

    def _refresh_estimates(self):
        self._highlight_selected_model()
        if self.total_audio_seconds <= 0:
            return
        total_s = self.total_audio_seconds
        self.audio_dur_label.config(text=f"·  Total audio: {fmt_dur(total_s)}")
        for model in MODEL_ORDER:
            info  = MODEL_INFO[model]
            est_s = info["load_s"] + total_s * info["rt_mult"]
            cells = self._est_rows[model]["cells"]
            cells["est_time"].config(text=fmt_dur(est_s))
            cells["finish"].config(text=fmt_clock(est_s))

    # ── Progress panel ─────────────────────────────────────────────────────────

    def _build_progress_panel(self):
        pf = self.progress_outer

        prog_frame = tk.Frame(pf, bg=C["bg"], padx=24)
        prog_frame.pack(fill="x", pady=(10, 4))

        tk.Label(prog_frame, text="Progress",
                 font=(FONT, 9, "bold"), bg=C["bg"],
                 fg=C["text_muted"]).pack(anchor="w", pady=(0, 6))

        # ── Per-file bar ───────────────────────────────────────────────────────
        self._file_prog_label = tk.Label(
            prog_frame, text="Current file",
            font=(FONT, 10), bg=C["bg"], fg=C["text_muted"],
        )
        self._file_prog_label.pack(anchor="w")

        self._file_smooth_bar = SmoothBar(prog_frame, height=4, bg=C["bg"])
        self._file_smooth_bar.pack(fill="x")

        tk.Frame(prog_frame, bg=C["bg"], height=8).pack(fill="x")

        # ── Overall bar ────────────────────────────────────────────────────────
        tk.Label(prog_frame, text="Overall",
                 font=(FONT, 10), bg=C["bg"], fg=C["text_muted"]).pack(anchor="w")

        self.smooth_bar = SmoothBar(prog_frame, height=6, bg=C["bg"])
        self.smooth_bar.pack(fill="x")

        info_row = tk.Frame(prog_frame, bg=C["bg"])
        info_row.pack(fill="x", pady=(6, 0))

        self.remaining_lbl = tk.Label(info_row, text="",
                                       font=(FONT, 11), bg=C["bg"],
                                       fg=C["text"])
        self.remaining_lbl.pack(side="left")

        self.finish_at_lbl = tk.Label(info_row, text="",
                                       font=(FONT, 11), bg=C["bg"],
                                       fg=C["text_muted"])
        self.finish_at_lbl.pack(side="right")

    # ── Progress ticking ───────────────────────────────────────────────────────

    def _start_progress_tick(self):
        self._file_smooth_bar.set(0)
        self._file_prog_label.config(text="Starting…")
        if self.total_audio_seconds <= 0:
            self.smooth_bar.pulse()
            self._file_smooth_bar.pulse()
            self.remaining_lbl.config(text="Working…")
            self.finish_at_lbl.config(text="Duration unknown")
        else:
            self._tick_progress()

    def _tick_progress(self):
        if self.transcription_start is None:
            return
        elapsed   = time.time() - self.transcription_start
        est       = self.estimated_total_s if self.estimated_total_s > 0 else 1.0
        pct       = min(98.0, (elapsed / est) * 100)
        remaining = max(0.0, est - elapsed)

        self.smooth_bar.set(pct)
        self.remaining_lbl.config(text=f"Time left: {fmt_dur(remaining)}")
        self.finish_at_lbl.config(text=f"Done by {fmt_clock(remaining)}")

        self._tick_id = self.root.after(300, self._tick_progress)

    def _stop_progress_tick(self):
        self.smooth_bar.stop_pulse()
        self._file_smooth_bar.stop_pulse()
        if self._tick_id:
            self.root.after_cancel(self._tick_id)
            self._tick_id = None

    # ── File selection ─────────────────────────────────────────────────────────

    def _on_drop(self, event):
        log.info("_on_drop fired  data=%r", event.data)
        self._drop_zone.config(bg=C["bg_input"], fg=C["text_muted"])
        self._add_files(self._parse_dnd_files(event.data))

    def _parse_dnd_files(self, data: str) -> List[str]:
        """Parse the Tcl list of paths that tkinterdnd2 returns on drop."""
        files: List[str] = []
        data = data.strip()
        while data:
            if data.startswith("{"):
                end = data.find("}")
                if end == -1:
                    files.append(data[1:])
                    break
                files.append(data[1:end])
                data = data[end + 1:].strip()
            else:
                parts = data.split(None, 1)
                files.append(parts[0])
                data = parts[1].strip() if len(parts) > 1 else ""
        return files

    def _add_files(self, new_files: List[str]):
        """Add files to the selection, enforcing MAX_FILES and deduplication."""
        from shared import AUDIO_EXTS
        audio  = [f for f in new_files if Path(f).suffix.lower() in AUDIO_EXTS]
        bad    = [Path(f).name for f in new_files if Path(f).suffix.lower() not in AUDIO_EXTS]

        existing = set(self.selected_files)
        to_add   = [f for f in audio if f not in existing]
        dupes    = len(audio) - len(to_add)

        available = MAX_FILES - len(self.selected_files)
        capped    = to_add[:available]
        skipped   = len(to_add) - len(capped)

        if bad:
            preview = "\n".join(bad[:5]) + ("…" if len(bad) > 5 else "")
            messagebox.showwarning(
                "Unsupported files",
                f"{len(bad)} file(s) skipped (unsupported format):\n{preview}",
            )
        if dupes:
            messagebox.showinfo("Duplicates removed", f"{dupes} duplicate file(s) removed.")
        if skipped:
            messagebox.showinfo(
                "Limit reached",
                f"Maximum {MAX_FILES} files allowed. {skipped} file(s) skipped.",
            )

        if not capped:
            return

        self.selected_files.extend(capped)
        self._refresh_file_list()

        self.estimates_outer.pack(fill="x", before=self.btn_row)
        self.audio_dur_label.config(text="·  Analyzing…")
        for row in self._est_rows.values():
            for k in ("est_time", "finish"):
                row["cells"][k].config(text="…")
        threading.Thread(target=self._analyze_files, daemon=True).start()

    def _refresh_file_list(self):
        """Rebuild the per-file list widget from self.selected_files."""
        for w in self._file_rows_frame.winfo_children():
            w.destroy()

        n = len(self.selected_files)
        if n == 0:
            self.file_label.config(text="No files selected", fg=C["text_muted"])
            return

        self.file_label.config(
            text=f"{n} / {MAX_FILES} file{'s' if n != 1 else ''} selected",
            fg=C["text"],
        )

        for i, f in enumerate(self.selected_files):
            row = tk.Frame(self._file_rows_frame, bg=C["bg_card"])
            row.pack(fill="x", padx=16, pady=1)

            tk.Label(
                row,
                text=f"  {i + 1}.  {Path(f).name}",
                bg=C["bg_card"], fg=C["text"],
                font=(FONT, 10), anchor="w",
            ).pack(side="left", fill="x", expand=True)

            def _make_remove(idx: int):
                def _rm():
                    self.selected_files.pop(idx)
                    self._refresh_file_list()
                    if self.selected_files:
                        threading.Thread(target=self._analyze_files, daemon=True).start()
                    else:
                        self.total_audio_seconds = 0.0
                        self.estimates_outer.pack_forget()
                return _rm

            self._btn(
                row, "×", _make_remove(i),
                font=(FONT, 9), pady=2,
            ).pack(side="right", padx=(0, 4))

    def _clear_files(self):
        self.selected_files = []
        self._refresh_file_list()
        self.total_audio_seconds = 0.0
        self.estimates_outer.pack_forget()

    def _browse(self):
        files = filedialog.askopenfilenames(
            title="Select audio files",
            filetypes=[
                ("Audio files", "*.mp3 *.wav *.m4a *.flac *.ogg *.aac *.wma *.mp4 *.mkv"),
                ("All files", "*.*"),
            ],
        )
        if files:
            self._add_files(list(files))

    def _analyze_files(self):
        total  = 0.0
        failed = 0
        for f in self.selected_files:
            dur = get_audio_duration(f)
            if dur > 0:
                total += dur
            else:
                failed += 1
        if failed:
            self.q.put(("log", f"Warning: could not probe duration for {failed} file(s).\n"))
        self.q.put(("duration", total))

    # ── Output helpers ─────────────────────────────────────────────────────────

    def _log(self, text: str):
        try:
            self.out.config(state="normal")
            self.out.insert("end", text)
            self.out.see("end")
        finally:
            self.out.config(state="disabled")

    def _poll(self):
        """
        Drain the cross-thread queue on the main thread every 40 ms.
        Worker threads must never touch widgets directly.
        """
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "done":
                    self._on_done(payload)
                elif kind == "duration":
                    self.total_audio_seconds = payload
                    self._refresh_estimates()
                elif kind == "fileidx":
                    idx, total_files, name = payload
                    self._file_smooth_bar.set(0)
                    self._file_prog_label.config(
                        text=f"File {idx} / {total_files}:  {name}",
                    )
                elif kind == "fileprog":
                    done, total, name = payload
                    pct = (done / total * 100) if total > 0 else 0
                    self._file_smooth_bar.set(pct)
                    self._file_prog_label.config(
                        text=f"File:  {name}  —  {done:.0f}s / {total:.0f}s",
                    )
                elif kind == "update_available":
                    self._show_update_banner(payload)
                elif kind == "update_seen":
                    # No update, but store the latest date for future comparisons
                    self._settings["known_commit_date"] = payload
                    save_settings(self._settings)
        except queue.Empty:
            pass
        self._poll_id = self.root.after(40, self._poll)

    # ── Transcription ──────────────────────────────────────────────────────────

    def _run(self):
        log.info("_run called with %d file(s): %s", len(self.selected_files), self.selected_files)
        if not self.selected_files:
            messagebox.showwarning("No files",
                                   "Please choose at least one audio file first.")
            return

        if not PYTHON.exists():
            messagebox.showerror(
                "Not installed",
                f"Transcriber not found at:\n{PYTHON}\n\nRun  ./install.command  first.",
            )
            return

        model = self.model_var.get()
        info  = MODEL_INFO.get(model, MODEL_INFO["medium"])
        self.estimated_total_s = info["load_s"] + self.total_audio_seconds * info["rt_mult"]

        self._failed_files = []
        self._output_files = []
        self._settings = merge_settings(self._settings, {
            "model": model,
            "language": self.lang_var.get(),
            "format": self.format_var.get(),
        })
        save_settings(self._settings)
        self.run_btn.config(state="disabled", text="Transcribing…",
                            bg=C["text_muted"], fg=C["accent_fg"])
        self.open_btn.pack_forget()
        self.show_btn.pack_forget()
        self.retry_btn.pack_forget()
        self.stop_btn.pack(side="left", padx=(10, 0))
        self.out.config(state="normal")
        self.out.delete("1.0", "end")
        self.out.config(state="disabled")

        self.progress_outer.pack(fill="x", before=self.btn_row)
        self.smooth_bar.set(0)
        self._file_smooth_bar.set(0)
        self._file_prog_label.config(text="Starting…")
        self.remaining_lbl.config(text=f"Time left: {fmt_dur(self.estimated_total_s)}")
        self.finish_at_lbl.config(text=f"Done by {fmt_clock(self.estimated_total_s)}")

        self.transcription_start = time.time()
        self._start_progress_tick()

        threading.Thread(
            target=self._worker,
            args=(model, self.lang_var.get(), self.format_var.get()),
            daemon=True,
        ).start()

    def _worker(self, model: str, lang: str, fmt: str):
        cmd = (
            [str(PYTHON), "--model", model, "--language", lang, "--format", fmt]
            if SCRIPT is None
            else [str(PYTHON), str(SCRIPT), "--model", model, "--language", lang, "--format", fmt]
        )
        for f in self.selected_files:
            cmd += ["--files", f]

        log.info("Subprocess cmd: %s", cmd)
        log.info("PYTHON=%s  exists=%s", PYTHON, Path(str(PYTHON)).exists())

        # NO_COLOR + TERM=dumb suppress Rich's ANSI sequences so the console
        # widget shows plain text.  stderr=STDOUT merges child process errors.
        env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb"}
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                cwd=str(PROJECT_DIR), env=env,
            )
            for line in self._proc.stdout:
                clean = strip_ansi(line)
                log.debug("subprocess: %s", clean.rstrip())
                if clean.startswith("OUTPUT:"):
                    self._output_files.append(clean[len("OUTPUT:"):].strip())
                    self.q.put(("log", clean))
                    continue
                if clean.startswith("FAILED:"):
                    self._failed_files.append(clean[len("FAILED:"):].strip())
                    self.q.put(("log", clean))
                    continue
                if clean.startswith("FILEIDX:"):
                    parts = clean[len("FILEIDX:"):].strip().split(":", 2)
                    if len(parts) == 3:
                        try:
                            self.q.put(("fileidx", (int(parts[0]), int(parts[1]), parts[2])))
                        except ValueError:
                            pass
                    continue
                if clean.startswith("FILEPROG:"):
                    parts = clean[len("FILEPROG:"):].strip().split(":", 2)
                    if len(parts) == 3:
                        try:
                            self.q.put(("fileprog", (float(parts[0]), float(parts[1]), parts[2])))
                        except ValueError:
                            pass
                    continue
                if clean.startswith("LANG:"):
                    parts = clean[len("LANG:"):].strip().split(":")
                    if len(parts) == 2:
                        try:
                            self.q.put(("log", f"Detected language: {parts[0]} ({float(parts[1])*100:.0f}% confidence)\n"))
                            continue
                        except ValueError:
                            pass
                self.q.put(("log", clean))
            self._proc.wait()
            rc = self._proc.returncode
            log.info("Subprocess exited with code %s", rc)
            if rc == 0:
                self.q.put(("log", "\nTranscription complete.\n"))
                self.q.put(("done", True))
            else:
                self.q.put(("log", f"\nProcess exited with code {rc}.\n"))
                self.q.put(("done", False))
        except Exception as exc:
            log.exception("Worker exception: %s", exc)
            self.q.put(("log", f"\nError: {exc}\n"))
            self.q.put(("done", False))
        finally:
            self._proc = None

    def _stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self._output_files = []

    def _on_done(self, success: bool):
        # If the process exited 0 but produced no output (all files failed),
        # treat it as a failure so the UI reflects what actually happened.
        if success and not self._output_files:
            success = False
        log.info("_on_done success=%s  output_files=%s  failed=%s", success, self._output_files, self._failed_files)
        self._stop_progress_tick()
        self.transcription_start = None

        self.smooth_bar.set(100 if success else 0)
        self._file_smooth_bar.set(100 if success else 0)
        if success:
            self.remaining_lbl.config(text="Done  ✓", fg=C["success"])
            self.finish_at_lbl.config(text=f"Finished at {fmt_clock(0)}", fg=C["text_muted"])
            self._file_prog_label.config(text="All files done")
        else:
            self.remaining_lbl.config(text="Failed", fg=C["error"])
            self.finish_at_lbl.config(text="", fg=C["text_muted"])
            self._file_prog_label.config(text="")

        self.stop_btn.pack_forget()
        self.run_btn.config(state="normal", text="Transcribe",
                            bg=C["accent"], fg=C["accent_fg"])
        if success:
            self.open_btn.pack(side="left", padx=(10, 0))
            self.show_btn.pack(side="left", padx=(10, 0))
            self._open_result()  # auto-open the file
        if self._failed_files:
            self.retry_btn.pack(side="left", padx=(10, 0))

    def _check_for_update(self):
        known = self._settings.get("known_commit_date")
        available, latest = updater.check(known)
        if latest is None:
            return  # network failure — stay silent
        if available:
            self.q.put(("update_available", latest))
        else:
            self.q.put(("update_seen", latest))

    def _show_update_banner(self, latest_date: str):
        try:
            from datetime import datetime
            dt = datetime.strptime(latest_date[:10], "%Y-%m-%d")
            label = f"⬆  Update available — released {dt.strftime('%b %d, %Y')}"
        except Exception:
            label = "⬆  Update available"
        self._update_label.config(text=label)
        self._update_banner.pack(fill="x")
        self._pending_update_date = latest_date

    def _dismiss_update(self):
        self._update_banner.pack_forget()
        date = getattr(self, "_pending_update_date", None)
        if date:
            self._settings["known_commit_date"] = date
            save_settings(self._settings)

    def _open_download(self):
        import webbrowser
        webbrowser.open(updater.DOWNLOAD_URL)

    def _retry(self):
        if not self._failed_files:
            return
        self.selected_files = list(self._failed_files)
        names  = [Path(f).name for f in self.selected_files]
        joined = ", ".join(names)
        label  = joined if len(joined) <= 54 else f"{len(self.selected_files)} file(s) selected"
        self.file_label.config(text=label, fg=C["text"])
        self._run()

    def _show_in_finder(self):
        if not self._output_files:
            messagebox.showerror("Not found", "Output path was not captured.")
            return
        show_in_file_manager(self._output_files[0])

    def _open_result(self):
        if not self._output_files:
            messagebox.showerror(
                "File not found",
                "Output file path was not captured.\nCheck the console log above.",
            )
            return
        open_file(self._output_files[0])


def main():
    log.info("Creating root window (DnD=%s)", _DND_AVAILABLE)
    try:
        root = TkinterDnD.Tk() if _DND_AVAILABLE else tk.Tk()
        log.info("Root window created  TkdndVersion=%s", getattr(root, "TkdndVersion", "n/a"))

        # ── Window icon ────────────────────────────────────────────────────────
        # On Windows use .ico (more reliable with Tk's iconbitmap).
        # On macOS/Linux use PNG via iconphoto.
        if platform.system() == "Windows":
            ico = _asset_path("scroll-icon.ico")
            if ico:
                try:
                    root.iconbitmap(str(ico))
                    log.info("Window icon set from %s", ico)
                except Exception as _e:
                    log.warning("iconbitmap failed: %s", _e)
        else:
            png = _asset_path("icon.png")
            if png:
                try:
                    _icon_img = tk.PhotoImage(file=str(png))
                    root.iconphoto(True, _icon_img)
                    log.info("Window icon set from %s", png)
                except Exception as _e:
                    log.warning("iconphoto failed: %s", _e)

        TranscriberApp(root)
        log.info("Entering mainloop")
        root.mainloop()
        log.info("mainloop exited cleanly")
    except Exception:
        log.exception("Fatal error in main()")
        raise


if __name__ == "__main__":
    main()
