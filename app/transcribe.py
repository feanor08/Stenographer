#!/usr/bin/env python3
"""
transcribe.py — Audio transcription engine.

Accepts audio_inputs.zip or input_audio/ folder, sorts files, runs
faster-whisper, and writes all results to a single transcriptions.txt.
"""

import json
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import typer
from rich import box
from rich.console import Console
from rich.live import Live
from rich.markup import escape as rich_escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from shared import (
    AUDIO_EXTS,
    MODEL_INFO,
    MODEL_LOAD_MAX_S,
    MODEL_LOAD_MIN_S,
    MODEL_ORDER,
    fmt_dur,
    fmt_hms,
    fmt_timestamp,
)

# ── Backend ────────────────────────────────────────────────────────────────────
try:
    from faster_whisper import WhisperModel
except ImportError as _e:
    WhisperModel = None
    _FASTER_WHISPER_ERR = str(_e)
else:
    _FASTER_WHISPER_ERR = ""

# ── Constants ──────────────────────────────────────────────────────────────────
MODEL_LOAD_STATS_FILE = Path(".model_load_times.json")
MAX_ZIP_BYTES         = 2 * 1024 * 1024 * 1024   # 2 GB guard against zip bombs
MAX_AUDIO_FILES       = 500                        # rglob file-count safety cap
MAX_SCAN_DEPTH        = 6                          # rglob depth safety cap

MODEL_CHOICES = [
    (name, MODEL_INFO[name]["speed"].title(), MODEL_INFO[name]["accuracy"])
    for name in MODEL_ORDER
]

CLOCK_FRAMES = ["🕛", "🕐", "🕑", "🕒", "🕓", "🕔", "🕕", "🕖", "🕗", "🕘", "🕙", "🕚"]

app     = typer.Typer(add_completion=False)
console = Console()


def log(msg: str) -> None:
    console.print(msg)


# ── File helpers ───────────────────────────────────────────────────────────────

def partial_output_path(output_path: Path) -> Path:
    """Return a sibling .part path for atomic writes."""
    return output_path.with_suffix(output_path.suffix + ".part")


def cleanup_interrupted_run_artifacts(
    zip_path: Path, extracted_dir: Path, output_path: Path
) -> None:
    part_path = partial_output_path(output_path)
    if part_path.exists():
        try:
            part_path.unlink()
            log(f"Removed stale partial output: {part_path}")
        except Exception as exc:
            log(f"⚠  Could not remove stale partial output {part_path}: {exc}")

    if zip_path.exists() and extracted_dir.exists():
        try:
            shutil.rmtree(extracted_dir)
            log(f"Cleaned previous extracted clips: {extracted_dir}")
        except Exception as exc:
            log(f"⚠  Could not clean extracted clips {extracted_dir}: {exc}")


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """
    Extract zip with a size guard against zip bombs.

    ZipFile.infolist() exposes uncompressed sizes without extracting, so we
    can reject maliciously crafted archives (e.g. 42.zip) before writing
    anything to disk.  MAX_ZIP_BYTES is set to 2 GB — well above any
    realistic batch of audio files but safely below typical disk free space.
    """
    log(f"Found ZIP: {zip_path}")
    with zipfile.ZipFile(zip_path, "r") as z:
        total_size = sum(info.file_size for info in z.infolist())
        if total_size > MAX_ZIP_BYTES:
            raise RuntimeError(
                f"ZIP uncompressed size ({total_size / 1e9:.1f} GB) exceeds the "
                f"{MAX_ZIP_BYTES / 1e9:.0f} GB safety limit."
            )
        dest_dir.mkdir(parents=True, exist_ok=True)
        z.extractall(dest_dir)
    log(f"Extracted to: {dest_dir}")


def collect_audio_files(root: Path, order: str = "ctime") -> List[Path]:
    """
    Collect audio files up to MAX_AUDIO_FILES, capped at MAX_SCAN_DEPTH.

    Both limits guard against adversarial or accidental inputs:
    - MAX_SCAN_DEPTH stops rglob from recursing into deeply nested archives
      or symlink loops that would spin forever.
    - MAX_AUDIO_FILES caps memory use and gives a predictable upper bound on
      how long a single run can take.
    ValueError in relative_to() can occur if rglob yields a path outside root
    (e.g. via a dangling symlink) — we skip those silently.
    """
    files: List[Path] = []
    for p in root.rglob("*"):
        try:
            depth = len(p.relative_to(root).parts)
        except ValueError:
            continue
        if depth > MAX_SCAN_DEPTH:
            continue
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            files.append(p)
            if len(files) >= MAX_AUDIO_FILES:
                log(f"⚠  Reached file limit ({MAX_AUDIO_FILES}). Additional files skipped.")
                break

    if order == "name":
        files.sort(key=lambda p: p.name.lower())
    else:
        files.sort(key=lambda p: p.stat().st_ctime)
    return files


# ── ffprobe ────────────────────────────────────────────────────────────────────

def get_audio_duration_seconds(audio_path: Path) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15,
        )
        return max(0.0, float(result.stdout.strip()))
    except Exception:
        return 0.0


def get_total_audio_duration(audio_files: List[Path]) -> float:
    return sum(get_audio_duration_seconds(p) for p in audio_files)


# ── Transcription ──────────────────────────────────────────────────────────────

def iter_transcribe_segments(
    model_bundle: Dict[str, object],
    audio_path: Path,
    language: Optional[str],
    task: str,
    beam_size: int = 5,
    vad: bool = True,
):
    model = model_bundle["model"]
    # Passing the literal string "auto" would cause faster-whisper to try to
    # load a language model named "auto" and raise a KeyError, so we normalise
    # it to None here (None = auto-detect).
    lang = None if (not language or language.lower() == "auto") else language

    if WhisperModel is None:
        raise RuntimeError(
            f"faster-whisper is not installed ({_FASTER_WHISPER_ERR}). "
            "Run: pip install faster-whisper"
        )
    segments, _ = model.transcribe(
        str(audio_path), language=lang, task=task,
        beam_size=beam_size, vad_filter=vad,
    )
    for seg in segments:
        text = str(seg.text).strip()
        if text:
            yield {
                "start": float(seg.start or 0.0),
                "end":   float(seg.end   or 0.0),
                "text":  text,
            }


def transcribe_file(
    model_bundle: Dict[str, object],
    audio_path: Path,
    language: Optional[str],
    task: str,
    beam_size: int = 5,
    vad: bool = True,
) -> List[Dict[str, object]]:
    return list(iter_transcribe_segments(
        model_bundle, audio_path=audio_path,
        language=language, task=task,
        beam_size=beam_size, vad=vad,
    ))


# ── Diarization ────────────────────────────────────────────────────────────────

def overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def ensure_local_diarizer(device: str = "cpu"):
    try:
        from simple_diarizer.diarizer import Diarizer
    except ImportError as e:
        raise RuntimeError(
            "Diarization requires simple-diarizer. Install: pip install simple-diarizer"
        ) from e
    return Diarizer(embed_model="ecapa", cluster_method="sc")


def diarize_audio_local(
    diarizer, audio_path: Path, num_speakers: Optional[int] = None
) -> List[Dict[str, object]]:
    diarization = diarizer.diarize(str(audio_path), num_speakers=num_speakers)
    turns: List[Dict[str, object]] = []
    for turn in diarization:
        turns.append({
            "start":   float(turn.get("start", 0.0)),
            "end":     float(turn.get("end",   0.0)),
            "speaker": str(turn.get("label", turn.get("speaker", "unknown"))),
        })
    return turns


def format_plain_segments(segments: List[Dict[str, object]]) -> str:
    return "\n".join(str(s["text"]) for s in segments if s.get("text")).strip()


def format_diarized_segments(
    segments: List[Dict[str, object]],
    speaker_turns: List[Dict[str, object]],
) -> str:
    if not segments:
        return ""
    speaker_map: Dict[str, str] = {}
    next_person = 1
    lines: List[str] = []
    for seg in segments:
        seg_start = float(seg.get("start", 0.0))
        seg_end   = float(seg.get("end",   seg_start))
        seg_text  = str(seg.get("text",  "")).strip()
        if not seg_text:
            continue
        best_speaker, best_overlap = "unknown", 0.0
        for turn in speaker_turns:
            ov = overlap_seconds(
                seg_start, seg_end,
                float(turn.get("start", 0.0)), float(turn.get("end", 0.0)),
            )
            if ov > best_overlap:
                best_overlap = ov
                best_speaker = str(turn.get("speaker", "unknown"))
        if best_speaker not in speaker_map:
            speaker_map[best_speaker] = f"Person {next_person}"
            next_person += 1
        lines.append(
            f"[{fmt_hms(seg_start)} - {fmt_hms(seg_end)}] "
            f"{speaker_map[best_speaker]}: {seg_text}"
        )
    return "\n".join(lines).strip()


# ── Model loading ──────────────────────────────────────────────────────────────

def ensure_model(
    model_name: str, device: str, compute_type: str, task: str
) -> Dict[str, object]:
    if WhisperModel is None:
        raise RuntimeError(
            f"faster-whisper is not installed ({_FASTER_WHISPER_ERR}). "
            "Run: pip install faster-whisper"
        )
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    return {"backend": "faster-whisper", "model": model}


def default_model_load_estimate(model_name: str) -> float:
    return float(MODEL_INFO.get(model_name, {}).get("load_s", 120))


def get_hf_cache_dir() -> Path:
    """
    Resolve the HuggingFace model cache directory using the same precedence
    order as the huggingface_hub library itself:
      1. HF_HUB_CACHE  — explicit override for the hub subdirectory
      2. HF_HOME       — override for the whole HF home; hub lives under it
      3. ~/.cache/huggingface/hub  — default on all platforms
    We replicate this logic rather than importing huggingface_hub to avoid
    pulling in the dependency just for a cache-existence check.
    """
    val = os.environ.get("HF_HUB_CACHE")
    if val:
        return Path(val)
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def is_model_cached(model_name: str) -> bool:
    """
    Check whether a model is already on disk without triggering a download.

    HuggingFace Hub stores repos as:
      <cache_dir>/models--<org>--<name>/snapshots/<hash>/
    We check for a non-empty snapshots/ directory rather than specific files
    because the internal layout can change between huggingface_hub versions.
    Two candidate repos are checked: faster-whisper (Systran) and the original
    openai weights, since either may be present depending on prior usage.
    """
    cache_dir = get_hf_cache_dir()
    candidates = [
        cache_dir / f"models--Systran--faster-whisper-{model_name}",
        cache_dir / f"models--openai--whisper-{model_name}",
    ]
    for repo_dir in candidates:
        snapshots = repo_dir / "snapshots"
        if snapshots.exists():
            try:
                if any(snapshots.iterdir()):
                    return True
            except OSError:
                pass
    return False


# ── Model stats (file-locked) ──────────────────────────────────────────────────

def _flock(f, exclusive: bool) -> None:
    """
    Best-effort file lock (POSIX only; no-op on Windows).

    ImportError  — fcntl doesn't exist on Windows; silently skip.
    OSError      — file system doesn't support locking (e.g. NFS, some
                   network shares); silently skip rather than crash.
    In both fallback cases the stats file is still written; the worst
    outcome is a slightly corrupted JSON if two processes race, which is
    recoverable because load_model_stats() returns {} on parse failure.
    """
    try:
        import fcntl
        fcntl.flock(f, fcntl.LOCK_EX if exclusive else fcntl.LOCK_UN)
    except (ImportError, OSError):
        pass


def load_model_stats() -> dict:
    if not MODEL_LOAD_STATS_FILE.exists():
        return {}
    try:
        with open(MODEL_LOAD_STATS_FILE, "r", encoding="utf-8") as f:
            _flock(f, exclusive=False)
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_model_stats(stats: dict) -> None:
    """
    Write model load-time stats atomically.

    Write to a sibling .tmp file first, then rename into place.
    On POSIX, os.rename / Path.replace is atomic when both paths are on
    the same filesystem, so a reader can never see a half-written JSON.
    The outer try/except makes stats loss non-fatal — a missing or corrupt
    stats file just falls back to the hard-coded defaults in MODEL_INFO.
    """
    try:
        tmp = MODEL_LOAD_STATS_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            _flock(f, exclusive=True)
            try:
                json.dump(stats, f, indent=2, sort_keys=True)
            finally:
                _flock(f, exclusive=False)
        tmp.replace(MODEL_LOAD_STATS_FILE)  # atomic on POSIX
    except Exception:
        pass


def get_model_load_estimate(model_name: str, device: str, compute_type: str) -> float:
    key   = f"{model_name}|{device}|{compute_type}"
    stats = load_model_stats()
    value = stats.get(key)
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return default_model_load_estimate(model_name)


def record_model_load_time(
    model_name: str, device: str, compute_type: str, elapsed: float
) -> None:
    """
    Update the persisted load-time estimate using exponential smoothing.

    Formula: new = 0.7 * prev + 0.3 * measured
    The 0.7/0.3 weights bias toward the historical average so that a single
    unusually slow run (e.g. cold disk cache, background indexing) doesn't
    over-inflate future estimates.  Both the raw measurement and the smoothed
    result are clamped to [MODEL_LOAD_MIN_S, MODEL_LOAD_MAX_S] to discard
    bogus values from system hibernation or extremely loaded machines.
    """
    elapsed = min(max(elapsed, MODEL_LOAD_MIN_S), MODEL_LOAD_MAX_S)
    key   = f"{model_name}|{device}|{compute_type}"
    stats = load_model_stats()
    prev  = stats.get(key)
    if isinstance(prev, (int, float)) and prev > 0:
        smoothed = (0.7 * float(prev)) + (0.3 * elapsed)
        stats[key] = round(min(max(smoothed, MODEL_LOAD_MIN_S), MODEL_LOAD_MAX_S), 2)
    else:
        stats[key] = round(elapsed, 2)
    save_model_stats(stats)


def load_model_with_progress(
    model_name: str, device: str, compute_type: str, task: str
) -> Dict[str, object]:
    """
    Load the Whisper model on a background thread while showing a progress bar.

    WhisperModel() can block for 10–240 seconds on first use (network download
    + disk write) or a few seconds on subsequent runs (disk read + ONNX
    compilation).  Running it on a thread lets Rich update the progress bar
    smoothly instead of freezing the terminal.

    The progress bar total is set to the historical load estimate and extended
    live if the model takes longer than expected (est += 10 s).  After the
    thread joins, the bar is snapped to 100 % so it always completes cleanly.
    """
    est_total = min(
        max(get_model_load_estimate(model_name, device, compute_type), MODEL_LOAD_MIN_S),
        MODEL_LOAD_MAX_S,
    )
    result: dict = {}
    error:  dict = {}

    def _loader() -> None:
        try:
            result["model"] = ensure_model(
                model_name, device=device, compute_type=compute_type, task=task
            )
        except Exception as e:
            error["err"] = e

    start = time.time()
    t = threading.Thread(target=_loader, daemon=True)
    t.start()

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("ETA"),
        TimeRemainingColumn(compact=True),
        TextColumn("Elapsed"),
        TimeElapsedColumn(),
        transient=False,
        console=console,
    ) as pbar:
        task_id = pbar.add_task(
            f"Loading model ({rich_escape(model_name)})", total=est_total
        )
        while t.is_alive():
            elapsed     = time.time() - start
            current_max = pbar.tasks[task_id].total or est_total
            if elapsed >= current_max:
                pbar.update(task_id, total=elapsed + 10.0)
            pbar.update(task_id, completed=min(elapsed, pbar.tasks[task_id].total or elapsed))
            time.sleep(0.2)

        t.join(timeout=5.0)
        elapsed    = time.time() - start
        final_total = max(pbar.tasks[task_id].total or 1.0, elapsed, 1.0)
        pbar.update(task_id, total=final_total, completed=final_total)

    if "err" in error:
        raise error["err"]

    record_model_load_time(model_name, device, compute_type, elapsed)
    return result["model"]


# ── Interactive model menu ─────────────────────────────────────────────────────

def choose_model_menu(
    audio_seconds: float, default_model: str = "medium", timeout_seconds: int = 30
) -> str:
    console.print(Panel.fit(
        "[bold cyan]Whisper Model Selection[/bold cyan]\nChoose the model for this run.",
        border_style="cyan",
    ))

    table = Table(box=box.ROUNDED, header_style="bold magenta")
    table.add_column("No.",          justify="right", style="bold")
    table.add_column("Model",        style="bold green")
    table.add_column("Cached",       style="green")
    table.add_column("Speed",        style="yellow")
    table.add_column("Accuracy",     style="cyan")
    table.add_column("Est. runtime", style="bold blue")

    for idx, (name, speed, acc) in enumerate(MODEL_CHOICES, 1):
        marker      = " (default)" if name == default_model else ""
        cached      = "[green]Ready[/green]" if is_model_cached(name) else "[yellow]Download needed[/yellow]"
        rt          = MODEL_INFO.get(name, {}).get("rt_mult", 1.6)
        est_runtime = fmt_dur(audio_seconds * rt)
        table.add_row(str(idx), f"{name}{marker}", cached, speed, acc, est_runtime)

    console.print(table)
    console.print(f"[dim]Total input audio: {fmt_dur(audio_seconds)}[/dim]")

    choices       = [str(i) for i in range(1, len(MODEL_CHOICES) + 1)]
    default_index = str(next(
        (i for i, c in enumerate(MODEL_CHOICES, 1) if c[0] == default_model),
        len(MODEL_CHOICES),
    ))
    console.print(
        f"[bold]Select model number ({'/'.join(choices)})[/bold] "
        f"[dim]- auto-selecting {default_model} in {timeout_seconds}s[/dim]"
    )

    if not sys.stdin.isatty():
        console.print(f"[yellow]No interactive input detected. Using {default_model}.[/yellow]")
        return default_model

    deadline  = time.time() + timeout_seconds
    frame_idx = 0
    typed     = ""

    if os.name == "posix":
        import select as _select
        import termios
        import tty

        fd           = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            with Live(console=console, refresh_per_second=8, transient=True) as live:
                while True:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break
                    shown      = max(0, int(math.ceil(remaining)))
                    frame      = CLOCK_FRAMES[frame_idx % len(CLOCK_FRAMES)]
                    typed_text = typed or "_"
                    live.update(Panel.fit(
                        f"[bold cyan]{frame} Auto-selecting {default_model} in {shown:02d}s[/bold cyan]\n"
                        f"[dim]Press number key ({','.join(choices)}) to choose. Enter = default.[/dim]\n"
                        f"[white]Your input: [bold]{typed_text}[/bold][/white]",
                        border_style="cyan",
                    ))
                    ready, _, _ = _select.select([sys.stdin], [], [], min(0.25, remaining))
                    if ready:
                        ch = sys.stdin.read(1)
                        if ch in ("\n", "\r"):
                            if typed in choices:
                                return MODEL_CHOICES[int(typed) - 1][0]
                            return MODEL_CHOICES[int(default_index) - 1][0]
                        if ch in ("\x7f", "\b"):
                            typed = typed[:-1]
                            continue
                        if ch.isdigit():
                            typed = ch
                            if typed in choices:
                                return MODEL_CHOICES[int(typed) - 1][0]
                    frame_idx += 1
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    else:
        input_queue: queue.Queue = queue.Queue()

        def _reader() -> None:
            try:
                input_queue.put(sys.stdin.readline().strip())
            except Exception:
                input_queue.put("")

        threading.Thread(target=_reader, daemon=True).start()
        with Live(console=console, refresh_per_second=8, transient=True) as live:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                shown = max(0, int(math.ceil(remaining)))
                frame = CLOCK_FRAMES[frame_idx % len(CLOCK_FRAMES)]
                live.update(Panel.fit(
                    f"[bold cyan]{frame} Auto-selecting {default_model} in {shown:02d}s[/bold cyan]\n"
                    f"[dim]Type {','.join(choices)} then Enter to choose manually[/dim]",
                    border_style="cyan",
                ))
                try:
                    raw = input_queue.get(timeout=min(0.25, remaining))
                    if raw in choices:
                        return MODEL_CHOICES[int(raw) - 1][0]
                    return MODEL_CHOICES[int(default_index) - 1][0]
                except queue.Empty:
                    pass
                frame_idx += 1

    console.print(f"[yellow]No response. Auto-selected {default_model}.[/yellow]")
    return default_model


# ── ETA helper (deduplicated) ──────────────────────────────────────────────────

def _compute_eta(done: float, total: float, elapsed: float) -> str:
    """
    Estimate time remaining based on observed throughput so far.

    Returns "estimating..." until both `done` and `elapsed` are positive —
    i.e. at least one segment has been processed — to avoid a divide-by-zero
    or a misleading ETA on the very first tick.  The rate check (rate > 0)
    is a second guard for the degenerate case where done > 0 but elapsed
    rounds to zero on a fast machine.
    """
    if done > 0 and elapsed > 0:
        rate      = done / elapsed
        remaining = max(0.0, total - done)
        return fmt_dur(remaining / rate) if rate > 0 else "estimating..."
    return "estimating..."


# ── CLI entry point ────────────────────────────────────────────────────────────

@app.command()
def main(
    zip_path:     Path                = typer.Option("audio_inputs.zip",  "--zip",          help="ZIP file containing audio clips."),
    folder_path:  Path                = typer.Option("input_audio",       "--folder",       help="Folder with audio files."),
    extracted_dir:Path                = typer.Option("clips",             "--extracted",    help="Where to extract/process audio."),
    output_path:  Path                = typer.Option("transcriptions.txt","--output",       help="Output file (folder/zip mode only)."),
    order:        str                 = typer.Option("ctime",             "--order",        help="Sort files by 'ctime' or 'name'."),
    model:        Optional[str]       = typer.Option(None,                "--model",        help="Whisper model size (skips interactive menu)."),
    language:     str                 = typer.Option("auto",              "--language",     help="Language code or 'auto'."),
    task:         str                 = typer.Option("transcribe",        "--task",         help="'transcribe' or 'translate'."),
    diarize:      bool                = typer.Option(False,               "--diarize",      help="Enable speaker labeling."),
    num_speakers: Optional[int]       = typer.Option(None,                "--num-speakers", help="Known speaker count for diarization."),
    device:       str                 = typer.Option("cpu",               "--device",       help="Device: cpu or cuda."),
    compute_type: str                 = typer.Option("int8",              "--compute-type", help="Compute type: int8|float16|float32."),
    files:        Optional[List[Path]]= typer.Option(None,                "--files",        help="Individual audio files; output goes next to each source file."),
) -> None:

    run_start = time.time()
    run_ts    = time.strftime("%Y%m%d_%H%M%S", time.localtime(run_start))

    # ── Input validation ───────────────────────────────────────────────────────
    if order not in {"ctime", "name"}:
        raise typer.BadParameter("--order must be one of: ctime, name")
    if task not in {"transcribe", "translate"}:
        raise typer.BadParameter("--task must be one of: transcribe, translate")
    valid_models = {c[0] for c in MODEL_CHOICES}
    if model is not None and model not in valid_models:
        raise typer.BadParameter(f"--model must be one of: {', '.join(sorted(valid_models))}")
    if num_speakers is not None and num_speakers < 1:
        raise typer.BadParameter("--num-speakers must be a positive integer")

    if not check_ffmpeg():
        log("⚠️  FFmpeg not found. Install: brew install ffmpeg (macOS) | apt install ffmpeg (Linux)")
        raise typer.Exit(code=1)

    # ── Locate input ───────────────────────────────────────────────────────────
    per_file_mode = bool(files)

    if per_file_mode:
        audio_files = [
            p.resolve() for p in files
            if p.exists() and p.suffix.lower() in AUDIO_EXTS
        ]
        if not audio_files:
            log("No valid audio files in --files list.")
            raise typer.Exit(code=1)
    else:
        cleanup_interrupted_run_artifacts(
            zip_path=zip_path, extracted_dir=extracted_dir, output_path=output_path
        )
        if zip_path.exists():
            extract_zip(zip_path, extracted_dir)
            input_root = extracted_dir
        elif folder_path.exists():
            input_root = folder_path
            log(f"Using audio folder: {folder_path}")
        else:
            log("No inputs found. Place audio files in 'input_audio/' or provide 'audio_inputs.zip'.")
            raise typer.Exit(code=1)
        audio_files = collect_audio_files(input_root, order=order)
        if not audio_files:
            log("No audio files found. Supported: " + ", ".join(sorted(AUDIO_EXTS)))
            raise typer.Exit(code=1)

    total_audio_seconds = get_total_audio_duration(audio_files)
    selected_model      = model or choose_model_menu(
        audio_seconds=total_audio_seconds, default_model="medium", timeout_seconds=30
    )

    log("Processing order:")
    for i, p in enumerate(audio_files, 1):
        try:
            ctime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_ctime))
        except Exception:
            ctime = "n/a"
        log(f"  {i:02d}. {p.name}  (ctime: {ctime})")

    # ── Load model ─────────────────────────────────────────────────────────────
    log(f"Preparing model: {selected_model} | device={device} | compute={compute_type}")
    model_obj = load_model_with_progress(
        selected_model, device=device, compute_type=compute_type, task=task
    )
    diarization_pipeline = None
    if diarize:
        log("Preparing speaker diarization pipeline...")
        diarization_pipeline = ensure_local_diarizer(device=device)

    # ── Transcribe ─────────────────────────────────────────────────────────────
    output_lines: List[str] = []  # used only in folder/zip mode
    failures              = 0
    transcription_start   = time.time()
    overall_total         = total_audio_seconds if total_audio_seconds > 0 else float(len(audio_files))
    overall_done          = 0.0

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold green]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("{task.completed:.0f}/{task.total:.0f}s"),
        TextColumn("ETA: {task.fields[eta]}"),
        TimeElapsedColumn(),
        transient=False,
        console=console,
    ) as pbar:
        overall_task = pbar.add_task("Transcribing", total=overall_total, eta="estimating...")
        file_task    = pbar.add_task("Current file: waiting...", total=1.0, completed=0.0, eta="--:--")

        for audio in audio_files:
            audio_dur       = get_audio_duration_seconds(audio)
            file_total      = audio_dur if audio_dur > 0 else 1.0
            file_done       = 0.0
            safe_name       = rich_escape(audio.name)

            pbar.update(overall_task, description=f"Transcribing: {safe_name}")
            pbar.update(file_task, description=f"File: {safe_name}",
                        total=file_total, completed=0.0, eta="estimating...")

            try:
                segments: List[Dict[str, object]] = []
                empty_count = 0

                for seg in iter_transcribe_segments(
                    model_obj, audio, language=language, task=task
                ):
                    if not str(seg.get("text", "")).strip():
                        empty_count += 1
                        continue
                    segments.append(seg)

                    if audio_dur > 0:
                        new_done = min(float(seg.get("end", 0.0)), audio_dur)
                        delta    = max(0.0, new_done - file_done)
                        if delta > 0:
                            file_done    = new_done
                            overall_done = min(overall_total, overall_done + delta)

                    elapsed  = time.time() - transcription_start
                    eta_text = _compute_eta(overall_done, overall_total, elapsed)
                    pbar.update(overall_task, completed=overall_done, eta=eta_text)
                    pbar.update(
                        file_task, completed=file_done,
                        eta=fmt_dur(max(0.0, audio_dur - file_done)) if audio_dur > 0 else "estimating...",
                    )

                if empty_count:
                    log(f"  [dim]({audio.name}: {empty_count} empty segment(s) skipped)[/dim]")

                # Ensure file reaches 100 %
                if audio_dur > 0 and file_done < audio_dur:
                    overall_done = min(overall_total, overall_done + (audio_dur - file_done))
                elif audio_dur <= 0:
                    overall_done = min(overall_total, overall_done + 1.0)

                elapsed  = time.time() - transcription_start
                eta_text = _compute_eta(overall_done, overall_total, elapsed)
                pbar.update(overall_task, completed=overall_done, eta=eta_text)
                pbar.update(file_task, completed=file_total, eta="00:00S")

                if diarization_pipeline is not None:
                    speaker_turns = diarize_audio_local(
                        diarization_pipeline, audio, num_speakers=num_speakers
                    )
                    text = format_diarized_segments(segments, speaker_turns)
                else:
                    text = format_plain_segments(segments)

                if per_file_mode:
                    out_path = audio.parent / f"{audio.stem}_transcribed_{run_ts}.txt"
                    part     = out_path.with_suffix(".txt.part")
                    with open(part, "w", encoding="utf-8") as fh:
                        fh.write((text if text else "[No speech detected]") + "\n")
                        fh.flush()
                        os.fsync(fh.fileno())
                    part.replace(out_path)
                    print(f"OUTPUT:{out_path}", flush=True)
                else:
                    output_lines.append(
                        f"### {audio.name}\n{text if text else '[No speech detected]'}\n"
                    )

            except Exception as e:
                failures += 1
                console.print(f"  ⚠️  Failed to transcribe {rich_escape(audio.name)}: {e}")
                if per_file_mode:
                    log(f"  (no output file written for {audio.name})")
                else:
                    output_lines.append(f"### {audio.name}\n[Error: {e}]\n")
                remaining_dur = audio_dur - file_done if audio_dur > 0 else 1.0
                overall_done  = min(overall_total, overall_done + remaining_dur)
                elapsed       = time.time() - transcription_start
                pbar.update(overall_task, completed=overall_done,
                            eta=_compute_eta(overall_done, overall_total, elapsed))
                pbar.update(file_task, completed=file_total, eta="00:00S")

        pbar.update(file_task, description="Current file: done")

    transcription_end = time.time()

    # ── Write output (folder/zip mode only — per-file mode writes inline) ──────
    if not per_file_mode:
        part_path = partial_output_path(output_path)
        with open(part_path, "w", encoding="utf-8") as f:
            f.write("\n".join(output_lines).strip() + "\n")
            f.flush()
            os.fsync(f.fileno())
        part_path.replace(output_path)
        log(f"Done. Wrote transcripts to: {output_path.resolve()}")
    else:
        log("Done.")
    run_end = time.time()
    log(f"Start time:         {fmt_timestamp(run_start)}")
    log(f"End time:           {fmt_timestamp(run_end)}")
    log(f"Total time:         {fmt_dur(run_end - run_start)}")
    log(f"Transcription time: {fmt_dur(transcription_end - transcription_start)}")
    if failures:
        log(f"Completed with {failures} failure(s). See above for details.")


if __name__ == "__main__":
    app()
