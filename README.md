# 🎙️ Audio Transcriber

> Turn any audio file into text — no internet, no accounts, no subscriptions. Just press go.

**[⬇️ Download](https://github.com/feanor08/AudioTranscriber/archive/refs/heads/main.zip)**

---

## 🖥️ What does it look like?

You get a simple window. Pick your files, choose a quality level, hit **Transcribe**. That's it.

The transcribed text file is saved right next to your original audio file — you'll find it right where you left it.

---

## 🚀 Getting started

There are 3 steps to get it running. You only do steps 1 and 2 **once, ever**.

---

### Step 1 — Install FFmpeg

FFmpeg is a free tool that helps read audio files. You just need to install it once.

**On a Mac:**

1. Open **Terminal** (press `⌘ + Space`, type "Terminal", hit Enter)
2. Paste this and hit Enter:
   ```
   brew install ffmpeg
   ```
   > Don't have Homebrew? First run this, then come back:
   > ```
   > /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   > ```

**On Linux (Ubuntu/Debian):**
```
sudo apt install ffmpeg
```

---

### Step 2 — Run the installer

1. Unzip the downloaded folder
2. Open **Terminal** and drag the folder into it (this sets the path automatically)
3. Type `./install` and hit Enter

This sets everything up. You'll see some text scroll by — that's normal. Wait for it to finish.

---

### Step 3 — Open the app

Double-click the **`transcribe`** file in the folder, or type `./transcribe` in Terminal.

A window will pop up and you're ready to go! ✅

---

## 🎧 How to use it

| Step | What to do |
|------|-----------|
| 1️⃣ | Click **Choose Files** and pick your audio |
| 2️⃣ | Pick a model (not sure? just leave it on **medium**) |
| 3️⃣ | Hit the big **Transcribe** button |
| 4️⃣ | The file opens automatically when it's done ✅ |

---

## ⚡ Which model should I pick?

Think of it like a photo — higher quality takes longer to process.

| Model | Speed | Accuracy | When to use it |
|-------|-------|----------|----------------|
| tiny | ⚡⚡⚡⚡ Very fast | ~60% | Just testing it out |
| base | ⚡⚡⚡ Fast | ~70% | Short clips, clear audio |
| small | ⚡⚡ Fast | ~80% | Everyday recordings |
| **medium** ⭐ | ⚡ Balanced | ~90% | **Best starting point** |
| large-v3 | 🐢 Slow | ~95% | Important recordings, heavy accents |

The app will show you how long it'll take **before** you start, so you can decide.

---

## 📁 What file types work?

Pretty much everything:

`MP3` · `WAV` · `M4A` · `FLAC` · `AAC` · `OGG` · `WMA` · `MP4` · `MKV`

---

## 🌐 Does it need wifi?

Only **once** — to download the AI model the first time you use it.

After that, it works **100% offline**. Your audio never leaves your computer.

---

## 💡 Tips for best results

- 🎯 **Clear audio = better results.** Background music or noise will reduce accuracy.
- 🔇 **Quiet recordings** transcribe much better than ones with lots of echo.
- ⏱️ The app learns from each run and gets better at predicting how long things will take.
