"""Cinder: a Windows Smart Dial companion for Nothing and CMF earbuds.

The dial uses media-button events for clicks and audio endpoint changes for
rotation. Outside the wheel, volume control is left untouched.
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
import wave
import shutil
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from cinder_brand import APP_VERSION, app_icon
from cinder_wheel import ControlWheel
from cinder_settings import SettingsWindow
from cinder_osd import BrightnessOSD
from cinder_dictation import DictationOverlay

APP_NAME = "Cinder"

def _config_path() -> Path:
    """Keep installed settings in the user's profile, not Program Files."""
    if getattr(sys, "frozen", False):
        local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        folder = local_app_data / "Cinder"
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / "config.json"
        # Import a legacy config beside the executable once, but never overwrite newer user settings.
        legacy = Path(sys.executable).resolve().parent / "config.json"
        if not destination.exists() and legacy.is_file():
            try:
                shutil.copy2(legacy, destination)
            except OSError:
                pass
        return destination
    return Path(__file__).with_name("config.json")

CONFIG_PATH = _config_path()
# Preserve the existing model/audio cache so upgrades don't force another model download.
CACHE_DIR = Path.home() / "AppData" / "Local" / "DialLab"
SILENCE_PATH = CACHE_DIR / "silence.wav"

VK: dict[str, int] = {
    "BACKSPACE": 0x08, "TAB": 0x09, "ENTER": 0x0D, "SHIFT": 0x10,
    "CTRL": 0x11, "CONTROL": 0x11, "ALT": 0x12, "PAUSE": 0x13,
    "CAPSLOCK": 0x14, "ESC": 0x1B, "SPACE": 0x20, "PAGEUP": 0x21,
    "PAGEDOWN": 0x22, "END": 0x23, "HOME": 0x24, "LEFT": 0x25,
    "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28, "PRINTSCREEN": 0x2C,
    "INSERT": 0x2D, "DELETE": 0x2E, "WIN": 0x5B,
    "VOLUME_MUTE": 0xAD, "VOLUME_DOWN": 0xAE, "VOLUME_UP": 0xAF,
    "EQUALS": 0xBB, "PLUS": 0xBB, "MINUS": 0xBD, "BACKTICK": 0xC0,
    "MEDIA_NEXT": 0xB0, "MEDIA_PREVIOUS": 0xB1, "MEDIA_STOP": 0xB2,
    "MEDIA_PLAY_PAUSE": 0xB3,
}
for _n in range(1, 25):
    VK[f"F{_n}"] = 0x70 + _n - 1
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    VK[_c] = ord(_c)


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def make_silence(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * 8000 * 10)


def default_config() -> dict[str, Any]:
    """Starter configuration: tools are built in, optional, and user-extensible."""
    builtins = [
        {"id": "volume", "label": "Volume", "icon": "◖", "kind": "mode", "mode": "volume", "enabled": True, "built_in": True},
        {"id": "undo_redo", "label": "Undo / Redo", "icon": "↶", "kind": "mode", "mode": "undo_redo", "enabled": True, "built_in": True},
        {"id": "tabs", "label": "Browser Tabs", "icon": "▤", "kind": "mode", "mode": "tabs", "enabled": True, "built_in": True},
        {"id": "windows", "label": "Switch Windows", "icon": "⇥", "kind": "mode", "mode": "windows", "enabled": True, "built_in": True},
        {"id": "zoom", "label": "Browser Zoom", "icon": "⌕", "kind": "mode", "mode": "zoom", "enabled": True, "built_in": True},
        {"id": "scroll", "label": "Scroll", "icon": "↕", "kind": "mode", "mode": "scroll", "enabled": True, "built_in": True},
        {"id": "page_navigation", "label": "Page Back / Fwd", "icon": "↔", "kind": "mode", "mode": "page_navigation", "enabled": True, "built_in": True},
        {"id": "brightness", "label": "Brightness", "icon": "☼", "kind": "mode", "mode": "brightness", "enabled": True, "built_in": True},
        {"id": "slides", "label": "Slides", "icon": "▷", "kind": "mode", "mode": "slides", "enabled": True, "built_in": True},
        {"id": "dictation", "label": "Dictation", "icon": "🎙", "kind": "action", "actions": [{"type": "dictation"}], "enabled": True, "built_in": True},
        {"id": "screenshot", "label": "Screenshot", "icon": "▣", "kind": "action", "actions": [{"type": "hotkey", "keys": ["WIN", "PRINTSCREEN"]}], "enabled": True, "built_in": True},
        {"id": "media_toggle", "label": "Play / Pause", "icon": "⏯", "kind": "action", "actions": [{"type": "media", "command": "toggle"}], "enabled": True, "built_in": True},
        {"id": "settings", "label": "Settings", "icon": "⚙", "kind": "settings", "actions": [], "enabled": True, "built_in": True},
        {"id": "tutorial", "label": "Tutorial", "icon": "?", "kind": "tutorial", "actions": [], "enabled": True, "built_in": True},
    ]
    return {
        "app_name": "Cinder",
        "version": 14,
        "preferences": {"start_with_windows": False, "close_to_tray": True, "wheel_animations": True},
        "dictation": {"input_device_name": "", "input_hostapi_name": "", "model_size": "base", "language": "en"},
        "default_mode": "volume",
        "wheel": {
            "device_name_contains": "buds pro 2",
            "last_selected_item_id": "volume",
            "last_active_mode": "volume",
            "position": "bottom-center",
            "open_select_events": ["PLAY", "PAUSE", "PLAY_PAUSE"],
            "next_events": ["NEXT"],
            "previous_events": ["PREVIOUS"],
            "cancel_events": ["STOP"],
            "items": builtins,
        },
        "modes": {
            "volume": {
                "label": "Volume Control",
                "description": "Turn up/down to change system volume",
                "positive_label": "Volume up", "negative_label": "Volume down",
                "passthrough_volume": True, "positive_actions": [], "negative_actions": [],
            },
            "undo_redo": {
                "label": "Undo / Redo", "description": "Turn up to redo; turn down to undo",
                "positive_label": "Redo", "negative_label": "Undo",
                "positive_actions": [{"type": "hotkey", "keys": ["CTRL", "Y"]}],
                "negative_actions": [{"type": "hotkey", "keys": ["CTRL", "Z"]}],
            },
            "tabs": {
                "label": "Browser Tabs", "description": "Turn up for next tab; down for previous tab",
                "positive_label": "Next tab", "negative_label": "Previous tab",
                "positive_actions": [{"type": "hotkey", "keys": ["CTRL", "TAB"]}],
                "negative_actions": [{"type": "hotkey", "keys": ["CTRL", "SHIFT", "TAB"]}],
            },
            "windows": {
                "label": "Switch Windows", "description": "Turn up/down to switch application windows",
                "positive_label": "Next window", "negative_label": "Previous window",
                "positive_actions": [{"type": "hotkey", "keys": ["ALT", "TAB"]}],
                "negative_actions": [{"type": "hotkey", "keys": ["ALT", "SHIFT", "TAB"]}],
            },
            "zoom": {
                "label": "Browser Zoom", "description": "Turn up to zoom in; down to zoom out",
                "positive_label": "Zoom in", "negative_label": "Zoom out",
                "positive_actions": [{"type": "hotkey", "keys": ["CTRL", "EQUALS"]}],
                "negative_actions": [{"type": "hotkey", "keys": ["CTRL", "MINUS"]}],
            },
            "scroll": {
                "label": "Scroll", "description": "Turn up to scroll up; down to scroll down",
                "positive_label": "Scroll up", "negative_label": "Scroll down",
                "positive_actions": [{"type": "scroll", "command": "up"}],
                "negative_actions": [{"type": "scroll", "command": "down"}],
            },
            "page_navigation": {
                "label": "Page Back / Forward", "description": "Turn up to navigate forward; down to go back",
                "positive_label": "Page forward", "negative_label": "Page back",
                "positive_actions": [{"type": "hotkey", "keys": ["ALT", "RIGHT"]}],
                "negative_actions": [{"type": "hotkey", "keys": ["ALT", "LEFT"]}],
            },
            "brightness": {
                "label": "Brightness", "description": "Turn up/down to adjust supported display brightness",
                "positive_label": "Brightness up", "negative_label": "Brightness down",
                "positive_actions": [{"type": "brightness", "command": "up", "step": 5}],
                "negative_actions": [{"type": "brightness", "command": "down", "step": 5}],
            },
            "slides": {
                "label": "Slides", "description": "Turn up for next slide; down for previous slide",
                "positive_label": "Next slide", "negative_label": "Previous slide",
                "positive_actions": [{"type": "hotkey", "keys": ["PAGEDOWN"]}],
                "negative_actions": [{"type": "hotkey", "keys": ["PAGEUP"]}],
            },
        },
        "buttons": {
            "NEXT": [{"type": "media", "command": "next"}],
            "PREVIOUS": [{"type": "media", "command": "previous"}],
            "STOP": [{"type": "media", "command": "pause"}],
        },
        "unmapped_event_action": "log",
    }


def visible_wheel_items(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return all enabled tiles in one 360-degree wheel ring.

    Built-in controls appear first in a sensible order; custom tiles follow,
    but every enabled tile is shown on the same wheel with no hidden pages.
    """
    items = [item for item in config.get("wheel", {}).get("items", [])
             if isinstance(item, dict) and item.get("enabled", True)]
    priority = {
        "volume": 0, "undo_redo": 1, "tabs": 2, "windows": 3,
        "zoom": 4, "scroll": 5, "brightness": 6, "settings": 7,
        "page_navigation": 8, "slides": 9, "dictation": 10,
        "screenshot": 11, "media_toggle": 12, "tutorial": 13,
    }
    original_order = {id(item): index for index, item in enumerate(items)}
    return sorted(
        items,
        key=lambda item: (
            0 if item.get("built_in", False) else 1,
            priority.get(str(item.get("id", "")), 1000 + original_order[id(item)])
            if item.get("built_in", False) else original_order[id(item)],
        ),
    )


def _migrate_v4_config(old: dict[str, Any]) -> dict[str, Any]:
    """Upgrade an existing v0.4 configuration without retaining demo app tiles."""
    fresh = default_config()
    old_wheel = old.get("wheel", {}) if isinstance(old.get("wheel"), dict) else {}
    fresh["wheel"]["device_name_contains"] = str(old_wheel.get("device_name_contains", fresh["wheel"]["device_name_contains"]))
    fresh["wheel"]["position"] = str(old_wheel.get("position", "bottom-center"))
    fresh["buttons"] = old.get("buttons", fresh["buttons"])

    # Preserve edits to known mode behavior where the user had customized v0.4.
    old_modes = old.get("modes", {})
    if isinstance(old_modes, dict):
        for key, old_mode in old_modes.items():
            if key in fresh["modes"] and isinstance(old_mode, dict):
                fresh["modes"][key].update({k: v for k, v in old_mode.items() if k in fresh["modes"][key]})

    built_in_labels = {
        "volume control", "undo / redo", "browser tabs", "switch windows", "browser zoom",
        "discord", "youtube", "screenshot", "play / pause", "close wheel",
    }
    old_items = old_wheel.get("items", [])
    if isinstance(old_items, list):
        for n, item in enumerate(old_items):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "Custom tile"))
            if label.lower() in built_in_labels or item.get("kind") == "mode":
                continue
            if item.get("kind") == "action" and isinstance(item.get("actions", []), list):
                migrated = dict(item)
                migrated.update({"id": f"migrated_{n}_{uuid.uuid4().hex[:6]}", "built_in": False, "enabled": True, "is_custom_app": True})
                fresh["wheel"]["items"].append(migrated)
    fresh["version"] = 10
    return fresh

def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        config = default_config()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log(f"Created starter config: {path}")
        return config
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read {path.name}: {exc}") from exc
    if not isinstance(config, dict):
        raise RuntimeError("config.json must contain a JSON object.")
    if int(config.get("version", 0) or 0) < 5:
        config = _migrate_v4_config(config)
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log("Updated the previous config.json to the current format.")
    if not isinstance(config.get("buttons"), dict):
        raise RuntimeError("config.json must contain a 'buttons' object.")
    wheel = config.get("wheel")
    if not isinstance(wheel, dict) or not isinstance(wheel.get("items"), list):
        raise RuntimeError("config.json needs a 'wheel.items' list.")
    if not wheel["items"]:
        raise RuntimeError("config.json needs at least one wheel item. Add one through Settings.")
    wheel.setdefault("position", "bottom-center")
    wheel.setdefault("last_selected_item_id", "")
    wheel.setdefault("last_active_mode", config.get("default_mode", "volume"))
    for index, item in enumerate(wheel["items"]):
        if not isinstance(item, dict) or not isinstance(item.get("label"), str):
            raise RuntimeError(f"wheel.items[{index}] needs an object with a string label.")
        if not isinstance(item.get("actions", []), list):
            raise RuntimeError(f"wheel.items[{index}].actions must be a list when provided.")
        item.setdefault("id", f"item_{index}")
        item.setdefault("enabled", True)
        item.setdefault("built_in", False)
        for action in item.get("actions", []):
            if not isinstance(action, dict) or not isinstance(action.get("type"), str):
                raise RuntimeError(f"Every action in wheel.items[{index}] needs a string 'type'.")
        if item.get("kind") == "mode":
            mode_name = item.get("mode")
            if not isinstance(mode_name, str):
                raise RuntimeError(f"wheel.items[{index}] is a mode tile but has no string 'mode'.")
        elif item.get("kind") not in {"action", "settings", "tutorial"}:
            raise RuntimeError(f"wheel.items[{index}] has an unknown kind: {item.get('kind')!r}.")
    if not visible_wheel_items(config):
        raise RuntimeError("All wheel items are disabled. Enable at least one item in Settings.")
    modes = config.get("modes", {})
    if not isinstance(modes, dict):
        raise RuntimeError("config.json 'modes' must be an object.")
    for mode_name, mode in modes.items():
        if not isinstance(mode_name, str) or not isinstance(mode, dict):
            raise RuntimeError("Each modes entry must map a mode name to an object.")
        for direction in ("positive_actions", "negative_actions"):
            actions = mode.get(direction, [])
            if not isinstance(actions, list):
                raise RuntimeError(f"modes.{mode_name}.{direction} must be a list.")
            for action in actions:
                if not isinstance(action, dict) or not isinstance(action.get("type"), str):
                    raise RuntimeError(f"Every action in modes.{mode_name}.{direction} needs a string 'type'.")
    default_mode = config.get("default_mode", "volume")
    if modes and default_mode not in modes:
        raise RuntimeError("config.json 'default_mode' must name an entry in 'modes'.")
    for item in wheel["items"]:
        if item.get("kind") == "mode" and item.get("mode") not in modes:
            raise RuntimeError(f"Wheel tile {item.get('label', '(unnamed)')!r} references an unknown mode.")
    for event_name, actions in config["buttons"].items():
        if not isinstance(event_name, str) or not isinstance(actions, list):
            raise RuntimeError("Each buttons entry must map an event name to a list of actions.")
        for action in actions:
            if not isinstance(action, dict) or not isinstance(action.get("type"), str):
                raise RuntimeError(f"Every action for {event_name} needs a string 'type'.")

    # Keep user-created tiles and mode mappings intact as the config format evolves.
    version = int(config.get("version", 0) or 0)
    if version < 7:
        for item in wheel["items"]:
            if item.get("id") == "dictation" and item.get("built_in", False):
                item["actions"] = [{"type": "dictation"}]
        config["version"] = 7
        version = 7
        log("Updated config.json to v0.7; custom tiles and mode mappings were preserved.")
    if version < 8:
        # v0.8 routes the built-in Dictation tile to Cinder's local Whisper UI.
        for item in wheel["items"]:
            if item.get("id") == "dictation" and item.get("built_in", False):
                item["actions"] = [{"type": "dictation"}]
        config["version"] = 8
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log("Updated config.json to v0.8; custom tiles and mode mappings were preserved.")
        version = 8
    if version < 9:
        config.setdefault("app_name", "Cinder")
        if not str(config.get("app_name", "")).strip():
            config["app_name"] = "Cinder"
        config["version"] = 9
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log("Updated config.json to v0.9; added editable app branding and preserved your settings.")
        version = 9
    if version < 10:
        wheel.setdefault("last_selected_item_id", "")
        wheel.setdefault("last_active_mode", config.get("default_mode", "volume"))
        config["version"] = 10
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log("Updated config.json to v0.10; added last-selected wheel persistence.")
    # v0.11 adds a configurable dictation input. Store friendly name + host API,
    # not a raw PortAudio index, because indices may change across reconnects.
    if not isinstance(config.get("dictation"), dict):
        config["dictation"] = {}
    config["dictation"].setdefault("input_device_name", "")
    config["dictation"].setdefault("input_hostapi_name", "")
    if int(config.get("version", 0) or 0) < 11:
        config["version"] = 11
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log("Updated config.json to v0.11; added selectable dictation microphone and preserved custom settings.")
    # v0.12 made recognition quality and spoken language configurable.
    config["dictation"].setdefault("model_size", "base")
    config["dictation"].setdefault("language", "en")
    if int(config.get("version", 0) or 0) < 12:
        config["version"] = 12
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log("Updated config.json to v0.12; added dictation quality and language settings.")
    # v0.13 defaults to Base for responsive CPU dictation. Existing settings
    # remain otherwise intact; the model can be changed to Small in Settings.
    if int(config.get("version", 0) or 0) < 13:
        config["dictation"]["model_size"] = "base"
        config["version"] = 13
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log("Updated config.json to v0.13; selected the faster Base dictation model by default.")
    config.setdefault("app_name", "Cinder")
    preferences = config.setdefault("preferences", {})
    if not isinstance(preferences, dict):
        preferences = {}
        config["preferences"] = preferences
    preferences.setdefault("start_with_windows", False)
    preferences.setdefault("close_to_tray", True)
    preferences.setdefault("wheel_animations", True)
    if int(config.get("version", 0) or 0) < 14:
        config["version"] = 14
        try:
            path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            log("Updated config.json to v0.14; added launcher and startup preferences.")
        except OSError as exc:
            log(f"Could not save configuration migration: {exc}")
    return config

def press_key(vk_code: int, key_up: bool = False) -> None:
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    extended_keys = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E, 0x5B, 0x5C}
    flags = KEYEVENTF_EXTENDEDKEY if vk_code in extended_keys else 0
    if key_up:
        flags |= KEYEVENTF_KEYUP
    ctypes.windll.user32.keybd_event(vk_code, 0, flags, 0)


def run_hotkey(keys: list[str]) -> None:
    if not keys or not all(isinstance(k, str) for k in keys):
        raise ValueError("hotkey action needs a non-empty 'keys' list.")
    normalized = [key.strip().upper() for key in keys]
    unknown = [key for key in normalized if key not in VK]
    if unknown:
        raise ValueError(f"Unknown key name(s): {', '.join(unknown)}")
    if len(normalized) > 6:
        raise ValueError("Hotkeys are limited to 6 keys.")
    pressed: list[int] = []
    try:
        for key in normalized:
            press_key(VK[key])
            pressed.append(VK[key])
            time.sleep(0.025)
    finally:
        for code in reversed(pressed):
            press_key(code, key_up=True)
            time.sleep(0.015)


def run_volume_action(command: str) -> None:
    choices = {"up": VK["VOLUME_UP"], "down": VK["VOLUME_DOWN"], "mute": VK["VOLUME_MUTE"]}
    if command not in choices:
        raise ValueError("volume command must be 'up', 'down', or 'mute'.")
    press_key(choices[command])
    time.sleep(0.02)
    press_key(choices[command], key_up=True)


def run_scroll_action(command: str, amount: int = 120) -> None:
    """Send one mouse-wheel step at the current pointer location."""
    if command not in {"up", "down"}:
        raise ValueError("scroll command must be 'up' or 'down'.")
    delta = abs(int(amount)) * (1 if command == "up" else -1)
    if sys.platform != "win32":
        raise RuntimeError("Mouse-wheel scroll actions are supported only on Windows.")
    MOUSEEVENTF_WHEEL = 0x0800
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)


def run_brightness_action(command: str, step: int = 5) -> int:
    """Adjust the primary supported display brightness by a small percentage."""
    if command not in {"up", "down"}:
        raise ValueError("brightness command must be 'up' or 'down'.")
    try:
        import screen_brightness_control as sbc
    except ImportError as exc:
        raise RuntimeError("Brightness support is missing. Install requirements.txt again.") from exc
    current_value = sbc.get_brightness(display=0)
    if isinstance(current_value, (list, tuple)):
        if not current_value:
            raise RuntimeError("No brightness-capable display was found.")
        current_value = current_value[0]
    current = int(current_value)
    delta = abs(int(step)) * (1 if command == "up" else -1)
    target = max(0, min(100, current + delta))
    sbc.set_brightness(target, display=0)
    log(f"Display brightness: {current}% → {target}%")
    return target


async def control_external_media(command: str) -> None:
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager

    manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
    sessions = list(manager.get_sessions())
    if not sessions:
        log("No Windows media sessions are available to control. Open media in Spotify or a browser first.")
        return

    def source_id(session: Any) -> str:
        try:
            return str(session.source_app_user_model_id or "").lower()
        except Exception:
            return ""

    async def is_cinder_session(session: Any) -> bool:
        identity = source_id(session)
        if any(part in identity for part in ("cinder", "python", "pythonw.exe")):
            return True
        try:
            properties = await session.try_get_media_properties_async()
            return "cinder" in str(properties.title or "").lower()
        except Exception:
            return False

    candidates = []
    for session in sessions:
        if not await is_cinder_session(session):
            candidates.append(session)
    if not candidates:
        log("No external media session found. Open/play media in Spotify, a browser, etc.")
        return

    try:
        current = manager.get_current_session()
    except Exception:
        current = None
    target = None
    if current is not None and not await is_cinder_session(current):
        current_id = source_id(current)
        target = next((s for s in candidates if source_id(s) == current_id), None)
    if target is None:
        target = candidates[0]
    methods = {
        "toggle": "try_toggle_play_pause_async", "play": "try_play_async", "pause": "try_pause_async",
        "next": "try_skip_next_async", "previous": "try_skip_previous_async", "stop": "try_stop_async",
    }
    method_name = methods.get(command)
    if method_name is None:
        raise ValueError("media command must be toggle/play/pause/next/previous/stop.")
    method = getattr(target, method_name, None)
    if method is None:
        log(f"The selected media session does not support '{command}'.")
        return
    succeeded = await method()
    log(f"Media action '{command}' sent to {source_id(target) or 'media app'} (accepted={bool(succeeded)}).")


def execute_action(action: dict[str, Any], brightness_changed=None, dictation_requested=None) -> None:
    action_type = str(action.get("type", "")).strip().lower()
    if action_type == "log":
        log(str(action.get("message", "Configured log action.")))
        return
    if action_type == "media":
        asyncio.run(control_external_media(str(action.get("command", "toggle")).strip().lower()))
        return
    if action_type == "hotkey":
        keys = action.get("keys", [])
        run_hotkey(keys)
        log(f"Hotkey sent: {' + '.join(keys)}")
        return
    if action_type in {"dictation", "voice_typing"}:
        if dictation_requested is None:
            raise RuntimeError(f"Local dictation UI is unavailable. Restart {APP_NAME} after installing requirements.txt.")
        dictation_requested()
        log(f"Opened {APP_NAME} local dictation. Record, stop, then insert the recognized text.")
        return
    if action_type == "volume":
        command = str(action.get("command", "")).strip().lower()
        run_volume_action(command)
        log(f"Volume action sent: {command}")
        return
    if action_type == "scroll":
        command = str(action.get("command", "")).strip().lower()
        run_scroll_action(command, int(action.get("amount", 120)))
        log(f"Mouse scroll sent: {command}")
        return
    if action_type == "brightness":
        command = str(action.get("command", "")).strip().lower()
        target = run_brightness_action(command, int(action.get("step", 5)))
        if brightness_changed is not None:
            brightness_changed(target)
        return
    if action_type == "launch":
        program, args = action.get("program"), action.get("args", [])
        if not isinstance(program, str) or not program.strip():
            raise ValueError("launch action needs a non-empty 'program'.")
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ValueError("launch action 'args' must be a list of strings.")
        program = os.path.expandvars(program)
        expanded_args = [os.path.expandvars(arg) for arg in args]
        subprocess.Popen([program, *expanded_args], shell=False, close_fds=True)
        log(f"Launched: {program}")
        return
    if action_type == "open_uri":
        uri = action.get("uri")
        if not isinstance(uri, str) or not uri.strip():
            raise ValueError("open_uri action needs a non-empty 'uri'.")
        parsed = urlparse(uri)
        # Only allow known app-protocol schemes. This hands the URI to Windows
        # ShellExecute / its registered app; it does not execute arbitrary shell text.
        if parsed.scheme.lower() not in {"discord", "spotify", "steam", "microsoft-edge"}:
            raise ValueError("open_uri supports only discord://, spotify://, steam://, or microsoft-edge://.")
        if sys.platform == "win32":
            os.startfile(uri)  # type: ignore[attr-defined]
        else:
            raise RuntimeError("App protocol shortcuts are supported only on Windows.")
        log(f"Opened app URI: {uri}")
        return
    if action_type == "open_url":
        url = action.get("url")
        if not isinstance(url, str):
            raise ValueError("open_url action needs a 'url'.")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("Only valid http:// or https:// URLs can be opened.")
        webbrowser.open(url, new=2)
        log(f"Opened URL: {url}")
        return
    raise ValueError(f"Unknown action type: {action_type!r}")


class ActionRunner:
    """Run external actions on a worker so the Qt UI stays responsive."""

    def __init__(self, config: dict[str, Any], brightness_changed=None, dictation_requested=None) -> None:
        self.config = config
        self.brightness_changed = brightness_changed
        self.dictation_requested = dictation_requested
        self.tasks: queue.Queue[tuple[str, Any] | None] = queue.Queue()
        self.thread = threading.Thread(target=self._work, name="CinderActionRunner", daemon=True)
        self.thread.start()

    def enqueue_event(self, event_name: str) -> None:
        self.tasks.put(("event", event_name))

    def enqueue_actions(self, actions: list[dict[str, Any]], label: str) -> None:
        self.tasks.put(("actions", (actions, label)))

    def close(self) -> None:
        self.tasks.put(None)
        self.thread.join(timeout=2)

    def _work(self) -> None:
        while True:
            task = self.tasks.get()
            try:
                if task is None:
                    return
                kind, payload = task
                if kind == "event":
                    event_name = payload
                    actions = self.config.get("buttons", {}).get(event_name)
                    if actions is None:
                        if self.config.get("unmapped_event_action", "log") == "log":
                            log(f"Unmapped event: {event_name} (edit config.json to assign an action)")
                        continue
                    label = event_name
                else:
                    actions, label = payload
                log(f"Running action(s) for {label}")
                for action in actions:
                    try:
                        execute_action(action, self.brightness_changed, self.dictation_requested)
                    except Exception as exc:
                        log(f"Action failed for {label}: {exc}")
            finally:
                self.tasks.task_done()


class VolumeRotationSource:
    """Interpret changes to the earbuds' Windows output volume as rotation.

    While the wheel is closed, volume changes pass through normally. While it
    is open, each volume delta emits a +/- rotation and the output volume is
    restored to the level recorded when the wheel opened.
    """

    def __init__(self, device_match: str, emit_rotation):
        self.device_match = (device_match or "buds pro 2").strip().lower()
        self.emit_rotation = emit_rotation
        self.commands: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="CinderVolumeWatcher", daemon=True)
        self.started = False

    def start(self) -> None:
        self.started = True
        self.thread.start()

    def set_active(self, active: bool) -> None:
        if self.started:
            self.commands.put(("active", bool(active)))

    def stop(self) -> None:
        self.stop_event.set()
        self.commands.put(("stop", None))
        if self.started:
            self.thread.join(timeout=2)

    def _run(self) -> None:
        try:
            import comtypes
            from pycaw.callbacks import AudioEndpointVolumeCallback
            from pycaw.pycaw import AudioUtilities
        except ImportError as exc:
            log(f"Rotation unavailable: install requirements ({exc})")
            return

        class Callback(AudioEndpointVolumeCallback):
            def __init__(self, owner):
                super().__init__()
                self.owner = owner

            def on_notify(self, new_volume, new_mute, event_context, channels, channel_volumes):
                try:
                    ours = event_context.contents == self.owner.context_guid
                except Exception:
                    ours = False
                self.owner.commands.put(("volume", (float(new_volume), ours)))

        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        device = None
        callback = None
        enumerator = None
        try:
            self.context_guid = comtypes.GUID("{5f0c2a1e-6d3b-4c9a-9a47-0b1e7a1d1a11}")
            enumerator = AudioUtilities.GetDeviceEnumerator()
            collection = enumerator.EnumAudioEndpoints(0, 1)  # active render endpoints
            matches = []
            candidates = []
            for i in range(collection.GetCount()):
                candidate = AudioUtilities.CreateDevice(collection.Item(i))
                name = str(candidate.FriendlyName or "")
                matches.append(name)
                candidates.append(candidate)
                if self.device_match and self.device_match in name.lower() and device is None:
                    device = candidate

            # Bluetooth often exposes both Stereo and Hands-Free endpoints. Prefer
            # the actual default render endpoint when it matches the configured
            # earbuds name; the first substring match can otherwise be the unused
            # Hands-Free endpoint, which does not receive the dial's volume changes.
            default_device = None
            try:
                default_device = AudioUtilities.GetSpeakers()
            except Exception as exc:
                log(f"Could not identify the default output endpoint: {exc}")
            default_name = str(getattr(default_device, "FriendlyName", "") or "") if default_device else ""
            default_matches = bool(self.device_match and self.device_match in default_name.lower())
            if default_device is not None and (default_matches or device is None):
                device = default_device
                if default_matches:
                    log(f"Using the default output endpoint that matches the earbuds: '{default_name}'.")
                else:
                    log(f"No active endpoint name matched {self.device_match!r}; falling back to the default output '{default_name}'.")
            elif device is None and candidates:
                device = candidates[0]
                log(f"Default output unavailable; using first active output '{device.FriendlyName}'.")
            if device is None:
                log("Rotation watcher couldn't find an active output endpoint.")
                log("Available active output devices: " + ("; ".join(matches) if matches else "none"))
                log("Buttons will still work. Check that your earbuds are connected as an audio output.")
                return

            callback = Callback(self)
            device.EndpointVolume.RegisterControlChangeNotify(callback)
            endpoint = device.EndpointVolume
            last_level = float(endpoint.GetMasterVolumeLevelScalar())
            active = False
            saved_level: float | None = None
            last_rotation_at = 0.0
            log(f"Rotation watcher bound to '{device.FriendlyName}'.")

            while not self.stop_event.is_set():
                try:
                    kind, payload = self.commands.get(timeout=0.05)
                except queue.Empty:
                    # Some Bluetooth drivers do not deliver endpoint callbacks
                    # reliably for AVRCP volume changes. Poll while capture is
                    # active as a fallback, using the same direction mapping.
                    if active:
                        try:
                            polled_level = float(endpoint.GetMasterVolumeLevelScalar())
                            previous = last_level
                            if previous is not None and abs(polled_level - previous) >= 0.003:
                                last_level = polled_level
                                direction = 1 if polled_level > previous else -1
                                now = time.monotonic()
                                if now - last_rotation_at >= 0.12:
                                    self.emit_rotation(direction)
                                    last_rotation_at = now
                                    log(f"Rotation detected by volume polling: {'up' if direction > 0 else 'down'}.")
                                else:
                                    log("Ignored a duplicate near-simultaneous volume report.")
                                if saved_level is not None:
                                    endpoint.SetMasterVolumeLevelScalar(saved_level, ctypes.byref(self.context_guid))
                                    last_level = saved_level
                        except Exception as exc:
                            log(f"Volume polling fallback failed: {exc}")
                    continue
                if kind == "stop":
                    break
                if kind == "active":
                    new_active = bool(payload)
                    if new_active and not active:
                        saved_level = float(endpoint.GetMasterVolumeLevelScalar())
                        last_level = saved_level
                        active = True
                        log("Dial rotation now navigates the wheel; volume is held temporarily.")
                    elif not new_active and active:
                        active = False
                        if saved_level is not None:
                            try:
                                endpoint.SetMasterVolumeLevelScalar(saved_level, ctypes.byref(self.context_guid))
                            except Exception as exc:
                                log(f"Could not restore volume after wheel use: {exc}")
                            last_level = saved_level
                        saved_level = None
                        log("Wheel closed; dial rotation returns to volume control.")
                    continue

                if kind == "volume":
                    level, ours = payload
                    if ours:
                        last_level = level
                        continue
                    previous = last_level
                    last_level = level
                    if active and previous is not None and abs(level - previous) >= 0.003:
                        direction = 1 if level > previous else -1
                        now = time.monotonic()
                        if now - last_rotation_at >= 0.12:
                            self.emit_rotation(direction)
                            last_rotation_at = now
                            log(f"Rotation detected by audio callback: {'up' if direction > 0 else 'down'}.")
                        else:
                            log("Ignored a duplicate near-simultaneous volume report.")
                        if saved_level is not None:
                            try:
                                endpoint.SetMasterVolumeLevelScalar(saved_level, ctypes.byref(self.context_guid))
                                last_level = saved_level
                            except Exception as exc:
                                log(f"Could not hold volume while wheel is open: {exc}")
        except Exception as exc:
            log(f"Rotation watcher stopped: {exc}")
        finally:
            if device is not None and callback is not None:
                try:
                    device.EndpointVolume.UnregisterControlChangeNotify(callback)
                except Exception:
                    pass
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass


class InputController(QObject):
    """Owns the wheel and persistent rotation mode state."""

    def __init__(self, config: dict[str, Any], wheel: ControlWheel, runner: ActionRunner,
                 volume_source: VolumeRotationSource, event_queue: queue.Queue,
                 open_settings=None, open_tutorial=None):
        super().__init__()
        self.config = config
        self.wheel = wheel
        self.runner = runner
        self.volume_source = volume_source
        self.event_queue = event_queue
        self.open_settings_callback = open_settings or (lambda: None)
        self.open_tutorial_callback = open_tutorial or (lambda: None)
        wheel_cfg = config["wheel"]
        self.wheel.set_items(visible_wheel_items(config))
        self.wheel.set_position(str(wheel_cfg.get("position", "bottom-center")))
        self.open_select_events = set(wheel_cfg.get("open_select_events", ["PLAY", "PAUSE", "PLAY_PAUSE"]))
        self.next_events = set(wheel_cfg.get("next_events", ["NEXT"]))
        self.previous_events = set(wheel_cfg.get("previous_events", ["PREVIOUS"]))
        self.cancel_events = set(wheel_cfg.get("cancel_events", ["STOP"]))
        self.is_open = False
        self.modes = config.get("modes", {})
        self.last_selected_item_id = str(wheel_cfg.get("last_selected_item_id", "") or "")
        self.current_mode = str(wheel_cfg.get("last_active_mode", config.get("default_mode", "volume")) or config.get("default_mode", "volume"))
        if self.current_mode not in self.modes:
            self.current_mode = str(config.get("default_mode", "volume"))
        if self.current_mode not in self.modes:
            self.current_mode = "volume" if "volume" in self.modes else next(iter(self.modes), "")
        self.wheel.set_active_mode(self._mode_label())
        self.timer = QTimer(self)
        self.timer.setInterval(15)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        wheel.item_clicked.connect(self._mouse_select)
        # Selected non-volume modes capture dial turns globally. Volume mode
        # deliberately leaves raw endpoint changes untouched.
        self.volume_source.set_active(self._rotation_capture_needed())

    def _mode_label(self) -> str:
        mode = self.modes.get(self.current_mode, {})
        return str(mode.get("label", self.current_mode or "None"))

    def _rotation_capture_needed(self) -> bool:
        mode = self.modes.get(self.current_mode, {})
        return self.is_open or not bool(mode.get("passthrough_volume", False))

    def _sync_rotation_capture(self) -> None:
        self.volume_source.set_active(self._rotation_capture_needed())

    def apply_config(self, config: dict[str, Any]) -> None:
        """Apply saved settings without restarting the media-button listener."""
        self.config = config
        self.modes = config.get("modes", {})
        self.open_select_events = set(config["wheel"].get("open_select_events", ["PLAY", "PAUSE", "PLAY_PAUSE"]))
        self.next_events = set(config["wheel"].get("next_events", ["NEXT"]))
        self.previous_events = set(config["wheel"].get("previous_events", ["PREVIOUS"]))
        self.cancel_events = set(config["wheel"].get("cancel_events", ["STOP"]))
        self.wheel.set_items(visible_wheel_items(config))
        self.wheel.set_position(str(config["wheel"].get("position", "bottom-center")))
        self.wheel.set_brand_name(str(config.get("app_name", "Cinder")))
        self.last_selected_item_id = str(config["wheel"].get("last_selected_item_id", self.last_selected_item_id) or "")
        saved_mode = str(config["wheel"].get("last_active_mode", self.current_mode) or self.current_mode)
        if saved_mode in self.modes:
            self.current_mode = saved_mode
        elif self.current_mode not in self.modes:
            self.current_mode = str(config.get("default_mode", "volume"))
        self.wheel.set_active_mode(self._mode_label())
        self.runner.config = config
        self._sync_rotation_capture()
        log("Settings applied. Updated wheel items and actions are ready.")

    def _poll(self) -> None:
        for _ in range(80):
            try:
                kind, payload = self.event_queue.get_nowait()
            except queue.Empty:
                return
            if kind == "button":
                self._button(str(payload))
            elif kind == "rotate":
                delta = int(payload)
                if self.is_open:
                    self._move(delta)
                else:
                    self._run_mode_turn(delta)

    def _button(self, event_name: str) -> None:
        log(f"Event received: {event_name}")
        if event_name in self.open_select_events:
            if self.is_open:
                self._select()
            else:
                self._open()
            return
        if event_name in self.cancel_events and self.is_open:
            self._close()
            log("Wheel cancelled; active mode kept.")
            return
        if event_name in self.next_events and self.is_open:
            self._move(1)
            return
        if event_name in self.previous_events and self.is_open:
            self._move(-1)
            return
        # Outside the wheel, double/triple-press events retain their configured
        # button mappings (the default is next/previous media track). Dial turns
        # themselves are handled separately by _run_mode_turn.
        self.runner.enqueue_event(event_name)

    def _open(self) -> None:
        if not self.wheel.items:
            log("Wheel has no items in config.json.")
            return
        self.is_open = True
        self.wheel.set_active_mode(self._mode_label())
        # Restore the last selected tile. If it was removed or disabled, focus
        # the active mode's tile so the wheel remains context-aware.
        selected_index = next(
            (i for i, item in enumerate(self.wheel.items)
             if str(item.get("id", "")) == self.last_selected_item_id),
            -1,
        )
        if selected_index < 0:
            selected_index = next(
                (i for i, item in enumerate(self.wheel.items)
                 if item.get("kind") == "mode" and item.get("mode") == self.current_mode),
                0,
            )
        self.wheel.set_selected(selected_index)
        self.wheel.show_at_cursor()
        self._sync_rotation_capture()
        log(f"Wheel opened. Active mode is '{self._mode_label()}'; selection restored to '{self.wheel.items[self.wheel.selected_index].get('label', 'Action')}'. Rotate to browse; press to select.")

    def _close(self) -> None:
        self.is_open = False
        self.wheel.hide_animated()
        self._sync_rotation_capture()

    def _move(self, delta: int) -> None:
        self.wheel.move_selected(delta)
        item = self.wheel.items[self.wheel.selected_index]
        log(f"Wheel selection: {item.get('label', 'Action')}")

    def _persist_wheel_selection(self, item_id: str, active_mode: str | None = None) -> None:
        """Remember the selected tile/mode across wheel openings and app restarts."""
        item_id = str(item_id or "")
        self.last_selected_item_id = item_id
        wheel_cfg = self.config.setdefault("wheel", {})
        wheel_cfg["last_selected_item_id"] = item_id
        if active_mode and active_mode in self.modes:
            wheel_cfg["last_active_mode"] = active_mode
        try:
            temp_path = CONFIG_PATH.with_suffix(".json.tmp")
            temp_path.write_text(json.dumps(self.config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temp_path, CONFIG_PATH)
        except OSError as exc:
            log(f"Could not persist last wheel selection: {exc}")

    def _select(self) -> None:
        if not self.is_open:
            return
        index = self.wheel.selected_index
        self.wheel.pop_selected()
        item = self.wheel.items[index]
        label = str(item.get("label", "Action"))
        item_id = str(item.get("id", ""))
        kind = str(item.get("kind", "action")).lower()

        if kind == "mode":
            mode_name = str(item.get("mode", ""))
            if mode_name not in self.modes:
                log(f"Cannot activate unknown mode {mode_name!r}; check config.json.")
                self._close()
                return
            self.current_mode = mode_name
            self._persist_wheel_selection(item_id, active_mode=mode_name)
            self.wheel.set_active_mode(self._mode_label())
            self._close()
            mode = self.modes[mode_name]
            positive = str(mode.get("positive_label", "next action"))
            negative = str(mode.get("negative_label", "previous action"))
            log(f"Active mode: {self._mode_label()} | dial up: {positive} | dial down: {negative}.")
            return

        if kind in {"settings", "tutorial"}:
            self._persist_wheel_selection(item_id)
        if kind == "settings":
            self._close()
            self.open_settings_callback()
            return
        if kind == "tutorial":
            self._close()
            self.open_tutorial_callback()
            return

        self._persist_wheel_selection(item_id)
        actions = item.get("actions", [])
        self._close()
        log(f"Selected shortcut: {label} (active mode remains '{self._mode_label()}').")
        self.runner.enqueue_actions(actions, label)

    def _run_mode_turn(self, delta: int) -> None:
        mode = self.modes.get(self.current_mode, {})
        if not mode or mode.get("passthrough_volume", False):
            return
        direction = "positive" if delta > 0 else "negative"
        actions = mode.get(f"{direction}_actions", [])
        if not actions:
            log(f"Mode '{self._mode_label()}' has no {direction} action configured.")
            return
        description = str(mode.get(f"{direction}_label", direction.title()))
        log(f"Dial {'up' if delta > 0 else 'down'}: {description} ({self._mode_label()})")
        self.runner.enqueue_actions(actions, f"{self._mode_label()}: {description}")

    def _mouse_select(self, index: int) -> None:
        if self.is_open:
            self.wheel.set_selected(index)
            self._select()


class UIBridge(QObject):
    """Thread-safe bridge for updating overlays from action workers."""
    brightness_changed = Signal(int)
    dictation_requested = Signal()


# The WinRT imports are loaded in main so the script can print a helpful error
# if the Windows media-control packages are missing.
def make_tray_icon() -> QIcon:
    """Load the same branded icon for the tray and Windows app identity."""
    icon = app_icon()
    if not icon.isNull():
        return icon
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor("#6d303b"), 2))
    painter.setBrush(QColor("#171013"))
    painter.drawEllipse(7, 7, 50, 50)
    painter.setPen(QPen(QColor("#ef4e5d"), 5))
    painter.drawArc(17, 17, 30, 30, 25 * 16, 285 * 16)
    painter.setBrush(QColor("#ff8790"))
    painter.setPen(QPen(Qt.PenStyle.NoPen))
    painter.drawEllipse(28, 28, 8, 8)
    painter.end()
    return QIcon(pixmap)


def _apply_windows_startup(enabled: bool) -> None:
    """Register or remove Cinder's per-user Windows sign-in entry."""
    if sys.platform != "win32":
        return
    try:
        import winreg
        run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                if getattr(sys, "frozen", False):
                    command = f'"{Path(sys.executable).resolve()}" --background'
                else:
                    command = f'"{Path(sys.executable).resolve()}" "{Path(__file__).resolve()}" --background'
                winreg.SetValueEx(key, "Cinder", 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, "Cinder")
                except FileNotFoundError:
                    pass
    except OSError as exc:
        log(f"Could not update the Windows startup setting: {exc}")


def main() -> int:
    global APP_NAME
    if sys.platform != "win32":
        print(f"Cinder v{APP_VERSION} only runs on Windows 10/11.")
        return 1

    try:
        from winrt.windows.foundation import Uri
        from winrt.windows.media import MediaPlaybackStatus, MediaPlaybackType, SystemMediaTransportControlsButton as Button
        from winrt.windows.media.core import MediaSource
        from winrt.windows.media.playback import MediaPlayer
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager  # noqa: F401
        import pycaw.pycaw  # noqa: F401
        import comtypes  # noqa: F401
    except ImportError as exc:
        print(f"{APP_NAME} dependencies are missing or incomplete.")
        print(r"Run: .\.venv\Scripts\python.exe -m pip install -r requirements.txt")
        print(f"Details: {exc}")
        return 2

    try:
        config = load_config()
    except (RuntimeError, OSError) as exc:
        print(exc)
        return 3

    APP_NAME = " ".join(str(config.get("app_name", "Cinder")).strip().split())[:24] or "Cinder"
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)

    # Re-launching the desktop/start-menu shortcut should open the existing
    # launcher instead of spawning a second dial listener.
    instance_name = "Cinder_SmartDial_Launcher"
    instance_client = QLocalSocket()
    instance_client.connectToServer(instance_name)
    if instance_client.waitForConnected(250):
        if "--launcher" in sys.argv:
            instance_client.write(b"launcher")
            instance_client.flush()
            instance_client.waitForBytesWritten(500)
        instance_client.disconnectFromServer()
        return 0
    instance_server = QLocalServer()
    if not instance_server.listen(instance_name):
        QLocalServer.removeServer(instance_name)
        if not instance_server.listen(instance_name):
            log("Could not reserve the single-instance launcher channel; continuing without it.")

    brightness_osd = BrightnessOSD()
    dictation_overlay = DictationOverlay()
    dictation_overlay.set_brand_name(APP_NAME)
    dictation_cfg = config.get("dictation", {}) if isinstance(config.get("dictation", {}), dict) else {}
    dictation_overlay.set_input_device(
        str(dictation_cfg.get("input_device_name", "") or ""),
        str(dictation_cfg.get("input_hostapi_name", "") or ""),
    )
    dictation_overlay.set_transcription_options(
        str(dictation_cfg.get("model_size", "base") or "base"),
        str(dictation_cfg.get("language", "en") or "en"),
    )
    ui_bridge = UIBridge()
    ui_bridge.brightness_changed.connect(brightness_osd.show_level, Qt.ConnectionType.QueuedConnection)
    ui_bridge.dictation_requested.connect(dictation_overlay.start_dictation, Qt.ConnectionType.QueuedConnection)
    make_silence(SILENCE_PATH)

    # A silent, local media session is used only to receive the earbuds' media-button events.
    player = MediaPlayer()
    player.command_manager.is_enabled = False
    player.volume = 0.0
    controls = player.system_media_transport_controls
    controls.is_enabled = True
    controls.is_play_enabled = True
    controls.is_pause_enabled = True
    controls.is_next_enabled = True
    controls.is_previous_enabled = True
    controls.is_stop_enabled = True
    display = controls.display_updater
    display.type = MediaPlaybackType.MUSIC
    display.music_properties.title = APP_NAME
    display.music_properties.artist = "Cinder Smart Dial controller"
    display.update()

    button_names = {
        value: name for name, value in vars(Button).items()
        if not name.startswith("_") and isinstance(value, int)
    }
    event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
    event_count = 0

    def on_button_pressed(_sender: Any, args: Any) -> None:
        nonlocal event_count
        event_count += 1
        name = button_names.get(args.button, f"UNKNOWN_{args.button}")
        event_queue.put(("button", name))

    token = controls.add_button_pressed(on_button_pressed)
    player.source = MediaSource.create_from_uri(Uri(SILENCE_PATH.resolve().as_uri()))
    player.is_looping_enabled = True
    controls.playback_status = MediaPlaybackStatus.PLAYING
    player.play()

    runner = ActionRunner(
        config,
        brightness_changed=ui_bridge.brightness_changed.emit,
        dictation_requested=ui_bridge.dictation_requested.emit,
    )
    wheel = ControlWheel(visible_wheel_items(config), str(config["wheel"].get("position", "bottom-center")))
    wheel.setWindowIcon(app_icon())
    wheel.set_brand_name(APP_NAME)
    wheel.set_animations_enabled(bool(config.get("preferences", {}).get("wheel_animations", True)))
    volume_source = VolumeRotationSource(
        config["wheel"].get("device_name_contains", "buds pro 2"),
        lambda direction: event_queue.put(("rotate", direction)),
    )
    volume_source.start()

    config_holder: dict[str, dict[str, Any]] = {"config": config}
    ui_holder: dict[str, Any] = {"settings": None, "controller": None}

    def apply_saved_config(new_config: dict[str, Any]) -> None:
        global APP_NAME
        config_holder["config"] = new_config
        APP_NAME = " ".join(str(new_config.get("app_name", "Cinder")).strip().split())[:24] or "Cinder"
        app.setApplicationName(APP_NAME)
        controller = ui_holder.get("controller")
        if controller is not None:
            controller.apply_config(new_config)
        wheel.set_brand_name(APP_NAME)
        wheel.set_animations_enabled(bool(new_config.get("preferences", {}).get("wheel_animations", True)))
        _apply_windows_startup(bool(new_config.get("preferences", {}).get("start_with_windows", False)))
        dictation_overlay.set_brand_name(APP_NAME)
        dictation_cfg = new_config.get("dictation", {}) if isinstance(new_config.get("dictation", {}), dict) else {}
        dictation_overlay.set_input_device(
            str(dictation_cfg.get("input_device_name", "") or ""),
            str(dictation_cfg.get("input_hostapi_name", "") or ""),
        )
        dictation_overlay.set_transcription_options(
            str(dictation_cfg.get("model_size", "base") or "base"),
            str(dictation_cfg.get("language", "en") or "en"),
        )
        chosen_mic = str(dictation_cfg.get("input_device_name", "") or "System default microphone")
        log(f"Dictation microphone set to: {chosen_mic}; model={dictation_cfg.get('model_size', 'base')}; language={dictation_cfg.get('language', 'en')}")
        try:
            display.music_properties.title = APP_NAME
            display.update()
        except Exception:
            pass
        tray_obj = ui_holder.get("tray")
        if tray_obj is not None:
            tray_obj.setToolTip(f"{APP_NAME} · Smart Dial Controller")
        quit_action_obj = ui_holder.get("quit_action")
        if quit_action_obj is not None:
            quit_action_obj.setText(f"Quit {APP_NAME}")
        log(f"App name updated to {APP_NAME}.")

    def show_settings() -> None:
        window = ui_holder.get("settings")
        if window is None:
            window = SettingsWindow(
                config_holder["config"], CONFIG_PATH, apply_saved_config,
                open_wheel=lambda: ui_holder["controller"]._open() if ui_holder.get("controller") is not None else None,
            )
            window.launch_tile_requested.connect(
                lambda payload: runner.enqueue_actions(payload.get("actions", []), str(payload.get("label", "Launcher shortcut")))
            )
            ui_holder["settings"] = window
        window.showNormal()
        window.raise_()
        window.activateWindow()

    def handle_instance_connections() -> None:
        while instance_server.hasPendingConnections():
            client = instance_server.nextPendingConnection()
            if client is None:
                continue
            def read_command(sock=client) -> None:
                try:
                    command = bytes(sock.readAll()).decode("utf-8", errors="ignore").strip()
                    if command == "launcher":
                        show_settings()
                    sock.disconnectFromServer()
                except RuntimeError:
                    pass
            client.readyRead.connect(read_command)
            if client.bytesAvailable():
                read_command()

    instance_server.newConnection.connect(handle_instance_connections)

    def show_tutorial() -> None:
        show_settings()
        window = ui_holder.get("settings")
        if window is not None:
            window.show_tutorial()

    controller = InputController(config, wheel, runner, volume_source, event_queue,
                                 open_settings=show_settings, open_tutorial=show_tutorial)
    ui_holder["controller"] = controller

    # Windows tray menu provides a fallback entry point if the physical dial is not nearby.
    tray = QSystemTrayIcon(make_tray_icon(), app)
    tray.setToolTip(f"{APP_NAME} · Smart Dial Controller")
    tray_menu = QMenu()
    open_wheel_action = tray_menu.addAction("Open control wheel")
    open_wheel_action.triggered.connect(controller._open)
    settings_action = tray_menu.addAction("Open Cinder launcher")
    settings_action.triggered.connect(show_settings)
    tutorial_action = tray_menu.addAction("Tutorial")
    tutorial_action.triggered.connect(show_tutorial)
    tray_menu.addSeparator()
    quit_action = tray_menu.addAction(f"Quit {APP_NAME}")
    quit_action.triggered.connect(app.quit)
    tray.setContextMenu(tray_menu)
    ui_holder["tray"] = tray
    ui_holder["quit_action"] = quit_action
    tray.activated.connect(
        lambda reason: show_settings() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
    )
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray.show()
    else:
        log("Windows system tray is unavailable; use the Smart Dial's Settings tile to open settings.")

    _apply_windows_startup(bool(config.get("preferences", {}).get("start_with_windows", False)))
    if "--launcher" in sys.argv:
        show_settings()

    print(f"\n{APP_NAME} v{APP_VERSION} is running.")
    print(f"Config: {CONFIG_PATH}")
    print("Tap to open the animated crimson wheel; turn to browse; tap to select.")
    print(f"Active rotation mode: {controller._mode_label()}")
    print(f"Settings: right-click the {APP_NAME} tray icon -> Settings, or select Settings in the wheel.")
    print("Custom apps: Settings -> Apps & shortcuts -> Add application / Add website / Add shortcut.")
    print("Dictation uses local faster-whisper recognition; first use downloads the selected model once to Local AppData.")
    print("For dictation, focus a text field first, record, stop, then choose Insert text.")
    print("Press Ctrl+C in this terminal to stop.\n", flush=True)

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal_timer = QTimer()
    signal_timer.start(250)
    signal_timer.timeout.connect(lambda: None)

    exit_code = app.exec()
    controller.timer.stop()
    controller._close()
    dictation_overlay.shutdown()
    volume_source.stop()
    runner.close()
    tray.hide()
    if instance_server.isListening():
        instance_server.close()
        QLocalServer.removeServer("Cinder_SmartDial_Launcher")
    try:
        controls.remove_button_pressed(token)
    except Exception:
        pass
    try:
        player.pause()
        player.source = None
        player.close()
    except Exception:
        pass
    log(f"Stopped. Button events received: {event_count}")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
