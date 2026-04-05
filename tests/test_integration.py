"""
Integration tests for the internal transcribe.py worker entry point.

Requirements:
  - ffmpeg installed and on PATH
  - app/venv set up (run install.command / install.bat first)
  - Internet connection on the first run (downloads the ~75 MB 'tiny' model)

Run just these:   pytest -m integration -v
Skip these:       pytest -m "not integration" -v   (default unit test run)
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).parent.parent / "app"
PYTHON  = (
    APP_DIR / "venv" / "Scripts" / "python.exe"
    if sys.platform == "win32"
    else APP_DIR / "venv" / "bin" / "python"
)
SCRIPT = APP_DIR / "transcribe.py"

_no_ffmpeg = shutil.which("ffmpeg") is None
_no_venv   = not PYTHON.exists()


def _silent_wav(path: Path, duration: int = 2) -> None:
    """Create a short silent WAV using ffmpeg."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
         "-t", str(duration), str(path)],
        check=True, capture_output=True,
    )


def _run(*files: Path, extra_args: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    cmd = [str(PYTHON), str(SCRIPT), "--model", "tiny"]
    for audio in files:
        cmd += ["--files", str(audio)]
    cmd += [*extra_args]
    return subprocess.run(
        cmd,
        capture_output=True, text=True, cwd=str(APP_DIR),
        env={**os.environ, "NO_COLOR": "1", "TERM": "dumb"},
        timeout=300,  # first run downloads the model — allow plenty of time
    )


@pytest.mark.integration
@pytest.mark.skipif(_no_ffmpeg, reason="ffmpeg not installed")
@pytest.mark.skipif(_no_venv,   reason="venv not set up — run install.command first")
class TestTranscribeWorkerCLI:

    # ── basic smoke ────────────────────────────────────────────────────────────

    def test_exits_zero(self, tmp_path):
        audio = tmp_path / "silence.wav"
        _silent_wav(audio)
        result = _run(audio)
        assert result.returncode == 0, result.stdout

    def test_emits_output_line(self, tmp_path):
        audio = tmp_path / "clip.wav"
        _silent_wav(audio)
        result = _run(audio)
        assert any(line.startswith("OUTPUT:") for line in result.stdout.splitlines())

    def test_no_failed_line_on_success(self, tmp_path):
        audio = tmp_path / "clip.wav"
        _silent_wav(audio)
        result = _run(audio)
        assert not any(line.startswith("FAILED:") for line in result.stdout.splitlines())

    # ── txt format ─────────────────────────────────────────────────────────────

    def test_creates_txt_file_next_to_audio(self, tmp_path):
        audio = tmp_path / "clip.wav"
        _silent_wav(audio)
        _run(audio)
        assert len(list(tmp_path.glob("clip_transcribed_*.txt"))) == 1

    def test_txt_output_not_empty(self, tmp_path):
        audio = tmp_path / "clip.wav"
        _silent_wav(audio)
        _run(audio)
        content = next(tmp_path.glob("clip_transcribed_*.txt")).read_text(encoding="utf-8")
        assert content.strip()

    def test_txt_no_extra_files_created(self, tmp_path):
        audio = tmp_path / "clip.wav"
        _silent_wav(audio)
        _run(audio)
        # Only the original WAV and the output TXT should exist
        files = list(tmp_path.iterdir())
        assert len(files) == 2

    # ── srt format ─────────────────────────────────────────────────────────────

    def test_creates_srt_file(self, tmp_path):
        audio = tmp_path / "clip.wav"
        _silent_wav(audio)
        _run(audio, extra_args=("--format", "srt"))
        assert len(list(tmp_path.glob("clip_transcribed_*.srt"))) == 1

    def test_srt_content_valid(self, tmp_path):
        audio = tmp_path / "clip.wav"
        _silent_wav(audio)
        _run(audio, extra_args=("--format", "srt"))
        content = next(tmp_path.glob("clip_transcribed_*.srt")).read_text(encoding="utf-8").strip()
        # Either has speech (SRT starts with "1") or is silent
        assert content.startswith("1") or "[No speech detected]" in content

    # ── vtt format ─────────────────────────────────────────────────────────────

    def test_creates_vtt_file(self, tmp_path):
        audio = tmp_path / "clip.wav"
        _silent_wav(audio)
        _run(audio, extra_args=("--format", "vtt"))
        assert len(list(tmp_path.glob("clip_transcribed_*.vtt"))) == 1

    def test_vtt_starts_with_webvtt(self, tmp_path):
        audio = tmp_path / "clip.wav"
        _silent_wav(audio)
        _run(audio, extra_args=("--format", "vtt"))
        content = next(tmp_path.glob("clip_transcribed_*.vtt")).read_text(encoding="utf-8")
        assert content.startswith("WEBVTT") or "[No speech detected]" in content

    def test_multiple_inputs_use_first_files_folder_without_collision(self, tmp_path):
        first_dir = tmp_path / "first"
        second_dir = tmp_path / "second"
        first_audio = first_dir / "clip.wav"
        second_audio = second_dir / "clip.wav"
        first_dir.mkdir()
        second_dir.mkdir()
        _silent_wav(first_audio)
        _silent_wav(second_audio)

        result = _run(first_audio, second_audio)

        assert result.returncode == 0, result.stdout
        first_outputs = sorted(first_dir.glob("clip_transcribed_*.txt"))
        second_outputs = sorted(second_dir.glob("clip_transcribed_*.txt"))
        assert len(first_outputs) == 2
        assert len(second_outputs) == 0
        assert first_outputs[0].name != first_outputs[1].name

    # ── error handling ─────────────────────────────────────────────────────────

    def test_invalid_format_exits_nonzero(self, tmp_path):
        audio = tmp_path / "clip.wav"
        _silent_wav(audio)
        result = _run(audio, extra_args=("--format", "docx"))
        assert result.returncode != 0

    def test_nonexistent_file_exits_nonzero(self, tmp_path):
        result = _run(tmp_path / "ghost.wav")
        assert result.returncode != 0
