"""Tests for updater.py — update check logic."""
import unittest.mock as mock

import pytest

import updater


class TestCheck:
    def test_no_update_when_dates_equal(self):
        with mock.patch("updater.fetch_latest_commit_date", return_value="2026-03-27T10:00:00Z"):
            available, latest = updater.check("2026-03-27T10:00:00Z")
        assert available is False
        assert latest == "2026-03-27T10:00:00Z"

    def test_update_available_when_remote_is_newer(self):
        with mock.patch("updater.fetch_latest_commit_date", return_value="2026-03-28T10:00:00Z"):
            available, latest = updater.check("2026-03-27T10:00:00Z")
        assert available is True
        assert latest == "2026-03-28T10:00:00Z"

    def test_no_update_when_remote_is_older(self):
        with mock.patch("updater.fetch_latest_commit_date", return_value="2026-03-26T10:00:00Z"):
            available, latest = updater.check("2026-03-27T10:00:00Z")
        assert available is False

    def test_first_run_stores_date_without_alerting(self):
        with mock.patch("updater.fetch_latest_commit_date", return_value="2026-03-27T10:00:00Z"):
            available, latest = updater.check(None)
        assert available is False
        assert latest == "2026-03-27T10:00:00Z"

    def test_network_failure_returns_false_none(self):
        with mock.patch("updater.fetch_latest_commit_date", return_value=None):
            available, latest = updater.check("2026-03-27T10:00:00Z")
        assert available is False
        assert latest is None

    def test_network_failure_on_first_run(self):
        with mock.patch("updater.fetch_latest_commit_date", return_value=None):
            available, latest = updater.check(None)
        assert available is False
        assert latest is None
