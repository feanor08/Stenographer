#!/usr/bin/env python3
"""
Simple desktop GUI for non-technical users.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext

PROJECT_ROOT = Path(__file__).resolve().parent
LAUNCHER = PROJECT_ROOT / "audio_transcriber_cli.py"
INPUT_FOLDER = PROJECT_ROOT / "input_audio"


class DesktopLauncher:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Audio Transcriber")
        self.root.geometry("860x560")
        self.root.minsize(760, 480)

        self.process: subprocess.Popen[str] | None = None
        self.output_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()

        self.status_var = tk.StringVar(value="Ready")
        self._build_ui()
        self.root.after(100, self._drain_output_queue)

    def _build_ui(self) -> None:
        container = tk.Frame(self.root, padx=18, pady=18)
        container.pack(fill="both", expand=True)

        title = tk.Label(
            container,
            text="Audio Transcriber",
            font=("Helvetica", 18, "bold"),
            anchor="w",
        )
        title.pack(fill="x")

        subtitle = tk.Label(
            container,
            text=(
                "1. Click 'Open Input Folder' and place audio files in it.\n"
                "2. Click 'Install / Repair' once.\n"
                "3. Click 'Run Transcription'."
            ),
            justify="left",
            anchor="w",
        )
        subtitle.pack(fill="x", pady=(6, 14))

        button_row = tk.Frame(container)
        button_row.pack(fill="x", pady=(0, 14))

        self.install_button = tk.Button(
            button_row,
            text="Install / Repair",
            width=18,
            command=lambda: self._start_command(["install"], "Installing environment"),
        )
        self.install_button.pack(side="left")

        self.run_button = tk.Button(
            button_row,
            text="Run Transcription",
            width=18,
            command=lambda: self._start_command(["run"], "Running transcription"),
        )
        self.run_button.pack(side="left", padx=(10, 0))

        self.open_input_button = tk.Button(
            button_row,
            text="Open Input Folder",
            width=18,
            command=self._open_input_folder,
        )
        self.open_input_button.pack(side="left", padx=(10, 0))

        self.open_project_button = tk.Button(
            button_row,
            text="Open Project Folder",
            width=18,
            command=lambda: self._open_folder(PROJECT_ROOT),
        )
        self.open_project_button.pack(side="left", padx=(10, 0))

        status = tk.Label(container, textvariable=self.status_var, anchor="w")
        status.pack(fill="x", pady=(0, 10))

        self.output = scrolledtext.ScrolledText(container, wrap="word", state="disabled")
        self.output.pack(fill="both", expand=True)
        self._append_output(
            "Welcome.\n"
            "You can keep this window open while installation or transcription is running.\n"
            "Output will appear here.\n\n"
        )

    def _append_output(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.insert("end", text)
        self.output.see("end")
        self.output.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.install_button.configure(state=state)
        self.run_button.configure(state=state)

    def _open_folder(self, folder: Path) -> None:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)], cwd=str(PROJECT_ROOT))
            return
        if sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", str(folder)], cwd=str(PROJECT_ROOT))
            return

        messagebox.showinfo("Open Folder", f"Open this folder manually:\n{folder}")

    def _open_input_folder(self) -> None:
        INPUT_FOLDER.mkdir(parents=True, exist_ok=True)
        self._open_folder(INPUT_FOLDER)

    def _start_command(self, args: list[str], status_text: str) -> None:
        if self.process is not None and self.process.poll() is None:
            messagebox.showinfo("Already Running", "Please wait for the current task to finish.")
            return

        self.status_var.set(status_text)
        self._set_busy(True)
        self._append_output(f"$ {sys.executable} {LAUNCHER.name} {' '.join(args)}\n")

        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")

        self.process = subprocess.Popen(
            [sys.executable, str(LAUNCHER), *args],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=env,
        )

        threading.Thread(target=self._read_process_output, args=(self.process,), daemon=True).start()

    def _read_process_output(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        try:
            for line in process.stdout:
                self.output_queue.put(("line", line))
        finally:
            returncode = process.wait()
            self.output_queue.put(("done", str(returncode)))

    def _drain_output_queue(self) -> None:
        try:
            while True:
                kind, payload = self.output_queue.get_nowait()
                if kind == "line":
                    self._append_output(payload)
                elif kind == "done":
                    code = int(payload)
                    self.process = None
                    self._set_busy(False)
                    if code == 0:
                        self.status_var.set("Finished successfully")
                        self._append_output("\nFinished successfully.\n\n")
                    else:
                        self.status_var.set(f"Finished with errors (exit code {code})")
                        self._append_output(f"\nFinished with errors (exit code {code}).\n\n")
        except queue.Empty:
            pass

        self.root.after(100, self._drain_output_queue)


def main() -> None:
    root = tk.Tk()
    DesktopLauncher(root)
    root.mainloop()


if __name__ == "__main__":
    main()
