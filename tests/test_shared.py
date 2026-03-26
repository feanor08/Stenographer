"""Tests for shared.py — pure utility functions."""
import re
from unittest.mock import patch
from datetime import datetime

import pytest
from shared import fmt_dur, fmt_hms, fmt_clock, fmt_timestamp


# ── fmt_dur ────────────────────────────────────────────────────────────────────

class TestFmtDur:
    def test_zero(self):
        assert fmt_dur(0) == "0S"

    def test_negative_clamps_to_zero(self):
        assert fmt_dur(-5) == "0S"

    def test_under_a_minute(self):
        assert fmt_dur(45) == "45S"

    def test_exactly_one_minute(self):
        assert fmt_dur(60) == "1M 00S"

    def test_minutes_and_seconds(self):
        assert fmt_dur(90) == "1M 30S"

    def test_exactly_one_hour(self):
        assert fmt_dur(3600) == "1H 0M"

    def test_hours_and_minutes(self):
        assert fmt_dur(3661) == "1H 1M"

    def test_float_rounds(self):
        # 59.6 rounds to 60 → "1M 00S"
        assert fmt_dur(59.6) == "1M 00S"


# ── fmt_hms ────────────────────────────────────────────────────────────────────

class TestFmtHms:
    def test_zero(self):
        assert fmt_hms(0) == "00:00:00"

    def test_seconds_only(self):
        assert fmt_hms(45) == "00:00:45"

    def test_minutes_and_seconds(self):
        assert fmt_hms(90) == "00:01:30"

    def test_hours_minutes_seconds(self):
        assert fmt_hms(3661) == "01:01:01"

    def test_negative_clamps_to_zero(self):
        assert fmt_hms(-10) == "00:00:00"


# ── fmt_clock ──────────────────────────────────────────────────────────────────

class TestFmtClock:
    _PATTERN = re.compile(r"^\d{1,2}:\d{2} (AM|PM)$")

    def test_format(self):
        result = fmt_clock(300)
        assert self._PATTERN.match(result), f"unexpected format: {result!r}"

    def test_zero_seconds_is_now(self):
        # Should not raise; result is a valid clock string
        assert self._PATTERN.match(fmt_clock(0))

    def test_hour_range(self):
        # Pin "now" to midnight so we can reason about the output
        fixed = datetime(2024, 1, 1, 0, 0, 0)
        with patch("shared.datetime") as mock_dt:
            mock_dt.now.return_value = fixed
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = fmt_clock(0)
        # 12:00 AM
        assert result == "12:00 AM"


# ── fmt_timestamp ──────────────────────────────────────────────────────────────

class TestFmtTimestamp:
    _PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_format(self):
        import time
        ts = time.time()
        assert self._PATTERN.match(fmt_timestamp(ts))

    def test_known_value(self):
        # 2024-01-15 10:30:00 UTC+0 local — use a fixed epoch
        fixed = datetime(2024, 1, 15, 10, 30, 0)
        import time
        ts = fixed.timestamp()
        result = fmt_timestamp(ts)
        assert self._PATTERN.match(result)
