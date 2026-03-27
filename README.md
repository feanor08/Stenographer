# 🎙️ Stenographer

> Turn any audio file into text — no internet, no accounts, no subscriptions. Just press go.

**[⬇️ Download the latest DMG](https://github.com/feanor08/Stenographer/releases/latest)**

---

## 🖥️ What does it look like?

You get a simple window. Pick your files, choose a quality level, hit **Transcribe**. That's it.

The transcribed text file is saved right next to your original audio file — you'll find it right where you left it.

---

## 🚀 Getting started

Two steps, both done **once, ever**. (Mac only)

---

### Step 1 — Download & install

1. Click the download link above and open the `.dmg`
2. Drag **Stenographer** into your **Applications** folder
3. Open it — a warning will pop up saying Apple can't verify the developer

> ⚠️ **Why the warning?** Mac blocks apps downloaded from the internet by default. To get past it:
> - Right-click the app → **Open** → **Open**
> - Or go to **System Settings → Privacy & Security** → **Open Anyway**
>
> You only need to do this once.

---

### Step 2 — Install FFmpeg *(optional but recommended)*

FFmpeg lets the app show you how long transcription will take before you start. Without it the app still works — just no time estimate.

1. Open **Terminal** (`⌘ + Space`, type "Terminal", hit Enter)
2. Paste this and hit Enter:
   ```
   brew install ffmpeg
   ```
   > Don't have Homebrew? Run this first, then repeat step 2:
   > ```
   > /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   > ```

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
