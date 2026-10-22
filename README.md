# Cinder

Cinder v0.14.0 adds a launcher-style control center and a standard Windows installer build recipe. The launcher and the wheel's Settings tile open the same configuration window.

Cinder is a Windows companion for the Nothing/CMF Buds Pro 2 Smart Dial. It adds a circular launcher, dial-controlled modes, custom shortcuts, brightness controls and local speech-to-text.

## Features

- Open a wheel with the dial, rotate to choose a tile and tap to select it.
- Use modes for volume, undo/redo, browser tabs, window switching, zoom, scrolling, page navigation, brightness and slides.
- Add tiles for applications, websites and keyboard shortcuts.
- Dictate text with faster-whisper. Recognition runs locally after the model has been downloaded.
- Configure the microphone, language and model size in Settings.
- Open the launcher from the desktop or Start Menu; use **Open wheel** when you need the radial control.
- Add app shortcuts using the executable's own Windows icon.
- Choose whether Cinder starts at sign-in, stays in the tray when the launcher closes, or uses reduced animations.

## Requirements

- Windows 10 or 11, 64-bit
- Python 3.12, 64-bit recommended
- A microphone available to Windows for dictation
- Internet connection for the first download of a speech model

## Run from source

1. Download and extract the project.
2. Install Python 3.12 if needed.
3. Open the project folder in PowerShell or VS Code's terminal.
4. Create an environment and install dependencies:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --timeout 300 --retries 10 -r requirements.txt
   .\.venv\Scripts\python.exe cinder.py
   ```

If `py` is unavailable, use `python -m venv .venv` for the first command. If package installation times out, retry it or use a package mirror you trust.

## Dictation

Open **Settings → Dictation** and select the microphone you use. Bluetooth headsets can show multiple input endpoints, so test each available CMF option. **Base** is the faster model on a CPU; **Small** may improve recognition accuracy but takes more time and disk space. Choose the spoken language for short recordings when possible.

To dictate, focus a text field, open the wheel and choose **Dictation**. Speak, select **Stop & transcribe**, review the result, then choose **Insert text**. Cinder does not insert the text until you confirm it.

The first transcription downloads the selected model into the local Windows user cache. The audio is processed on the PC and is not sent to a cloud transcription service. Model downloads require internet access.

## Build the Windows installer

See [BUILD_WINDOWS.md](BUILD_WINDOWS.md) for the full packaging walkthrough. The repository includes `scripts/build_windows.ps1` and `installer/Cinder.iss`. On a Windows x64 PC, create `.venv` and install `requirements.txt`. Test a console build first:

```powershell
.\scripts\build_windows.ps1 -Diagnostic
```

Quit any existing Cinder instance first, then launch `dist\Cinder-Diagnostic\Cinder-Diagnostic.exe --launcher` and test the dial and dictation. Then install [Inno Setup 6](https://jrsoftware.org/isinfo.php), update the GitHub repository URL and publisher in `installer/Cinder.iss`, and build the release package:

```powershell
.\scripts\build_windows.ps1
```

The installer offers an installation directory, Start Menu shortcut, optional desktop shortcut and an option to launch Cinder after setup. Test the installer on a clean Windows account before publishing it. The app folder in `dist\Cinder` is the PyInstaller build output; the setup EXE is produced in `release`.

## Configuration

When run from source, Cinder creates `config.json` beside the source files on first launch. An installed build stores its configuration under `%LOCALAPPDATA%\Cinder\config.json` so settings are writable without administrator rights. It stores the app name, wheel options and custom tiles. Back it up before replacing the project folder. The file is excluded from Git because it can contain personal app paths and shortcuts.

## Troubleshooting

- **No speech is recognized:** open Settings → Dictation and test the selected microphone. Check Windows microphone permissions for desktop apps.
- **The input level is almost zero:** test another microphone endpoint, including the headset's hands-free endpoint or the laptop microphone.
- **The first transcription is slow:** Cinder may still be downloading or loading the model. Base is the faster starting point.
- **The model download fails:** check internet access to Hugging Face and retry. A symlink warning from the model cache is not itself a failure.
- **Text goes into the wrong app:** focus the intended text field before starting dictation and review the result before inserting it.

## Project layout

- `cinder.py` — app startup, dial events, actions, configuration and tray menu
- `cinder_wheel.py` — circular wheel UI
- `cinder_settings.py` — settings, microphone test and custom tiles
- `cinder_dictation.py` — audio capture and local transcription
- `cinder_osd.py` — brightness overlay
- `cinder_brand.py` — app version and icon loading
- `assets/` — Cinder icon files (PNG, ICO and editable SVG)

## License

Released under the MIT License. Cinder is an independent project and is not an official Nothing or CMF application.
