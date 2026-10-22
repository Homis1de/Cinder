"""Shared Cinder branding assets and app metadata."""
from __future__ import annotations

from pathlib import Path
import sys
from PySide6.QtGui import QIcon

APP_VERSION = "0.14.0"
APP_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
ASSET_DIR = APP_ROOT / "assets"
APP_ICON_PATH = ASSET_DIR / "cinder.ico"
APP_ICON_PNG_PATH = ASSET_DIR / "cinder.png"


def app_icon() -> QIcon:
    """Return the packaged Windows app icon, or an empty QIcon as fallback."""
    if APP_ICON_PATH.is_file():
        return QIcon(str(APP_ICON_PATH))
    if APP_ICON_PNG_PATH.is_file():
        return QIcon(str(APP_ICON_PNG_PATH))
    return QIcon()
