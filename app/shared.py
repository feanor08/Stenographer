"""
shared.py — single source of truth for Audio Transcriber.

Imported by both one_click_ui.py and transcribe.py so that model
constants, audio extensions, and time-formatting helpers are never
duplicated or allowed to drift out of sync.
"""
from __future__ import annotations
from datetime import datetime, timedelta

# ── Audio file types ───────────────────────────────────────────────────────────
AUDIO_EXTS: frozenset[str] = frozenset({
    ".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wma", ".mp4", ".mkv"
})

# ── Model registry ─────────────────────────────────────────────────────────────
# rt_mult : approximate CPU int8 real-time multiplier
#           (processing seconds per second of audio on a modern laptop CPU)
# load_s  : approximate cold-start load time in seconds (first run after reboot;
#           subsequent runs are faster due to OS disk cache)
# acc_fg  : hex colour used to render the accuracy value in the GUI table —
#           red for poor models, graduating to bright yellow for the best
MODEL_ORDER: list[str] = ["tiny", "base", "small", "medium", "large-v3"]

MODEL_INFO: dict[str, dict] = {
    "tiny":     {"speed": "FASTEST",   "accuracy": "~60%", "acc_fg": "#CC0000", "rt_mult": 0.35, "load_s": 20},
    "base":     {"speed": "VERY FAST", "accuracy": "~70%", "acc_fg": "#FF0000", "rt_mult": 0.55, "load_s": 35},
    "small":    {"speed": "FAST",      "accuracy": "~80%", "acc_fg": "#B3A125", "rt_mult": 0.90, "load_s": 60},
    "medium":   {"speed": "BALANCED",  "accuracy": "~90%", "acc_fg": "#FFDE00", "rt_mult": 1.60, "load_s": 120},
    "large-v3": {"speed": "SLOWEST",   "accuracy": "~95%", "acc_fg": "#fff59d", "rt_mult": 2.80, "load_s": 240},
}

# Bounds applied to measured load times before and after EMA smoothing in
# record_model_load_time().  The floor (5 s) discards sub-second readings
# caused by timing the load() call when the model is already in memory.
# The ceiling (600 s) discards anomalous readings from hibernation or an
# extremely loaded machine that would permanently inflate future estimates.
MODEL_LOAD_MIN_S: float = 5.0
MODEL_LOAD_MAX_S: float = 600.0


# ── Time formatters ────────────────────────────────────────────────────────────

def fmt_dur(seconds: float) -> str:
    """Human-readable duration: 45S / 4M 30S / 1H 4M."""
    s = max(0, int(round(seconds)))
    if s < 60:
        return f"{s}S"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}M {s:02d}S"
    h, m = divmod(m, 60)
    return f"{h}H {m}M"


def fmt_hms(seconds: float) -> str:
    """HH:MM:SS — used for diarized segment timestamps."""
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_clock(seconds_from_now: float) -> str:
    """Wall-clock finish time, e.g. '2:05 PM'."""
    finish = datetime.now() + timedelta(seconds=max(0, seconds_from_now))
    hour = finish.hour % 12 or 12
    return f"{hour}:{finish.strftime('%M %p')}"


def fmt_timestamp(ts: float) -> str:
    """ISO-style datetime string for run logs."""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
