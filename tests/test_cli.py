"""Tests for the public stenograph CLI."""
from typer.testing import CliRunner

import cli


runner = CliRunner()


def _fake_segments(*_args, **_kwargs):
    yield {"start": 0.0, "end": 1.0, "text": "Hello world"}


class TestPublicCli:
    def test_reports_missing_ffmpeg(self, monkeypatch, tmp_path):
        audio = tmp_path / "clip.wav"
        audio.touch()
        monkeypatch.setattr(cli, "check_ffmpeg", lambda: False)

        result = runner.invoke(cli.cli, [str(audio)])

        assert result.exit_code == 1
        assert "FFmpeg not found" in result.output

    def test_writes_output_to_requested_directory(self, monkeypatch, tmp_path):
        audio = tmp_path / "clip.wav"
        out_dir = tmp_path / "out"
        audio.touch()
        out_dir.mkdir()

        monkeypatch.setattr(cli, "check_ffmpeg", lambda: True)
        monkeypatch.setattr(cli, "get_total_audio_duration", lambda _files: 1.0)
        monkeypatch.setattr(cli, "get_audio_duration_seconds", lambda _audio: 1.0)
        monkeypatch.setattr(cli, "is_model_cached", lambda _model: True)
        monkeypatch.setattr(cli, "load_model_with_progress", lambda *_args, **_kwargs: {"model": object()})
        monkeypatch.setattr(cli, "iter_transcribe_segments", _fake_segments)

        result = runner.invoke(
            cli.cli,
            [str(audio), "--model", "tiny", "--output-dir", str(out_dir)],
        )

        assert result.exit_code == 0, result.output
        outputs = list(out_dir.glob("clip_transcribed_*.txt"))
        assert len(outputs) == 1
        assert outputs[0].read_text(encoding="utf-8").strip() == "[00:00:00] Hello world"

    def test_keeps_outputs_unique_when_stems_repeat(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "out"
        audio_a = tmp_path / "a" / "clip.wav"
        audio_b = tmp_path / "b" / "clip.wav"
        out_dir.mkdir()
        audio_a.parent.mkdir()
        audio_b.parent.mkdir()
        audio_a.touch()
        audio_b.touch()

        monkeypatch.setattr(cli, "check_ffmpeg", lambda: True)
        monkeypatch.setattr(cli, "get_total_audio_duration", lambda _files: 2.0)
        monkeypatch.setattr(cli, "get_audio_duration_seconds", lambda _audio: 1.0)
        monkeypatch.setattr(cli, "is_model_cached", lambda _model: True)
        monkeypatch.setattr(cli, "load_model_with_progress", lambda *_args, **_kwargs: {"model": object()})
        monkeypatch.setattr(cli, "iter_transcribe_segments", _fake_segments)

        result = runner.invoke(
            cli.cli,
            [str(audio_a), str(audio_b), "--model", "tiny", "--output-dir", str(out_dir)],
        )

        assert result.exit_code == 0, result.output
        names = sorted(path.name for path in out_dir.glob("clip_transcribed_*.txt"))
        assert len(names) == 2
        assert names[0].endswith(".txt")
        assert names[1].endswith("_2.txt")
