<div align="center">
  <img src="assets/cinder.png" alt="Cinder app icon" width="112" />
  <h1>Cinder</h1>
  <p><strong>Your Smart Dial. Your controls. Your workflow.</strong></p>
  <p>A Windows companion for the CMF Buds Pro 2 Smart Dial, with a radial control wheel, app shortcuts and local speech dictation.</p>
  <p>
    <a href="https://github.com/Homis1de/Cinder/releases"><img alt="GitHub Releases" src="https://img.shields.io/github/v/release/Homis1de/Cinder?display_name=tag&style=flat-square&color=ba3448"></a>
    <a href="https://github.com/Homis1de/Cinder/blob/main/LICENSE"><img alt="MIT License" src="https://img.shields.io/github/license/Homis1de/Cinder?style=flat-square"></a>
    <a href="https://github.com/Homis1de/Cinder/issues"><img alt="Issues" src="https://img.shields.io/github/issues/Homis1de/Cinder?style=flat-square"></a>
    <img alt="Windows" src="https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-20232a?style=flat-square&logo=windows">
  </p>
  <p><a href="https://github.com/Homis1de/Cinder/releases/latest"><strong>Download Cinder</strong></a> · <a href="https://github.com/Homis1de/Cinder/issues">Report a bug</a> · <a href="https://github.com/Homis1de/Cinder/releases">Release notes</a></p>
</div>

---

## What is Cinder?

Cinder turns your supported Smart Dial into a handy control surface for Windows. Open the circular wheel, choose a mode, and use the dial for common actions without reaching for your keyboard every time.

The launcher and the wheel share one Settings window, so your controls and shortcuts are managed in one place.

## Features

| | Feature | What it does |
|---|---|---|
| ◉ | **Radial control wheel** | Choose a mode from a circular menu and control it with the dial. |
| ↕ | **Everyday controls** | Change volume or brightness, scroll pages, navigate browser tabs and windows, zoom, and use supported presentation controls. |
| ⌘ | **Custom shortcuts** | Add shortcuts for applications, websites and keyboard actions. |
| ◈ | **App icons** | Custom executable shortcuts use the application's Windows icon when one is available. |
| ▤ | **Launcher** | Open the launcher from a desktop or Start Menu shortcut and access the same Settings used by the wheel. |
| ☾ | **Tray and startup options** | Choose whether Cinder starts at sign-in, stays in the system tray when the launcher closes, and uses reduced animations. |
| 🎙 | **Local dictation** | Convert speech to text with `faster-whisper`, using a model downloaded to your PC. Review the transcription before inserting it. |

> Cinder is actively developed. Device behaviour can vary with Windows version, Bluetooth audio profiles and the specific headset firmware. See [Issues](https://github.com/Homis1de/Cinder/issues) for known problems or to report a new one.

## Get Cinder

### Windows installer

1. Open **[GitHub Releases](https://github.com/Homis1de/Cinder/releases)**.
2. Download the latest `Cinder-Setup-...-x64.exe` installer.
3. Run it and choose an installation folder. You can opt to create a desktop shortcut.
4. Launch Cinder from the desktop or Start Menu shortcut.

The installer is published through GitHub Releases when a release build is available. If no installer is listed yet, use the source setup below or check back after the first release is published.

### Run from source

**Requirements:** Windows 10 or 11 (64-bit) and Python 3.12 (64-bit recommended). A microphone and an internet connection are needed for the first speech-model download if you use dictation.

1. Install [Python 3.12](https://www.python.org/downloads/) if needed.
2. Download and extract this repository.
3. Open a terminal in the project directory and run:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --timeout 300 --retries 10 -r requirements.txt
   .\.venv\Scripts\python.exe cinder.py
   ```

If the `py` launcher isn't available, use `python` in the first command. If dependency installation times out, retry it or use a package mirror you trust.

## Dictation and privacy

Cinder uses `faster-whisper` for speech recognition. The selected model must be downloaded the first time; subsequent runs can use the local model cache. The first run can therefore take longer than later ones.

- Choose and test the input device under **Settings → Dictation**. Bluetooth headsets can expose more than one microphone endpoint.
- **Base** is a reasonable starting point for faster CPU transcription; **Small** can improve recognition in some cases but needs more time and storage.
- Dictation is processed locally after the model is downloaded. Cinder does not send recorded audio to a cloud transcription service. Internet access is needed to fetch a model that is not already cached.
- Review the result before inserting it into the focused application.

Cinder stores local settings in `config.json` when run from source. The installed version stores its settings in `%LOCALAPPDATA%\Cinder\config.json`. Back up your configuration before replacing or removing a source folder. The installer leaves user settings and the speech-model cache intact when the application is uninstalled.

## Building the Windows application

To build the packaged application and installer yourself, see **[BUILD_WINDOWS.md](BUILD_WINDOWS.md)**. The project includes a PowerShell build script and an Inno Setup installer definition.

```powershell
# Diagnostic build (keeps a console visible for troubleshooting)
.\scripts\build_windows.ps1 -Diagnostic

# Release build (requires Inno Setup 6 to compile the installer)
.\scripts\build_windows.ps1
```

Test the diagnostic build first, then install and test the generated setup program before sharing it. See [installer/README.md](installer/README.md) for installer-specific notes.

## Project structure

| File | Purpose |
|---|---|
| `cinder.py` | Application startup, dial events, actions and tray integration |
| `cinder_wheel.py` | Circular wheel interface |
| `cinder_settings.py` | Launcher-style Settings and custom controls |
| `cinder_dictation.py` | Microphone capture and local transcription |
| `cinder_osd.py` | On-screen brightness display |
| `cinder_brand.py` | Version and application icon loading |
| `assets/` | Cinder icon files |
| `scripts/build_windows.ps1` | Windows packaging script |
| `installer/Cinder.iss` | Inno Setup installer configuration |

## Troubleshooting

<details>
  <summary><strong>Dictation is slow or returns no text</strong></summary>

  Open **Settings → Dictation**, test the selected microphone, and check Windows microphone permissions for desktop apps. Try another headset input endpoint if the input level is very low. The first transcription may take longer while the speech model downloads or loads.
</details>

<details>
  <summary><strong>The model download fails</strong></summary>

  Check your internet connection and try again. A Hugging Face cache symlink warning is not, by itself, a transcription failure; it can mean the cache uses more disk space.
</details>

<details>
  <summary><strong>The dial or a control does not behave as expected</strong></summary>

  Confirm that the headset is connected and recognised by Windows. Behaviour can vary by audio profile and device. If the problem continues, [open an issue](https://github.com/Homis1de/Cinder/issues) with your Windows version, headset connection type, steps to reproduce and any relevant error output. Remove personal information from logs before posting them.
</details>

## Contributing and bug reports

Bug reports, thoughtful suggestions and pull requests are welcome. Before opening an issue, search existing issues and include:

- Windows version and whether you're running from source or the installer
- Steps to reproduce the problem
- What you expected and what actually happened
- Relevant error messages (with personal information removed)

Please avoid uploading configuration files, recordings, access tokens or other private data to an issue.

## License and attribution

Cinder is released under the [MIT License](LICENSE).

Cinder is an independent community project and is **not affiliated with, endorsed by, or an official product of Nothing or CMF**. Product and brand names are used only to identify the compatible hardware.
