"""Tests for pure/filesystem helpers in transcribe.py."""
import shutil
import unittest.mock as mock
from pathlib import Path

import pytest

from transcribe import (
    partial_output_path,
    collect_audio_files,
    check_ffmpeg,
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


# ── check_ffmpeg ───────────────────────────────────────────────────────────────

class TestCheckFfmpeg:
    def test_returns_true_when_ffmpeg_found(self):
        with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            assert check_ffmpeg() is True

    def test_returns_false_when_ffmpeg_missing(self):
        with mock.patch("shutil.which", return_value=None):
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
