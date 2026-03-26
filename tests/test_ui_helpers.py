"""Tests for module-level helpers in one_click_ui.py."""
import sys
import unittest.mock as mock

import pytest

# Import only the module-level helpers — avoids touching tk.Tk()
import one_click_ui
from one_click_ui import strip_ansi, open_file, show_in_file_manager


# ── strip_ansi ─────────────────────────────────────────────────────────────────

class TestStripAnsi:
    def test_plain_text_unchanged(self):
        assert strip_ansi("hello world") == "hello world"

    def test_removes_color_code(self):
        assert strip_ansi("\x1b[1;31mred text\x1b[0m") == "red text"

    def test_removes_multiple_codes(self):
        assert strip_ansi("\x1b[2mDIM\x1b[0m \x1b[1;34mBLUE\x1b[0m") == "DIM BLUE"

    def test_removes_osc_sequence(self):
        assert strip_ansi("\x1b]0;title\x07content") == "content"

    def test_empty_string(self):
        assert strip_ansi("") == ""

    def test_only_escape_codes_leaves_empty(self):
        assert strip_ansi("\x1b[0m") == ""


# ── open_file ──────────────────────────────────────────────────────────────────

class TestOpenFile:
    def test_macos_calls_open(self, monkeypatch):
        monkeypatch.setattr(one_click_ui, "_sys", "Darwin")
        with mock.patch("one_click_ui.subprocess.run") as mock_run:
            open_file("/path/to/file.txt")
            mock_run.assert_called_once_with(["open", "/path/to/file.txt"])

    def test_linux_calls_open(self, monkeypatch):
        monkeypatch.setattr(one_click_ui, "_sys", "Linux")
        with mock.patch("one_click_ui.subprocess.run") as mock_run:
            open_file("/path/to/file.txt")
            mock_run.assert_called_once_with(["open", "/path/to/file.txt"])

    def test_windows_calls_startfile(self, monkeypatch):
        monkeypatch.setattr(one_click_ui, "_sys", "Windows")
        # os.startfile is Windows-only; create=True allows patching it on macOS/Linux
        with mock.patch("one_click_ui.os.startfile", create=True) as mock_sf:
            open_file(r"C:\path\to\file.txt")
            mock_sf.assert_called_once_with(r"C:\path\to\file.txt")


# ── show_in_file_manager ───────────────────────────────────────────────────────

class TestShowInFileManager:
    def test_macos_calls_open_r(self, monkeypatch):
        monkeypatch.setattr(one_click_ui, "_sys", "Darwin")
        with mock.patch("one_click_ui.subprocess.run") as mock_run:
            show_in_file_manager("/path/to/file.txt")
            mock_run.assert_called_once_with(["open", "-R", "/path/to/file.txt"])

    def test_linux_calls_open_r(self, monkeypatch):
        monkeypatch.setattr(one_click_ui, "_sys", "Linux")
        with mock.patch("one_click_ui.subprocess.run") as mock_run:
            show_in_file_manager("/path/to/file.txt")
            mock_run.assert_called_once_with(["open", "-R", "/path/to/file.txt"])

    def test_windows_calls_explorer_select(self, monkeypatch):
        monkeypatch.setattr(one_click_ui, "_sys", "Windows")
        with mock.patch("one_click_ui.subprocess.run") as mock_run:
            show_in_file_manager(r"C:\path\to\file.txt")
            mock_run.assert_called_once_with(
                ["explorer", "/select,", r"C:\path\to\file.txt"]
            )
