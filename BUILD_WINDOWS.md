# Build Cinder for Windows

Build on a Windows x64 machine using Python 3.12. This produces the application folder and, when Inno Setup 6 is installed, a standard installer EXE.

## 1. Prepare the environment

Open PowerShell in this project folder and run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --timeout 300 --retries 10 -r requirements.txt
```

Run `python cinder.py` from that environment once if you want to check the source app before packaging.

## 2. Build a diagnostic package

```powershell
.\scripts\build_windows.ps1 -Diagnostic
```

Quit any existing Cinder instance first (source or packaged), then launch `dist\Cinder-Diagnostic\Cinder-Diagnostic.exe --launcher` from PowerShell. The console remains visible to help diagnose missing imports or runtime errors. Cinder uses a single-instance channel, so another running instance can receive the launcher request instead. Test the wheel, app shortcuts, settings, tray behaviour and dictation.

## 3. Build the release package and installer

Install [Inno Setup 6](https://jrsoftware.org/isinfo.php). In `installer\Cinder.iss`, replace the sample GitHub URL and publisher attribution before distributing the installer. Then run:

```powershell
.\scripts\build_windows.ps1
```

The application folder is `dist\Cinder`. If Inno Setup is installed, the installer is written to `release\Cinder-Setup-v0.14.0-x64.exe`. The installer offers a directory selection page, Start Menu shortcut, a desktop-shortcut task (checked by default) and launches the launcher after setup.

Quit any source/diagnostic Cinder instance before testing the release build. Install the setup on a clean Windows account and test it again before publishing. Do not ship the diagnostic build as the public release.

## User data

Installed settings are stored at `%LOCALAPPDATA%\Cinder\config.json`. Model data continues to use the existing `%LOCALAPPDATA%\DialLab\models` cache so a user who already downloaded a model does not need to download it again. Uninstall preserves the settings and model cache.
