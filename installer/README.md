# Windows installer

Cinder's installable Windows Setup EXE is built from the PyInstaller onedir folder using Inno Setup 6. The installer lets the user choose an installation directory, creates a Start Menu shortcut, offers a desktop shortcut, and launches the Cinder launcher after setup.

## Build

1. From PowerShell in the project root, prepare `.venv` and install `requirements.txt`.
2. Install [Inno Setup 6](https://jrsoftware.org/isinfo.php).
3. Update `MyAppURL` in `installer/Cinder.iss` with the public GitHub repository URL. Set publisher attribution to the name you want shown to users.
4. Run `scripts/build_windows.ps1`.
5. Test `dist/Cinder/Cinder.exe --launcher` and then install the generated setup EXE on a clean Windows user account before publishing.

Cinder stores installed configuration in `%LOCALAPPDATA%\Cinder\config.json`; speech models continue to use the existing local model cache. Uninstalling removes the application but deliberately leaves user settings and model cache intact.
