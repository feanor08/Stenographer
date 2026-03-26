# Audio Transcriber

A simple desktop app that turns your audio files into text — no internet required, no accounts, no subscriptions. Just drop your files in and hit go.

**[⬇ Download](https://github.com/feanor08/AudioTranscriber/archive/refs/heads/main.zip)**

## Getting started

**Step 1 — Install FFmpeg** (you only need to do this once)

- On a Mac: open Terminal and run `brew install ffmpeg`
- On Ubuntu/Debian Linux: open Terminal and run `sudo apt install ffmpeg`

If you don't have Homebrew on Mac, grab it from [brew.sh](https://brew.sh) first.

**Step 2 — Run the installer** (also just once)

Double-click `install` in the project folder, or open Terminal, navigate to the folder, and run:
```
./install
```
This sets everything up automatically.

**Step 3 — Launch the app**

Run `./transcribe` (or double-click it). A window will pop up.

## How to use it

1. Click **Choose Files** and pick your audio files (MP3, M4A, WAV, and most other formats work)
2. Pick a model — **medium** is a good starting point (see below)
3. Hit **Transcribe**
4. When it's done, click **Open Result** to see your transcription

Your transcription lands in `app/transcriptions.txt` — one section per file.

## Choosing a model

Bigger models are more accurate but take longer. Here's a rough guide:

| Model | Speed | Accuracy | Good for |
|-------|-------|----------|----------|
| tiny | Very fast | ~60% | Quick drafts, testing |
| base | Fast | ~70% | Short clips, clear audio |
| small | Fast | ~80% | Most everyday use |
| medium | Balanced | ~90% | Best default choice |
| large-v3 | Slow | ~95% | Important recordings, tricky accents |

The app shows you an estimated finish time before you start, so you can pick based on how long you're willing to wait.

## What audio files does it support?

MP3, WAV, M4A, FLAC, OGG, AAC, WMA, MP4, MKV — basically anything you'd normally encounter.

## Does it need the internet?

Only to download the model the first time you use it. After that it works completely offline. Models are saved to your computer automatically.

## Tips

- Clean, quiet recordings give the best results. Heavy background noise or music can trip it up.
- If you're transcribing a conversation with multiple speakers, the result will just be one big block of text — speaker labels aren't supported in the GUI (there's a CLI option for that if you need it).
- The app remembers how long model loading took last time and uses that to give you better time estimates going forward.
