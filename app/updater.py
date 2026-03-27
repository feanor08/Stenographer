"""
updater.py — lightweight update checker.

Fetches the latest commit date from GitHub on a background thread so the UI
never blocks.  No third-party dependencies — uses only stdlib urllib.
"""
import json
import urllib.request
from typing import Optional, Tuple

REPO         = "feanor08/Stenographer"
API_URL      = f"https://api.github.com/repos/{REPO}/commits/main"
DOWNLOAD_URL = f"https://github.com/{REPO}/archive/refs/heads/main.zip"


def fetch_latest_commit_date() -> Optional[str]:
    """Return the ISO-8601 committer date of the latest commit on main, or None on failure."""
    try:
        req = urllib.request.Request(
            API_URL,
            headers={
                "Accept":     "application/vnd.github+json",
                "User-Agent": "AudioTranscriber",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            return data["commit"]["committer"]["date"]
    except Exception:
        return None


def check(known_date: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Compare `known_date` (stored in settings) to the latest commit on GitHub.

    Returns (update_available, latest_date).

    - If the network call fails, returns (False, None) — silent no-op.
    - On the very first run (known_date is None), records the current date
      without flagging an update, so new installs don't immediately prompt.
    - On subsequent runs, flags an update if latest_date > known_date
      (ISO-8601 string comparison works correctly for UTC timestamps).
    """
    latest = fetch_latest_commit_date()
    if latest is None:
        return False, None
    if known_date is None:
        return False, latest          # first run — store but don't alert
    return latest > known_date, latest
