# stenographer.spec
# Run with:  pyinstaller stenographer.spec
# or via:    ./build_dmg.sh

from PyInstaller.building.api import PYZ, EXE, COLLECT
from PyInstaller.building.osx import BUNDLE
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_data_files

# Hidden imports required by faster-whisper / ctranslate2
_hidden = [
    "faster_whisper",
    "ctranslate2",
    "huggingface_hub",
    "tokenizers",
    "numpy",
    "av",
    "tkinterdnd2",
]

# tkinterdnd2 ships native Tcl extensions (dylib + tcl scripts) that
# PyInstaller won't discover automatically — collect them explicitly.
_tkdnd_datas = collect_data_files("tkinterdnd2")

# faster-whisper bundles a Silero VAD ONNX model that PyInstaller misses.
_fw_datas = collect_data_files("faster_whisper")

# ── GUI ────────────────────────────────────────────────────────────────────────
a_gui = Analysis(
    ["app/one_click_ui.py"],
    pathex=["app"],
    binaries=[],
    datas=_tkdnd_datas + _fw_datas,
    hiddenimports=_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# ── CLI transcriber (runs as subprocess spawned by the GUI) ───────────────────
a_cli = Analysis(
    ["app/transcribe.py"],
    pathex=["app"],
    binaries=[],
    datas=_fw_datas,
    hiddenimports=_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

MERGE(
    (a_gui, "Stenographer", "Stenographer"),
    (a_cli, "transcribe",   "transcribe"),
)

pyz_gui = PYZ(a_gui.pure)
pyz_cli = PYZ(a_cli.pure)

exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name="Stenographer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # no Terminal window for the GUI
    windowed=True,
    icon="assets/icon.icns" if __import__("os").path.exists("assets/icon.icns") else None,
)

exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name="transcribe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.zipfiles,
    a_gui.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.zipfiles,
    a_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Stenographer",
)

app = BUNDLE(
    coll,
    name="Stenographer.app",
    icon="assets/icon.icns" if __import__("os").path.exists("assets/icon.icns") else None,
    bundle_identifier="com.feanor08.stenographer",
    info_plist={
        "CFBundleShortVersionString": "1.0.8",
        "CFBundleVersion":            "1.0.8",
        "NSHighResolutionCapable":    True,
        "NSMicrophoneUsageDescription": "Stenographer does not use the microphone.",
        "LSMinimumSystemVersion":     "11.0",
    },
)
