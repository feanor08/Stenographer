"""Tests for pure/filesystem helpers in transcribe.py."""
import shutil
import unittest.mock as mock
from pathlib import Path

import pytest

from transcribe import (
    build_output_path,
    partial_output_path,
    collect_audio_files,
    check_ffmpeg,
    format_srt,
    format_vtt,
    format_txt_timed,
    render_transcript,
    write_output_text,
    MAX_AUDIO_FILES,
    MAX_SCAN_DEPTH,
)


# ── partial_output_path ────────────────────────────────────────────────────────

class TestPartialOutputPath:
    def test_appends_part_extension(self):
        p = Path("/some/dir/output.txt")
        assert partial_output_path(p) == Path("/some/dir/output.txt.part")

    def test_preserves_stem(self):
        p = Path("/dir/my_file.txt")
        result = partial_output_path(p)
        assert result.name == "my_file.txt.part"

    def test_is_sibling(self):
        p = Path("/dir/out.txt")
        assert partial_output_path(p).parent == p.parent


class TestWriteOutputText:
    def test_writes_atomically_and_removes_part_file(self, tmp_path):
        out = tmp_path / "result.txt"
        write_output_text(out, "hello\n")

        assert out.read_text(encoding="utf-8") == "hello\n"
        assert not partial_output_path(out).exists()


class TestBuildOutputPath:
    def test_uses_requested_output_dir(self, tmp_path):
        audio = tmp_path / "nested" / "clip.wav"
        audio.parent.mkdir()
        audio.touch()
        out_dir = tmp_path / "chosen"
        out_dir.mkdir()

        result = build_output_path(audio, out_dir, "20260405_101010", "txt")

        assert result.parent == out_dir
        assert result.name == "clip_transcribed_20260405_101010.txt"

    def test_avoids_collisions_when_stems_repeat(self, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        used_paths = set()

        audio_a = tmp_path / "a" / "clip.wav"
        audio_b = tmp_path / "b" / "clip.wav"
        audio_a.parent.mkdir()
        audio_b.parent.mkdir()
        audio_a.touch()
        audio_b.touch()

        first = build_output_path(audio_a, out_dir, "20260405_101010", "txt", used_paths=used_paths)
        second = build_output_path(audio_b, out_dir, "20260405_101010", "txt", used_paths=used_paths)

        assert first.name == "clip_transcribed_20260405_101010.txt"
        assert second.name == "clip_transcribed_20260405_101010_2.txt"


# ── check_ffmpeg ───────────────────────────────────────────────────────────────

class TestCheckFfmpeg:
    def test_returns_true_when_ffmpeg_found(self):
        with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            assert check_ffmpeg() is True

    def test_returns_false_when_ffmpeg_missing(self):
        with (
            mock.patch("shutil.which", return_value=None),
            mock.patch("transcribe.os.path.isfile", return_value=False),
            mock.patch("transcribe.os.access", return_value=False),
        ):
            assert check_ffmpeg() is False


# ── collect_audio_files ────────────────────────────────────────────────────────

@pytest.fixture
def audio_dir(tmp_path):
    """A temp directory with a mix of audio and non-audio files."""
    (tmp_path / "track1.mp3").touch()
    (tmp_path / "track2.wav").touch()
    (tmp_path / "notes.txt").touch()
    (tmp_path / "image.png").touch()
    return tmp_path


class TestCollectAudioFiles:
    def test_returns_only_audio_files(self, audio_dir):
        files = collect_audio_files(audio_dir, order="name")
        names = {f.name for f in files}
        assert names == {"track1.mp3", "track2.wav"}

    def test_name_order(self, audio_dir):
        files = collect_audio_files(audio_dir, order="name")
        assert [f.name for f in files] == ["track1.mp3", "track2.wav"]

    def test_recurses_into_subdirectory(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.flac").touch()
        files = collect_audio_files(tmp_path, order="name")
        assert any(f.name == "deep.flac" for f in files)

    def test_ignores_files_beyond_max_depth(self, tmp_path):
        # Build a path deeper than MAX_SCAN_DEPTH
        deep = tmp_path
        for i in range(MAX_SCAN_DEPTH + 1):
            deep = deep / f"d{i}"
        deep.mkdir(parents=True)
        (deep / "deep.mp3").touch()

        files = collect_audio_files(tmp_path, order="name")
        assert not any(f.name == "deep.mp3" for f in files)

    def test_caps_at_max_audio_files(self, tmp_path):
        for i in range(MAX_AUDIO_FILES + 5):
            (tmp_path / f"track{i:04d}.mp3").touch()
        files = collect_audio_files(tmp_path)
        assert len(files) == MAX_AUDIO_FILES

    def test_empty_directory(self, tmp_path):
        assert collect_audio_files(tmp_path) == []

    def test_case_insensitive_extension(self, tmp_path):
        (tmp_path / "UPPER.MP3").touch()
        files = collect_audio_files(tmp_path)
        assert len(files) == 1


# ── format_srt ─────────────────────────────────────────────────────────────────

SEGS = [
    {"start": 0.0,  "end": 1.5,  "text": "Hello world"},
    {"start": 1.5,  "end": 3.25, "text": "Goodbye"},
    {"start": 3.25, "end": 4.0,  "text": "  "},   # whitespace-only — should be skipped
]


class TestFormatSrt:
    def test_numbered_sequentially(self):
        result = format_srt(SEGS)
        assert result.startswith("1\n")
        assert "2\n" in result

    def test_timestamp_format(self):
        result = format_srt(SEGS)
        assert "00:00:00,000 --> 00:00:01,500" in result

    def test_text_present(self):
        result = format_srt(SEGS)
        assert "Hello world" in result
        assert "Goodbye" in result

    def test_skips_empty_text(self):
        result = format_srt(SEGS)
        # Only 2 valid segments → last index is 2
        assert "3\n" not in result

    def test_empty_segments(self):
        assert format_srt([]) == ""


# ── format_vtt ─────────────────────────────────────────────────────────────────

class TestFormatVtt:
    def test_starts_with_webvtt(self):
        result = format_vtt(SEGS)
        assert result.startswith("WEBVTT")

    def test_timestamp_format(self):
        result = format_vtt(SEGS)
        assert "00:00:00.000 --> 00:00:01.500" in result

    def test_text_present(self):
        result = format_vtt(SEGS)
        assert "Hello world" in result

    def test_skips_empty_text(self):
        result = format_vtt(SEGS)
        # whitespace-only segment should not produce a cue
        assert result.count("-->") == 2

    def test_empty_segments(self):
        result = format_vtt([])
        assert result.startswith("WEBVTT")


# ── format_txt_timed ───────────────────────────────────────────────────────────

class TestFormatTxtTimed:
    def test_timestamp_prefix(self):
        result = format_txt_timed(SEGS)
        assert result.startswith("[00:00:00]")

    def test_contains_text(self):
        result = format_txt_timed(SEGS)
        assert "Hello world" in result
        assert "Goodbye" in result

    def test_skips_whitespace_only(self):
        result = format_txt_timed(SEGS)
        lines = result.splitlines()
        assert len(lines) == 2  # whitespace-only segment skipped

    def test_empty_segments(self):
        assert format_txt_timed([]) == ""


class TestRenderTranscript:
    def test_renders_plain_text_by_default(self):
        result = render_transcript(SEGS, fmt="txt")
        assert result.startswith("[00:00:00]")
        assert "Hello world" in result

    def test_uses_diarizer_when_provided(self):
        diarizer = object()
        with mock.patch("transcribe.diarize_audio_local", return_value=[{"start": 0, "end": 2, "speaker": "speaker_a"}]):
            result = render_transcript(SEGS[:1], fmt="txt", diarizer=diarizer, audio_path=Path("/tmp/demo.wav"))
        assert "Person 1: Hello world" in result

    def test_requires_audio_path_for_diarizer(self):
        with pytest.raises(ValueError):
            render_transcript(SEGS, fmt="txt", diarizer=object())
