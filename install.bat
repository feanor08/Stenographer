@echo off
setlocal
chcp 65001 >nul
set "DIR=%~dp0"
set "APP=%DIR%app"
set "VENV=%APP%\venv"

echo.
echo ============================================
echo    AUDIO TRANSCRIBER - Installer
echo ============================================
echo.

REM -- Python --
echo Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    echo Download it from https://python.org
    echo Make sure to tick "Add Python to PATH" during install.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo Found: %%v

REM -- Virtual environment --
echo.
echo Setting up virtual environment...
if not exist "%VENV%" (
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo ERROR: Could not create virtual environment.
        echo Make sure Python is properly installed.
        pause
        exit /b 1
    )
    echo Created venv at app\venv\
) else (
    echo venv already exists - skipping
)

REM -- pip packages --
echo.
echo Upgrading pip...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip

echo.
echo Installing packages (this may take a few minutes)...
"%VENV%\Scripts\python.exe" -m pip install "click>=8.1.7" "faster-whisper>=1.0.0" "rich>=13.7.0" "typer>=0.12.0"
if errorlevel 1 (
    echo.
    echo ERROR: Package install failed.
    echo If you see an error about "Microsoft Visual C++", download and install:
    echo https://aka.ms/vs/17/release/vc_redist.x64.exe
    echo Then run install.bat again.
    pause
    exit /b 1
)
echo Packages installed.

REM -- FFmpeg --
echo.
echo Checking FFmpeg...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo WARNING: FFmpeg not found.
    echo Download it from https://ffmpeg.org/download.html
    echo Unzip it, then add the \bin folder to your PATH.
    echo See the README for step-by-step instructions.
) else (
    echo FFmpeg found.
)

echo.
echo ============================================
echo    INSTALL COMPLETE
echo    Double-click transcribe.bat to open app
echo ============================================
echo.
pause
