param(
    [switch]$Diagnostic
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Missing .venv. Run: py -3.12 -m venv .venv, then install requirements.txt."
}

# pip exits quickly when PyInstaller is already installed in this environment.
& $Python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Could not install PyInstaller." }

if ($Diagnostic) {
    $TargetName = "Cinder-Diagnostic"
    $WindowMode = "--console"
} else {
    $TargetName = "Cinder"
    $WindowMode = "--windowed"
}

if (Test-Path ".\build") { Remove-Item ".\build" -Recurse -Force }
if (Test-Path ".\dist\$TargetName") { Remove-Item ".\dist\$TargetName" -Recurse -Force }
if (Test-Path ".\$TargetName.spec") { Remove-Item ".\$TargetName.spec" -Force }

$PyInstallerArgs = @(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", $WindowMode,
    "--name", $TargetName,
    "--icon", "assets\cinder.ico",
    "--version-file", "assets\version_info.txt",
    "--add-data", "assets;assets",
    "--collect-all", "faster_whisper",
    "--collect-all", "ctranslate2",
    "--collect-all", "av",
    "--collect-all", "huggingface_hub",
    "--collect-all", "tokenizers",
    "--collect-all", "screen_brightness_control",
    "--hidden-import", "winrt.windows.foundation",
    "--hidden-import", "winrt.windows.foundation.collections",
    "--hidden-import", "winrt.windows.media",
    "--hidden-import", "winrt.windows.media.core",
    "--hidden-import", "winrt.windows.media.playback",
    "--hidden-import", "winrt.windows.media.control",
    "cinder.py"
)

Write-Host "Building $TargetName..." -ForegroundColor Cyan
& $Python @PyInstallerArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed. Review the error output above." }

$BuiltExe = Join-Path $ProjectRoot "dist\$TargetName\$TargetName.exe"
if (-not (Test-Path $BuiltExe)) { throw "Build ended without $BuiltExe." }
Write-Host "Build complete: $BuiltExe" -ForegroundColor Green

if ($Diagnostic) {
    Write-Host "Run the diagnostic build from PowerShell with: .\dist\Cinder-Diagnostic\Cinder-Diagnostic.exe --launcher" -ForegroundColor Yellow
    Write-Host "The diagnostic build is for testing; do not publish it as the release." -ForegroundColor Yellow
    exit 0
}

$IsccCandidates = @(
    "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($Iscc) {
    & $Iscc (Join-Path $ProjectRoot "installer\Cinder.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed. Review its compiler output." }
    Write-Host "Installer build complete. See the release folder." -ForegroundColor Green
} else {
    Write-Host "Inno Setup was not found. The app folder is ready. Install Inno Setup 6 to create the installable Setup EXE." -ForegroundColor Yellow
}
