@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 audio_transcriber_cli.py run %*
  exit /b %errorlevel%
)

where python >nul 2>nul
if %errorlevel%==0 (
  python audio_transcriber_cli.py run %*
  exit /b %errorlevel%
)

echo Python 3 not found. Please install Python 3 and retry.
exit /b 1
