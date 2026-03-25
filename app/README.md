# Audio Transcriber

Offline audio transcription using [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Drop audio files in, get a single `transcriptions.txt` out.

## Quick start

**1. Install FFmpeg** (one-time system dependency):
- macOS: `brew install ffmpeg`
- Ubuntu/Debian: `sudo apt install ffmpeg`

**2. Run the installer** from the project root:
```bash
./install
```
This creates a Python virtualenv at `app/venv/`, installs all packages, and writes the `transcribe` launcher script.

**3. Launch the GUI:**
```bash
./transcribe
```

## What it does

- **Inputs:** audio files staged into `app/input_audio/` by the GUI, or drop a ZIP (`audio_inputs.zip`) or folder there manually.
- **Models:** tiny / base / small / medium / large-v3 — selectable in the GUI with estimated runtime and accuracy shown per model.
- **Output:** `app/transcriptions.txt` — one section per input file.
- **Optional diarization:** labels speakers as Person 1, Person 2, … via `--diarize` (CLI only).

## CLI usage

For direct/scripted use, run the transcription engine directly:
```bash
app/venv/bin/python app/transcribe.py \
  --model medium        # tiny | base | small | medium | large-v3 | whisperx
  --language auto       # e.g. en, hi, ta; 'auto' = detect
  --task transcribe     # or 'translate' (to English)
  --order name          # or 'ctime' (default) to sort by creation time
  --diarize             # enable speaker labeling
  --num-speakers 2      # optional hint for diarization
  --output transcriptions.txt
```

## Project layout

```
audio_transcriber/
├── install              # run once to set up
├── transcribe           # created by install; opens the GUI
└── app/
    ├── one_click_ui.py  # GUI (tkinter)
    ├── transcribe.py    # transcription engine (CLI / called by GUI)
    ├── shared.py        # shared constants and formatters
    ├── requirements.txt
    └── input_audio/     # place audio files here for CLI use
```

## Notes

- CPU is supported out of the box. For GPU add `--device cuda`.
- Models are downloaded from HuggingFace on first use and cached in `~/.cache/huggingface/hub/`.
- Works best with clean audio; heavy noise or clipping reduces accuracy.
