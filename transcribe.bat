@echo off
setlocal
set "DIR=%~dp0"
if not exist "%DIR%app\venv\Scripts\python.exe" (
    echo ERROR: App not installed yet.
    echo Please run install.bat first.
    pause
    exit /b 1
)
"%DIR%app\venv\Scripts\python.exe" "%DIR%app\one_click_ui.py"
