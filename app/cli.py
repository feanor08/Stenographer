#!/usr/bin/env python3
"""
stenograph — local audio transcription

Usage
-----
  stenograph <file> [<file> ...]
  stenograph -m large-v3 -f srt meeting.m4a lecture.wav
  stenograph --language hi --output-dir ~/transcripts podcast.mp3

Files are transcribed in the order given.  Output is written next to each
source file (or into --output-dir) with a _transcribed_<timestamp> suffix.
"""
import logging
import time
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from shared import AUDIO_EXTS, MODEL_ORDER, fmt_dur, fmt_timestamp
from transcribe import (
    OUTPUT_FORMATS,
    _compute_eta,
    build_output_path,
    check_ffmpeg,
    choose_model_menu,
    ensure_local_diarizer,
    get_audio_duration_seconds,
    get_total_audio_duration,
    is_model_cached,
    iter_transcribe_segments,
    load_model_with_progress,
    render_transcript,
    write_output_text,
)

# ── Logging ────────────────────────────────────────────────────────────────────
_LOG_DIR  = Path.home() / "Library" / "Logs" / "Stenographer"
_LOG_FILE = _LOG_DIR / "stenographer-cli.log"
try:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.WARNING,
        handlers=[logging.FileHandler(_LOG_FILE, encoding="utf-8")],
    )
except Exception:
    pass

console = Console()
cli     = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Transcribe audio files locally using Whisper.",
)

_MODELS = MODEL_ORDER


def _ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


@cli.command()
def main(
    files: List[Path] = typer.Argument(
        ...,
        help="Audio files to transcribe (mp3, wav, m4a, flac, ogg, aac, wma, mp4, mkv).",
        metavar="<file>",
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m",
        help=f"Whisper model: {', '.join(_MODELS)}. Omit for interactive menu.",
        show_default=False,
    ),
    language: str = typer.Option(
        "auto", "--language", "-l",
        help="Language code (en, hi, fr …) or 'auto' for detection.",
    ),
    fmt: str = typer.Option(
        "txt", "--format", "-f",
        help="Output format: txt, srt, vtt.",
    ),
    output_dir: Optional[Path] = typer.Option(
        None, "--output-dir", "-o",
        help="Directory for output files. Default: same folder as each input file.",
    ),
    task: str = typer.Option(
        "transcribe", "--task",
        help="'transcribe' or 'translate' (translate → English).",
    ),
    diarize: bool = typer.Option(
        False, "--diarize", "-d",
        help="Label speakers in the output (requires simple-diarizer).",
    ),
    device: str = typer.Option(
        "cpu", "--device",
        help="Inference device: cpu or cuda.",
    ),
    compute_type: str = typer.Option(
        "int8", "--compute-type",
        help="Compute precision: int8, float16, float32.",
    ),
) -> None:
    # ── Validate inputs ────────────────────────────────────────────────────────
    if model is not None and model not in _MODELS:
        console.print(f"[red]Unknown model '{model}'. Choose from: {', '.join(_MODELS)}[/red]")
        raise typer.Exit(1)
    if fmt not in OUTPUT_FORMATS:
        console.print("[red]--format must be one of: txt, srt, vtt[/red]")
        raise typer.Exit(1)
    if task not in {"transcribe", "translate"}:
        console.print("[red]--task must be one of: transcribe, translate[/red]")
        raise typer.Exit(1)

    if not check_ffmpeg():
        console.print(
            "[yellow]⚠  FFmpeg not found.[/yellow]\n"
            "   Install with:  [bold]brew install ffmpeg[/bold]"
        )
        raise typer.Exit(1)

    # ── Resolve audio files ────────────────────────────────────────────────────
    audio_files: List[Path] = []
    skipped: List[str] = []
    for p in files:
        rp = p.resolve()
        if not rp.exists():
            console.print(f"[yellow]  Skipping (not found):[/yellow] {p}")
            skipped.append(str(p))
            continue
        if rp.suffix.lower() not in AUDIO_EXTS:
            console.print(f"[yellow]  Skipping (unsupported format):[/yellow] {p.name}")
            skipped.append(str(p))
            continue
        audio_files.append(rp)

    if not audio_files:
        console.print("[red]No valid audio files provided.[/red]")
        console.print(f"Supported: {', '.join(sorted(AUDIO_EXTS))}")
        raise typer.Exit(1)

    # ── Output directory ───────────────────────────────────────────────────────
    out_dir: Optional[Path] = None
    if output_dir:
        out_dir = output_dir.resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

    # ── Duration + model selection ─────────────────────────────────────────────
    total_secs = get_total_audio_duration(audio_files)
    selected   = model or choose_model_menu(
        audio_seconds=total_secs, default_model="medium", timeout_seconds=30
    )

    # ── Load model ─────────────────────────────────────────────────────────────
    cached = is_model_cached(selected)
    if not cached:
        console.print(f"[dim]Downloading model [bold]{selected}[/bold] (first use)…[/dim]")
    model_obj          = load_model_with_progress(selected, device=device, compute_type=compute_type, task=task)
    diarizer           = ensure_local_diarizer(device=device) if diarize else None

    # ── Transcribe ─────────────────────────────────────────────────────────────
    run_ts             = _ts()
    run_start          = time.time()
    transcription_start = run_start
    overall_total      = total_secs if total_secs > 0 else float(len(audio_files))
    overall_done       = 0.0
    failures           = 0
    outputs: List[Path] = []

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
        overall_task = pbar.add_task("Transcribing", total=overall_total, eta="estimating…")
        file_task    = pbar.add_task("Waiting…", total=1.0, completed=0.0, eta="--")

        for idx, audio in enumerate(audio_files, 1):
            audio_dur  = get_audio_duration_seconds(audio)
            file_total = audio_dur if audio_dur > 0 else 1.0
            file_done  = 0.0

            pbar.update(overall_task, description=f"[{idx}/{len(audio_files)}] {audio.name}")
            pbar.update(file_task, description=audio.name, total=file_total, completed=0.0, eta="estimating…")

            try:
                segments = []

                def _on_lang(code: str, prob: float) -> None:
                    pbar.print(f"  [dim]Detected language: {code} ({prob*100:.0f}%)[/dim]")

                for seg in iter_transcribe_segments(
                    model_obj, audio,
                    language=None if language == "auto" else language,
                    task=task,
                    on_language_detected=_on_lang,
                ):
                    if not str(seg.get("text", "")).strip():
                        continue
                    segments.append(seg)

                    if audio_dur > 0:
                        new_done = min(float(seg.get("end", 0.0)), audio_dur)
                        delta    = max(0.0, new_done - file_done)
                        if delta > 0:
                            file_done    = new_done
                            overall_done = min(overall_total, overall_done + delta)

                    elapsed  = time.time() - transcription_start
                    pbar.update(overall_task, completed=overall_done,
                                eta=_compute_eta(overall_done, overall_total, elapsed))
                    pbar.update(file_task, completed=file_done,
                                eta=fmt_dur(max(0.0, audio_dur - file_done)) if audio_dur > 0 else "…")

                # Snap to 100 %
                if audio_dur > 0:
                    overall_done = min(overall_total, overall_done + max(0.0, audio_dur - file_done))
                else:
                    overall_done = min(overall_total, overall_done + 1.0)

                pbar.update(overall_task, completed=overall_done,
                            eta=_compute_eta(overall_done, overall_total, time.time() - transcription_start))
                pbar.update(file_task, completed=file_total, eta="0S")

                text = render_transcript(
                    segments,
                    fmt=fmt,
                    diarizer=diarizer,
                    audio_path=audio,
                )

                # Write output
                dest_dir = out_dir or audio.parent
                out_path = build_output_path(audio, dest_dir, run_ts, fmt)
                write_output_text(out_path, (text or "[No speech detected]") + "\n")
                outputs.append(out_path)
                pbar.print(f"  [green]✓[/green] {out_path}")

            except Exception as exc:
                failures += 1
                pbar.print(f"  [red]✗ {audio.name}:[/red] {exc}")
                logging.exception("Failed: %s", audio)
                overall_done = min(overall_total, overall_done + (audio_dur if audio_dur > 0 else 1.0))
                pbar.update(overall_task, completed=overall_done, eta="—")
                pbar.update(file_task, completed=file_total, eta="0S")

        pbar.update(file_task, description="Done")

    # ── Summary ────────────────────────────────────────────────────────────────
    run_end = time.time()
    console.print()
    console.print(f"[bold]Total time:[/bold]  {fmt_dur(run_end - run_start)}")
    if failures:
        console.print(f"[yellow]Completed with {failures} failure(s).[/yellow]")
        raise typer.Exit(1)


if __name__ == "__main__":
    cli()
