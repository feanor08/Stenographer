#!/usr/bin/env python3
"""
Cross-platform launcher for installing dependencies and running the transcriber.
"""

from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path
from typing import Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / "venv"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"
TRANSCRIBER_FILE = PROJECT_ROOT / "transcribe_from_zip_or_folder.py"
INSTALL_MARKER = VENV_DIR / ".audio_transcriber_installed"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def print_status(message: str) -> None:
    print(message, flush=True)


def run_checked(command: Sequence[str]) -> None:
    subprocess.run(list(command), cwd=str(PROJECT_ROOT), check=True)


def write_install_marker() -> None:
    INSTALL_MARKER.write_text("ok\n", encoding="utf-8")


def create_virtualenv() -> None:
    if VENV_DIR.exists() and venv_python().exists():
        return

    print_status(f"Creating virtual environment in {VENV_DIR} ...")
    venv.EnvBuilder(with_pip=True).create(str(VENV_DIR))


def install_requirements() -> None:
    create_virtualenv()
    python_executable = str(venv_python())

    print_status("Upgrading pip ...")
    run_checked([python_executable, "-m", "pip", "install", "--upgrade", "pip"])

    print_status("Installing Python dependencies ...")
    run_checked([python_executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)])

    write_install_marker()
    print_status("")
    print_status("Setup complete.")
    if os.name == "nt":
        print_status("Run transcription with: run.cmd")
    else:
        print_status("Run transcription with: ./run")


def ensure_installed() -> None:
    if not venv_python().exists() or not INSTALL_MARKER.exists():
        print_status("Environment not set up yet. Running install first ...")
        install_requirements()


def run_transcriber(args: Iterable[str]) -> int:
    ensure_installed()
    command = [str(venv_python()), str(TRANSCRIBER_FILE), *list(args)]
    completed = subprocess.run(command, cwd=str(PROJECT_ROOT), check=False)
    return int(completed.returncode)


def fallback_usage() -> int:
    print(
        "Usage:\n"
        "  python audio_transcriber_cli.py install\n"
        "  python audio_transcriber_cli.py run [transcriber options]\n"
    )
    return 0


def fallback_main(argv: Sequence[str]) -> int:
    if len(argv) < 2 or argv[1] in {"-h", "--help"}:
        return fallback_usage()

    command = argv[1]
    if command == "install":
        install_requirements()
        return 0
    if command == "run":
        return run_transcriber(argv[2:])

    print(f"Unknown command: {command}", file=sys.stderr)
    return 2


try:
    import click
except ImportError:
    click = None


if click is not None:

    @click.group(help="Cross-platform launcher for this audio transcriber project.")
    def cli() -> None:
        pass


    @cli.command(help="Create the local virtual environment and install dependencies.")
    def install() -> None:
        install_requirements()


    @cli.command(
        context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
        help="Run the transcriber and forward all extra flags to the transcription script.",
    )
    @click.pass_context
    def run(ctx: click.Context) -> None:
        raise SystemExit(run_transcriber(ctx.args))


def main() -> int:
    if click is None:
        return fallback_main(sys.argv)
    cli()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
