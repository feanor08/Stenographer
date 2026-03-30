# cli.spec — standalone stenographer CLI binary
# Built separately from stenographer.spec to avoid the case-insensitive
# filesystem conflict between dist/stenographer (binary) and
# dist/Stenographer/ (PyInstaller COLLECT folder).

from PyInstaller.building.api import PYZ, EXE
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_data_files

_hidden = [
    "faster_whisper",
    "ctranslate2",
    "huggingface_hub",
    "tokenizers",
    "numpy",
    "av",
]

_fw_datas = collect_data_files("faster_whisper")

a = Analysis(
    ["app/cli.py"],
    pathex=["app"],
    binaries=[],
    datas=_fw_datas,
    hiddenimports=_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "tkinterdnd2", "_tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

# One-file binary: bundle everything directly into the EXE so Homebrew
# can install a single self-contained file.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="stenographer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
