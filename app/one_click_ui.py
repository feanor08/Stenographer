#!/usr/bin/env python3
"""
One-click GUI for Audio Transcriber — 8-bit Retro Edition.

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
import re
import shutil
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
INPUT_DIR   = PROJECT_DIR / "input_audio"
OUTPUT_FILE = PROJECT_DIR / "transcriptions.txt"
PYTHON      = PROJECT_DIR / "venv" / "bin" / "python"
SCRIPT      = PROJECT_DIR / "transcribe.py"

MODELS    = MODEL_ORDER
LANGUAGES = ["auto", "en", "hi", "ta", "fr", "es", "de", "zh", "ja", "ko", "ar", "pt", "ru"]

# ── Palette: #FF0000  #CC0000  #3B4CCA  #FFDE00  #B3A125 ─────────────────────────
C = {
    "bg":       "#0e0e2e",  # dark indigo body (derived from #3B4CCA)
    "bg_dark":  "#07071a",  # deepest background
    "bg_card":  "#16163e",  # slightly lighter indigo card
    "fg":       "#FFDE00",  # Pokémon yellow — primary text
    "fg_dim":   "#B3A125",  # dark gold — secondary / muted
    "fg_hi":    "#fff59d",  # bright near-white yellow for emphasis
    "yellow":   "#FFDE00",
    "amber":    "#B3A125",
    "blue":     "#3B4CCA",
    "red":      "#FF0000",
    "dark_red": "#CC0000",
    "white":    "#fff9c4",
    "border":   "#3B4CCA",  # Pokémon blue borders
    "hdr_bg":   "#CC0000",  # Pokéball red header
    "btn_bg":   "#CC0000",  # Pokéball red button
    "btn_act":  "#FF0000",  # bright red on hover
    "sel_bg":   "#3B4CCA",  # blue selected row
}

FONT = "Courier"          # The OG monospace

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


# ── Custom pixel-block progress bar ───────────────────────────────────────────
class PixelBar(tk.Canvas):
    """An 8-bit style progress bar drawn with filled blocks."""

    def __init__(self, parent, **kw):
        kw.setdefault("bg", C["bg_card"])
        kw.setdefault("highlightthickness", 2)
        kw.setdefault("highlightbackground", C["border"])
        kw.setdefault("height", 26)
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
        pad = 3
        inner_w = W - pad * 2
        fill_w  = int(inner_w * self._pct / 100)

        # Full trough first; blocks paint over it
        self.create_rectangle(pad, pad, W - pad, H - pad,
                               fill=C["bg_dark"], outline="")

        # Filled section — drawn as discrete pixel blocks separated by gaps.
        # Each loop iteration advances by (block + gap) pixels regardless of
        # whether the block was clipped at the fill edge, so the gap pattern
        # stays uniform and doesn't bunch up at the leading edge.
        block = 10
        gap   = 2
        x = pad
        filled_so_far = 0
        while filled_so_far < fill_w:
            bw = min(block, fill_w - filled_so_far)
            # Last block gets the brighter highlight colour for a "leading edge" effect
            colour = C["fg"] if filled_so_far < fill_w - block else C["fg_hi"]
            self.create_rectangle(x, pad + 2, x + bw, H - pad - 2,
                                   fill=colour, outline="")
            x            += block + gap
            filled_so_far += block + gap

        # Scanline overlay — stipple draws every other pixel transparent,
        # so the bg_dark shows through on alternate rows like a CRT scanline
        for y in range(pad + 2, H - pad - 2, 2):
            self.create_line(pad, y, min(pad + fill_w, W - pad), y,
                              fill=C["bg_dark"], stipple="gray50")

        # Percentage label — flips to dark text once the bar passes the centre
        # so it stays readable against both the filled and unfilled sections
        label_x = W // 2
        txt_col = C["bg"] if self._pct > 56 else C["fg"]
        self.create_text(label_x, H // 2, text=f" {int(self._pct)}% ",
                          fill=txt_col, font=(FONT, 10, "bold"))


# ── Retro-styled combobox helper ───────────────────────────────────────────────
def _apply_retro_style():
    """
    Patch the ttk theme for comboboxes and other shared widgets.

    We force the "default" theme first because themed engines like
    "aqua" (macOS) ignore many configure() keys, making the combobox
    look system-native instead of retro.  The try/except is a no-op
    fallback if the theme switch fails on an unusual platform.
    """
    style = ttk.Style()
    try:
        style.theme_use("default")
    except Exception:
        pass
    style.configure("Retro.TCombobox",
                    fieldbackground=C["bg_card"],
                    background=C["btn_bg"],
                    foreground=C["fg"],
                    selectbackground=C["sel_bg"],
                    selectforeground=C["fg"],
                    insertcolor=C["fg"],
                    arrowcolor=C["fg"],
                    bordercolor=C["border"],
                    lightcolor=C["border"],
                    darkcolor=C["border"],
                    relief="flat",
                    font=(FONT, 11))
    style.map("Retro.TCombobox",
              fieldbackground=[("readonly", C["bg_card"])],
              foreground=[("readonly", C["fg"])],
              background=[("active", C["btn_act"])])


# ── Main app ───────────────────────────────────────────────────────────────────
class TranscriberApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("► AUDIO TRANSCRIBER ◄")
        self.root.configure(bg=C["bg"])
        self.root.resizable(True, False)

        self.selected_files: List[str] = []
        self.q: queue.Queue = queue.Queue()  # cross-thread message bus
        self.total_audio_seconds: float = 0.0
        self.transcription_start: Optional[float] = None  # wall time, set when _run() fires
        self.estimated_total_s: float = 0.0
        # after() callback IDs — stored so we can cancel them on window close
        self._tick_id: Optional[str] = None
        self._blink_id: Optional[str] = None
        self._poll_id: Optional[str] = None
        self._blink_on = True
        self._proc: Optional[subprocess.Popen] = None  # ref to live subprocess for termination

        _apply_retro_style()
        self._build_ui()
        self._poll()
        self._blink()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        """Cancel all pending callbacks and kill any running subprocess."""
        if self._poll_id:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        if self._tick_id:
            self.root.after_cancel(self._tick_id)
            self._tick_id = None
        if self._blink_id:
            self.root.after_cancel(self._blink_id)
            self._blink_id = None
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self.root.destroy()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=C["hdr_bg"], pady=0)
        hdr.pack(fill="x")

        # Top scanline strip
        tk.Frame(hdr, bg=C["fg_dim"], height=2).pack(fill="x")

        inner_hdr = tk.Frame(hdr, bg=C["hdr_bg"], pady=14)
        inner_hdr.pack(fill="x")

        # Blinking cursor label stored for animation
        title_row = tk.Frame(inner_hdr, bg=C["hdr_bg"])
        title_row.pack()
        tk.Label(title_row, text="► AUDIO TRANSCRIBER ◄",
                 font=(FONT, 24, "bold"), bg=C["hdr_bg"], fg=C["fg"]).pack(side="left")
        self.cursor_lbl = tk.Label(title_row, text="█",
                                    font=(FONT, 24, "bold"), bg=C["hdr_bg"], fg=C["fg"])
        self.cursor_lbl.pack(side="left", padx=(4, 0))

        tk.Label(inner_hdr,
                 text="SELECT FILES  ·  PICK MODEL  ·  HIT TRANSCRIBE",
                 font=(FONT, 10), bg=C["hdr_bg"], fg=C["fg_dim"]).pack(pady=(2, 0))

        # Bottom scanline strip
        tk.Frame(hdr, bg=C["fg_dim"], height=2).pack(fill="x")

        # ── File picker row ────────────────────────────────────────────────────
        file_card = self._card(self.root)
        file_card.pack(fill="x", padx=14, pady=(12, 4))

        file_inner = tk.Frame(file_card, bg=C["bg_card"])
        file_inner.pack(fill="x", padx=10, pady=8)

        self._retro_button(file_inner, "[ 📂 CHOOSE FILES ]",
                           self._browse, bg=C["btn_bg"], fg=C["fg"],
                           active_bg=C["btn_act"], active_fg=C["fg"],
                           width=20).pack(side="left")

        self.file_label = tk.Label(file_inner, text="NO FILES SELECTED",
                                    fg=C["fg_dim"], bg=C["bg_card"],
                                    font=(FONT, 11), anchor="w")
        self.file_label.pack(side="left", padx=14)

        # ── Options row ───────────────────────────────────────────────────────
        opt_card = self._card(self.root)
        opt_card.pack(fill="x", padx=14, pady=4)

        opt_inner = tk.Frame(opt_card, bg=C["bg_card"])
        opt_inner.pack(fill="x", padx=10, pady=8)

        tk.Label(opt_inner, text="MODEL:", fg=C["fg_dim"], bg=C["bg_card"],
                 font=(FONT, 11, "bold")).pack(side="left")
        self.model_var = tk.StringVar(value="medium")
        model_cb = ttk.Combobox(opt_inner, textvariable=self.model_var,
                                 values=MODELS, state="readonly", width=11,
                                 style="Retro.TCombobox")
        model_cb.pack(side="left", padx=(6, 28))
        model_cb.bind("<<ComboboxSelected>>", lambda _e: self._refresh_estimates())

        tk.Label(opt_inner, text="LANGUAGE:", fg=C["fg_dim"], bg=C["bg_card"],
                 font=(FONT, 11, "bold")).pack(side="left")
        self.lang_var = tk.StringVar(value="auto")
        ttk.Combobox(opt_inner, textvariable=self.lang_var,
                     values=LANGUAGES, state="readonly", width=8,
                     style="Retro.TCombobox").pack(side="left", padx=(6, 0))

        # ── Estimates panel (hidden until files selected) ──────────────────────
        self.estimates_outer = tk.Frame(self.root, bg=C["bg"])
        self._build_estimates_panel()

        # ── Progress panel (hidden until transcription runs) ───────────────────
        self.progress_outer = tk.Frame(self.root, bg=C["bg"])
        self._build_progress_panel()

        # ── Transcribe button ──────────────────────────────────────────────────
        self.btn_row = tk.Frame(self.root, bg=C["bg"], pady=12)
        self.btn_row.pack()
        self.run_btn = self._retro_button(
            self.btn_row,
            "[ ▶  TRANSCRIBE ]",
            self._run,
            font=(FONT, 16, "bold"),
            fg=C["fg"],
            bg=C["btn_bg"],
            active_bg=C["btn_act"],
            active_fg=C["fg"],
            width=22,
            pady=10,
        )
        self.run_btn.pack()

        # ── Live output terminal ───────────────────────────────────────────────
        term_card = self._card(self.root)
        term_card.pack(fill="x", padx=14, pady=(4, 4))

        tk.Label(term_card, text=" CONSOLE OUTPUT ",
                 font=(FONT, 9, "bold"), bg=C["border"], fg=C["bg"]).pack(anchor="w")

        self.out = scrolledtext.ScrolledText(
            term_card, width=72, height=16, state="disabled",
            bg=C["bg_dark"], fg=C["fg"], font=(FONT, 10),
            relief="flat", insertbackground=C["fg"],
            wrap="word", selectbackground=C["sel_bg"],
            selectforeground=C["fg_hi"],
        )
        self.out.pack(padx=2, pady=(0, 2))

        # ── Open result button (hidden until success) ──────────────────────────
        self.open_btn = self._retro_button(
            self.root, "[ ✅  OPEN RESULT ]",
            self._open_result,
            font=(FONT, 13, "bold"),
            fg=C["bg"], bg=C["fg"],
            active_bg=C["fg_hi"], active_fg=C["bg"],
            width=22, pady=8,
        )

        self.root.update()
        self.root.minsize(self.root.winfo_width(), self.root.winfo_height())

    # ── Reusable widget helpers ────────────────────────────────────────────────

    def _card(self, parent) -> tk.Frame:
        """
        A bordered card frame.

        The 1-px padx/pady on the outer Frame shows through as a solid
        border line — no Canvas or relief tricks needed.  Children should
        be packed into the returned frame with their own bg so the border
        colour remains visible around the edges.
        """
        border = tk.Frame(parent, bg=C["border"], padx=1, pady=1)
        border.configure(bg=C["border"])
        return border

    def _retro_button(self, parent, text, command,
                      font=None, fg=None, bg=None,
                      active_fg=None, active_bg=None,
                      width=None, pady=6) -> tk.Button:
        f   = font      or (FONT, 12, "bold")
        fg  = fg        or C["fg"]
        bg  = bg        or C["btn_bg"]
        afg = active_fg or C["fg_hi"]
        abg = active_bg or C["btn_act"]
        kw  = dict(font=f, fg=fg, bg=bg, activeforeground=afg, activebackground=abg,
                   relief="flat", bd=0, pady=pady, cursor="hand2",
                   highlightthickness=2, highlightbackground=C["border"],
                   highlightcolor=C["fg"], command=command)
        if width:
            kw["width"] = width
        return tk.Button(parent, text=text, **kw)

    # ── Blinking cursor animation ──────────────────────────────────────────────

    def _blink(self):
        self._blink_on = not self._blink_on
        self.cursor_lbl.config(fg=C["fg"] if self._blink_on else C["hdr_bg"])
        self._blink_id = self.root.after(530, self._blink)

    # ── Estimates panel ────────────────────────────────────────────────────────

    def _build_estimates_panel(self):
        outer = self.estimates_outer

        sub = tk.Frame(outer, bg=C["bg"], padx=14, pady=8)
        sub.pack(fill="x")

        tk.Label(sub, text="▼ MODEL ESTIMATES",
                 font=(FONT, 10, "bold"), bg=C["bg"], fg=C["fg_dim"]).pack(side="left")
        self.audio_dur_label = tk.Label(sub, text="", bg=C["bg"],
                                         fg=C["fg_dim"], font=(FONT, 10))
        self.audio_dur_label.pack(side="left", padx=(10, 0))

        # Table border card
        border = tk.Frame(outer, bg=C["border"], padx=1, pady=1)
        border.pack(padx=14, pady=(0, 8), fill="x")

        tbl = tk.Frame(border, bg=C["bg_card"])
        tbl.pack(fill="x")

        # Header row
        col_specs = [
            ("MODEL",      10, C["fg"],    None),
            ("SPEED",      11, C["fg"],    None),
            ("ACCURACY",   10, C["fg"],    None),
            ("EST. TIME",  11, C["fg"],    None),
            ("FINISHES ~", 12, C["fg"],    None),
        ]
        for col, (label, w, fg, _) in enumerate(col_specs):
            tk.Label(tbl, text=label, bg=C["border"], fg=C["bg"],
                     font=(FONT, 9, "bold"), width=w, pady=5, anchor="center",
                     ).grid(row=0, column=col, padx=1, pady=(0, 1), sticky="nsew")

        # Data rows
        self._est_rows: dict = {}
        for r, model in enumerate(MODEL_ORDER, 1):
            info   = MODEL_INFO[model]
            row_bg = C["bg_dark"] if r % 2 == 0 else C["bg_card"]
            cells: dict = {}

            def _lbl(col, text, fg=C["fg"], width=None, bold=False, _bg=row_bg):
                f = (FONT, 10, "bold") if bold else (FONT, 10)
                w = col_specs[col][1]
                lbl = tk.Label(tbl, text=text, bg=_bg, fg=fg,
                               font=f, width=w, pady=5, anchor="center",
                               cursor="hand2")
                lbl.grid(row=r, column=col, padx=1, pady=1, sticky="nsew")
                return lbl

            cells["model"]    = _lbl(0, model,             fg=C["fg_hi"], bold=True)
            cells["speed"]    = _lbl(1, info["speed"])
            cells["accuracy"] = _lbl(2, info["accuracy"],  fg=info["acc_fg"], bold=True)
            cells["est_time"] = _lbl(3, "—")
            cells["finish"]   = _lbl(4, "—",               fg=C["yellow"])

            self._est_rows[model] = {"cells": cells, "alt_bg": row_bg}

            # Clicking any cell in the row selects that model.
            # Factory functions (_make_select, _make_hover) are used instead
            # of lambdas so that `m` is captured by value at definition time.
            # A plain lambda inside a loop would capture the loop variable by
            # reference and all rows would end up bound to the last model name.
            def _make_select(m):
                def _on_click(_e):
                    self.model_var.set(m)
                    self._refresh_estimates()
                return _on_click

            def _make_hover(m, enter):
                def _on_hover(_e):
                    if self.model_var.get() == m:
                        return          # already selected — don't flicker
                    bg = C["btn_bg"] if enter else self._est_rows[m]["alt_bg"]
                    for cell in self._est_rows[m]["cells"].values():
                        cell.config(bg=bg)
                return _on_hover

            click_cb      = _make_select(model)
            hover_in_cb   = _make_hover(model, enter=True)
            hover_out_cb  = _make_hover(model, enter=False)
            for cell in cells.values():
                cell.bind("<Button-1>",  click_cb)
                cell.bind("<Enter>",     hover_in_cb)
                cell.bind("<Leave>",     hover_out_cb)

    def _refresh_estimates(self):
        if self.total_audio_seconds <= 0:
            return
        total_s  = self.total_audio_seconds
        selected = self.model_var.get()

        self.audio_dur_label.config(
            text=f"·  TOTAL AUDIO: {fmt_dur(total_s)}"
        )
        for model in MODEL_ORDER:
            info    = MODEL_INFO[model]
            est_s   = info["load_s"] + total_s * info["rt_mult"]
            row     = self._est_rows[model]
            cells   = row["cells"]
            is_sel  = (model == selected)
            row_bg  = C["sel_bg"] if is_sel else row["alt_bg"]

            cells["est_time"].config(text=fmt_dur(est_s))
            cells["finish"].config(text=fmt_clock(est_s))

            # Highlight selected row
            for cell in cells.values():
                cell.config(bg=row_bg)
            if is_sel:
                cells["model"].config(fg=C["fg"], text=f"► {model}")
                cells["speed"].config(fg=C["fg"])
                cells["est_time"].config(fg=C["fg"])
                cells["finish"].config(fg=C["fg"])
            else:
                cells["model"].config(fg=C["fg_hi"], text=model)
                cells["speed"].config(fg=C["fg_dim"])
                cells["est_time"].config(fg=C["fg_dim"])
                cells["finish"].config(fg=C["amber"])

    # ── Progress panel ─────────────────────────────────────────────────────────

    def _build_progress_panel(self):
        pf = self.progress_outer

        top = tk.Frame(pf, bg=C["border"], padx=1, pady=1)
        top.pack(padx=14, pady=(8, 6), fill="x")

        inner = tk.Frame(top, bg=C["bg_card"], padx=10, pady=8)
        inner.pack(fill="x")

        tk.Label(inner, text="▼ PROGRESS",
                 font=(FONT, 10, "bold"), bg=C["bg_card"], fg=C["fg_dim"]).pack(anchor="w")

        self.pixel_bar = PixelBar(inner, height=28)
        self.pixel_bar.pack(fill="x", pady=(6, 6))

        info_row = tk.Frame(inner, bg=C["bg_card"])
        info_row.pack(fill="x")

        self.remaining_lbl = tk.Label(info_row, text="",
                                       font=(FONT, 11, "bold"),
                                       bg=C["bg_card"], fg=C["fg"])
        self.remaining_lbl.pack(side="left")

        self.finish_at_lbl = tk.Label(info_row, text="",
                                       font=(FONT, 11, "bold"),
                                       bg=C["bg_card"], fg=C["yellow"])
        self.finish_at_lbl.pack(side="right")

    # ── Progress ticking ───────────────────────────────────────────────────────

    def _start_progress_tick(self):
        self._tick_progress()

    def _tick_progress(self):
        if self.transcription_start is None:
            return
        elapsed   = time.time() - self.transcription_start
        est       = self.estimated_total_s if self.estimated_total_s > 0 else 1.0
        # Cap at 98 % so the bar never shows "done" before _on_done() fires.
        # The final jump to 100 % is handled explicitly in _on_done().
        pct       = min(98.0, (elapsed / est) * 100)
        remaining = max(0.0, est - elapsed)

        self.pixel_bar.set(pct)
        self.remaining_lbl.config(text=f"TIME LEFT: {fmt_dur(remaining)}")
        self.finish_at_lbl.config(text=f"DONE BY  {fmt_clock(remaining)}")

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
        label  = joined if len(joined) <= 54 else f"{len(files)} FILE(S) SELECTED"
        self.file_label.config(text=label.upper(), fg=C["fg"])

        # Reveal estimates table
        self.estimates_outer.pack(fill="x", before=self.btn_row)
        self.audio_dur_label.config(text="·  ANALYZING...")
        for row in self._est_rows.values():
            for k in ("est_time", "finish"):
                row["cells"][k].config(text="...")

        threading.Thread(target=self._analyze_files, daemon=True).start()

    def _analyze_files(self):
        total = 0.0
        failed = 0
        for f in self.selected_files:
            dur = get_audio_duration(f)
            if dur > 0:
                total += dur
            else:
                failed += 1
        if failed:
            self.q.put(("log", f"WARNING: Could not probe duration for {failed} file(s).\n"))
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
        Drain the cross-thread queue and dispatch messages to widget updates.

        Runs on the main thread every 40 ms via root.after().  Worker threads
        must NEVER touch widgets directly; they post messages here instead.
        Using get_nowait() + Empty rather than a blocking get() keeps the main
        loop responsive — we process everything available this tick, then yield.
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
            messagebox.showwarning(
                "NO FILES",
                "PLEASE CHOOSE AT LEAST ONE AUDIO FILE FIRST."
            )
            return

        if not PYTHON.exists():
            messagebox.showerror(
                "NOT INSTALLED",
                f"Python venv not found at:\n{PYTHON}\n\nRun  ./install  first.",
            )
            return

        model = self.model_var.get()
        info  = MODEL_INFO.get(model, MODEL_INFO["medium"])
        self.estimated_total_s = info["load_s"] + self.total_audio_seconds * info["rt_mult"]

        self.run_btn.config(state="disabled", text="[ ⏳  WORKING... ]",
                            bg=C["fg_dim"], fg=C["bg"])
        self.open_btn.pack_forget()
        self.out.config(state="normal")
        self.out.delete("1.0", "end")
        self.out.config(state="disabled")

        # Show progress panel
        self.progress_outer.pack(fill="x", before=self.btn_row)
        self.pixel_bar.set(0)
        self.remaining_lbl.config(text=f"TIME LEFT: {fmt_dur(self.estimated_total_s)}")
        self.finish_at_lbl.config(text=f"DONE BY  {fmt_clock(self.estimated_total_s)}")

        self.transcription_start = time.time()
        self._start_progress_tick()

        # Stage files into input_audio/.  Clear previous contents first so
        # transcribe.py always sees exactly the files chosen for this run —
        # leftover files from a prior run would otherwise be re-transcribed.
        INPUT_DIR.mkdir(exist_ok=True)
        for old in INPUT_DIR.iterdir():
            if old.is_file():
                old.unlink()
        for src in self.selected_files:
            src_path = Path(src)
            if src_path.exists():
                shutil.copy2(src_path, INPUT_DIR / src_path.name)
            else:
                self.q.put(("log", f"WARNING: File not found, skipping: {src_path.name}\n"))

        threading.Thread(
            target=self._worker,
            args=(model, self.lang_var.get()),
            daemon=True,
        ).start()

    def _worker(self, model: str, lang: str):
        cmd = [
            str(PYTHON),
            str(SCRIPT),
            "--model", model, "--language", lang, "--order", "name",
        ]
        # NO_COLOR=1 and TERM=dumb suppress Rich's ANSI colour sequences and
        # box-drawing characters so the console widget shows plain text.
        # stderr=STDOUT merges stderr into the single stdout pipe so error
        # messages from the child process appear in the GUI log too.
        env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb"}
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                cwd=str(PROJECT_DIR), env=env,
            )
            for line in self._proc.stdout:
                self.q.put(("log", strip_ansi(line)))
            self._proc.wait()
            if self._proc.returncode == 0:
                self.q.put(("log", "\n>>> TRANSCRIPTION COMPLETE <<<\n"))
                self.q.put(("done", True))
            else:
                self.q.put(("log", f"\n!!! PROCESS EXITED WITH CODE {self._proc.returncode} !!!\n"))
                self.q.put(("done", False))
        except Exception as exc:
            self.q.put(("log", f"\n!!! ERROR: {exc} !!!\n"))
            self.q.put(("done", False))
        finally:
            self._proc = None

    def _on_done(self, success: bool):
        self._stop_progress_tick()
        self.transcription_start = None

        self.pixel_bar.set(100 if success else 0)
        if success:
            self.remaining_lbl.config(text="STATUS: COMPLETE ✓", fg=C["fg"])
            self.finish_at_lbl.config(
                text=f"FINISHED AT {fmt_clock(0)}",
                fg=C["fg"]
            )
        else:
            self.remaining_lbl.config(text="STATUS: FAILED  ✗", fg=C["red"])
            self.finish_at_lbl.config(text="", fg=C["yellow"])

        self.run_btn.config(state="normal", text="[ ▶  TRANSCRIBE ]",
                            bg=C["btn_bg"], fg=C["fg"])
        if success:
            self.open_btn.pack(pady=(0, 14))

    def _open_result(self):
        if OUTPUT_FILE.exists():
            subprocess.run(["open", str(OUTPUT_FILE)])
        else:
            messagebox.showerror(
                "FILE NOT FOUND",
                f"OUTPUT FILE NOT FOUND:\n{OUTPUT_FILE}\n\nCHECK THE CONSOLE LOG ABOVE.",
            )


def main():
    root = tk.Tk()
    TranscriberApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
