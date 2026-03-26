#!/usr/bin/env python3
"""
One-click GUI for Audio Transcriber.

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
import os
import platform
import re
import subprocess
import threading
import queue
import time
from pathlib import Path
from typing import List, Optional
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from shared import MODEL_INFO, MODEL_ORDER, fmt_dur, fmt_clock

PROJECT_DIR = Path(__file__).parent
PYTHON      = PROJECT_DIR / "venv" / "bin" / "python"
SCRIPT      = PROJECT_DIR / "transcribe.py"

MODELS    = MODEL_ORDER
LANGUAGES = ["auto", "en", "hi", "ta", "fr", "es", "de", "zh", "ja", "ko", "ar", "pt", "ru"]

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
    "bar_track":    "#E2E8F0",  # progress bar track
    "sel_bg":       "#EFF6FF",  # hovered / selected row
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


def get_audio_duration(path: str) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        return max(0.0, float(result.stdout.strip()))
    except Exception:
        return 0.0


# ── Flat progress bar ──────────────────────────────────────────────────────────
class SmoothBar(tk.Canvas):
    """A clean, flat progress bar."""

    def __init__(self, parent, **kw):
        kw.setdefault("bg", C["bg_card"])
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("height", 6)
        super().__init__(parent, **kw)
        self._pct = 0.0
        self.bind("<Configure>", lambda _e: self._draw())

    def set(self, pct: float):
        self._pct = max(0.0, min(100.0, pct))
        self._draw()

    def _draw(self):
        self.delete("all")
        W = self.winfo_width()
        H = self.winfo_height()
        if W < 4 or H < 4:
            return
        # Track
        self.create_rectangle(0, 0, W, H, fill=C["bar_track"], outline="")
        # Fill
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
        self.root.title("Audio Transcriber")
        self.root.configure(bg=C["bg"])
        self.root.resizable(True, True)

        self.selected_files: List[str] = []
        self._output_files: List[str] = []   # paths captured from OUTPUT: lines
        self.q: queue.Queue = queue.Queue()
        self.total_audio_seconds: float = 0.0
        self.transcription_start: Optional[float] = None
        self.estimated_total_s: float = 0.0
        self._tick_id:  Optional[str] = None
        self._poll_id:  Optional[str] = None
        self._proc: Optional[subprocess.Popen] = None

        _apply_style()
        self._build_ui()
        self._poll()

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
        self.root.destroy()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=C["bg_card"])
        hdr.pack(fill="x")

        hdr_inner = tk.Frame(hdr, bg=C["bg_card"], padx=24, pady=20)
        hdr_inner.pack(fill="x")

        tk.Label(hdr_inner, text="Audio Transcriber",
                 font=(FONT, 20, "bold"), bg=C["bg_card"],
                 fg=C["text_hi"]).pack(anchor="w")
        tk.Label(hdr_inner,
                 text="Convert audio to text — runs entirely on your computer",
                 font=(FONT, 11), bg=C["bg_card"],
                 fg=C["text_muted"]).pack(anchor="w", pady=(3, 0))

        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")

        # ── File picker ────────────────────────────────────────────────────────
        file_section = self._card(self.root, title="Audio Files")

        file_row = tk.Frame(file_section, bg=C["bg_card"])
        file_row.pack(fill="x", padx=16, pady=(4, 14))

        self._btn(file_row, "📂  Choose Files", self._browse).pack(side="left")

        self.file_label = tk.Label(
            file_row, text="No files selected",
            fg=C["text_muted"], bg=C["bg_card"],
            font=(FONT, 11), anchor="w",
        )
        self.file_label.pack(side="left", padx=12)

        # ── Options ────────────────────────────────────────────────────────────
        opt_section = self._card(self.root, title="Settings")

        opt_row = tk.Frame(opt_section, bg=C["bg_card"])
        opt_row.pack(fill="x", padx=16, pady=(4, 14))

        tk.Label(opt_row, text="Model", fg=C["text_muted"], bg=C["bg_card"],
                 font=(FONT, 11)).pack(side="left")
        self.model_var = tk.StringVar(value="medium")
        model_cb = ttk.Combobox(opt_row, textvariable=self.model_var,
                                 values=MODELS, state="readonly", width=12,
                                 style="App.TCombobox")
        model_cb.pack(side="left", padx=(8, 28))
        model_cb.bind("<<ComboboxSelected>>", lambda _e: self._refresh_estimates())

        tk.Label(opt_row, text="Language", fg=C["text_muted"], bg=C["bg_card"],
                 font=(FONT, 11)).pack(side="left")
        self.lang_var = tk.StringVar(value="auto")
        ttk.Combobox(opt_row, textvariable=self.lang_var,
                     values=LANGUAGES, state="readonly", width=9,
                     style="App.TCombobox").pack(side="left", padx=(8, 0))

        # ── Estimates panel (revealed when files are selected) ─────────────────
        self.estimates_outer = tk.Frame(self.root, bg=C["bg"])
        self._build_estimates_panel()

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
        self.run_btn.pack()

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

        # ── Open result / show in Finder buttons (revealed on success) ───────────
        self._result_row = tk.Frame(self.root, bg=C["bg"], padx=24)
        self.open_btn = self._btn(
            self._result_row, "✅  Open Result",
            self._open_result,
            font=(FONT, 12),
            pady=8,
            width=18,
            success=True,
        )
        self.show_btn = self._btn(
            self._result_row, "📂  Show in Finder",
            self._show_in_finder,
            font=(FONT, 12),
            pady=8,
            width=18,
        )

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
             primary=False, success=False) -> tk.Button:
        f = font or (FONT, 11)
        if primary:
            bg, fg, abg, afg = C["accent"], C["accent_fg"], C["accent_hov"], C["accent_fg"]
        elif success:
            bg, fg, abg, afg = C["success_light"], C["success"], C["success"], C["accent_fg"]
        else:
            bg, fg, abg, afg = C["bg_card"], C["text"], C["sel_bg"], C["text"]

        kw: dict = dict(
            font=f, fg=fg, bg=bg,
            activeforeground=afg, activebackground=abg,
            relief="flat", bd=0, pady=pady,
            cursor="hand2",
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
                               cursor="hand2")
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

    def _refresh_estimates(self):
        if self.total_audio_seconds <= 0:
            return
        total_s  = self.total_audio_seconds
        selected = self.model_var.get()

        self.audio_dur_label.config(text=f"·  Total audio: {fmt_dur(total_s)}")

        for model in MODEL_ORDER:
            info    = MODEL_INFO[model]
            est_s   = info["load_s"] + total_s * info["rt_mult"]
            row     = self._est_rows[model]
            cells   = row["cells"]
            is_sel  = (model == selected)
            row_bg  = C["sel_bg"] if is_sel else row["alt_bg"]

            cells["est_time"].config(text=fmt_dur(est_s))
            cells["finish"].config(text=fmt_clock(est_s))

            for cell in cells.values():
                cell.config(bg=row_bg)

            if is_sel:
                cells["model"].config(fg=C["accent"],      text=f"▶  {model}")
                cells["speed"].config(fg=C["text"])
                cells["est_time"].config(fg=C["accent"])
                cells["finish"].config(fg=C["accent"])
            else:
                cells["model"].config(fg=C["text_hi"],     text=model)
                cells["speed"].config(fg=C["text_muted"])
                cells["est_time"].config(fg=C["text_muted"])
                cells["finish"].config(fg=C["text_muted"])

    # ── Progress panel ─────────────────────────────────────────────────────────

    def _build_progress_panel(self):
        pf = self.progress_outer

        prog_frame = tk.Frame(pf, bg=C["bg"], padx=24)
        prog_frame.pack(fill="x", pady=(10, 4))

        tk.Label(prog_frame, text="Progress",
                 font=(FONT, 9, "bold"), bg=C["bg"],
                 fg=C["text_muted"]).pack(anchor="w", pady=(0, 6))

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
        if self._tick_id:
            self.root.after_cancel(self._tick_id)
            self._tick_id = None

    # ── File selection ─────────────────────────────────────────────────────────

    def _browse(self):
        files = filedialog.askopenfilenames(
            title="Select audio files",
            filetypes=[
                ("Audio files", "*.mp3 *.wav *.m4a *.flac *.ogg *.aac *.wma *.mp4 *.mkv"),
                ("All files", "*.*"),
            ],
        )
        if not files:
            return
        self.selected_files = list(files)
        names  = [Path(f).name for f in files]
        joined = ", ".join(names)
        label  = joined if len(joined) <= 54 else f"{len(files)} file(s) selected"
        self.file_label.config(text=label, fg=C["text"])

        self.estimates_outer.pack(fill="x", before=self.btn_row)
        self.audio_dur_label.config(text="·  Analyzing…")
        for row in self._est_rows.values():
            for k in ("est_time", "finish"):
                row["cells"][k].config(text="…")

        threading.Thread(target=self._analyze_files, daemon=True).start()

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
        except queue.Empty:
            pass
        self._poll_id = self.root.after(40, self._poll)

    # ── Transcription ──────────────────────────────────────────────────────────

    def _run(self):
        if not self.selected_files:
            messagebox.showwarning("No files",
                                   "Please choose at least one audio file first.")
            return

        if not PYTHON.exists():
            messagebox.showerror(
                "Not installed",
                f"Python environment not found at:\n{PYTHON}\n\nRun  ./install  first.",
            )
            return

        model = self.model_var.get()
        info  = MODEL_INFO.get(model, MODEL_INFO["medium"])
        self.estimated_total_s = info["load_s"] + self.total_audio_seconds * info["rt_mult"]

        self._output_files = []
        self.run_btn.config(state="disabled", text="Transcribing…",
                            bg=C["text_muted"], fg=C["accent_fg"])
        self._result_row.pack_forget()
        self.out.config(state="normal")
        self.out.delete("1.0", "end")
        self.out.config(state="disabled")

        self.progress_outer.pack(fill="x", before=self.btn_row)
        self.smooth_bar.set(0)
        self.remaining_lbl.config(text=f"Time left: {fmt_dur(self.estimated_total_s)}")
        self.finish_at_lbl.config(text=f"Done by {fmt_clock(self.estimated_total_s)}")

        self.transcription_start = time.time()
        self._start_progress_tick()

        threading.Thread(
            target=self._worker,
            args=(model, self.lang_var.get()),
            daemon=True,
        ).start()

    def _worker(self, model: str, lang: str):
        cmd = [str(PYTHON), str(SCRIPT), "--model", model, "--language", lang]
        for f in self.selected_files:
            cmd += ["--files", f]

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
                if clean.startswith("OUTPUT:"):
                    self._output_files.append(clean[len("OUTPUT:"):].strip())
                self.q.put(("log", clean))
            self._proc.wait()
            if self._proc.returncode == 0:
                self.q.put(("log", "\nTranscription complete.\n"))
                self.q.put(("done", True))
            else:
                self.q.put(("log", f"\nProcess exited with code {self._proc.returncode}.\n"))
                self.q.put(("done", False))
        except Exception as exc:
            self.q.put(("log", f"\nError: {exc}\n"))
            self.q.put(("done", False))
        finally:
            self._proc = None

    def _on_done(self, success: bool):
        self._stop_progress_tick()
        self.transcription_start = None

        self.smooth_bar.set(100 if success else 0)
        if success:
            self.remaining_lbl.config(text="Done  ✓", fg=C["success"])
            self.finish_at_lbl.config(text=f"Finished at {fmt_clock(0)}", fg=C["text_muted"])
        else:
            self.remaining_lbl.config(text="Failed", fg=C["error"])
            self.finish_at_lbl.config(text="", fg=C["text_muted"])

        self.run_btn.config(state="normal", text="Transcribe",
                            bg=C["accent"], fg=C["accent_fg"])
        if success:
            self._result_row.pack(fill="x", pady=(8, 16))
            self.open_btn.pack(side="left")
            self.show_btn.pack(side="left", padx=(10, 0))

    def _show_in_finder(self):
        if self._output_files:
            subprocess.run(["open", "-R", self._output_files[0]])
        else:
            messagebox.showerror("Not found", "Output path was not captured.")

    def _open_result(self):
        if self._output_files:
            subprocess.run(["open", self._output_files[0]])
        else:
            messagebox.showerror(
                "File not found",
                "Output file path was not captured.\nCheck the console log above.",
            )


def main():
    root = tk.Tk()
    TranscriberApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
