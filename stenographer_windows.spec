# stenographer_windows.spec
# Run with:  pyinstaller stenographer_windows.spec
#
# Builds a Windows onedir GUI app plus the bundled transcribe.exe helper that
# the GUI launches as a subprocess.

import os

from PyInstaller.building.api import PYZ, EXE, COLLECT
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_data_files

_hidden = [
    "faster_whisper",
    "ctranslate2",
    "huggingface_hub",
    "tokenizers",
    "numpy",
    "av",
    "tkinterdnd2",
]

_tkdnd_datas = collect_data_files("tkinterdnd2")
_fw_datas = collect_data_files("faster_whisper")

# Bundle app icon assets so the GUI can load them at runtime.
_icon_datas = [
    (f, "assets") for f in [
        "assets/icon.png",
        "assets/scroll-icon.ico",
    ] if os.path.exists(f)
]

a_gui = Analysis(
    ["app/one_click_ui.py"],
    pathex=["app"],
    binaries=[],
    datas=_tkdnd_datas + _fw_datas + _icon_datas,
    hiddenimports=_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

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
    console=False,
    windowed=True,
    icon="assets/scroll-icon.ico" if os.path.exists("assets/scroll-icon.ico") else None,
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
