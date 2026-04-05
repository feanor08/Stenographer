$ErrorActionPreference = "Stop"

$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $Dir "app\venv\Scripts\python.exe"
$Version = if ($env:BUILD_VERSION) { $env:BUILD_VERSION } else { "dev" }
$Dist = Join-Path $Dir "dist"
$GuiDir = Join-Path $Dist "Stenographer"
$GuiZip = Join-Path $Dist "Stenographer-$Version-windows-x64.zip"
$CliDist = Join-Path $Dist "cli-build"
$CliExe = Join-Path $Dist "stenograph-windows-x86_64.exe"

if (-not (Test-Path $VenvPython)) {
    throw "No venv found at app\venv. Create it before running build_windows.ps1."
}

Remove-Item -Recurse -Force (Join-Path $Dir "build"), $Dist -ErrorAction SilentlyContinue

& $VenvPython -m PyInstaller "$Dir\stenographer_windows.spec" --noconfirm
& $VenvPython -m PyInstaller "$Dir\cli.spec" --noconfirm --distpath $CliDist

Copy-Item (Join-Path $CliDist "stenograph.exe") $CliExe -Force
Compress-Archive -Path $GuiDir -DestinationPath $GuiZip -Force

Write-Host "GUI zip: $GuiZip"
Write-Host "CLI exe: $CliExe"
