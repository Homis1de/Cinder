"""Cinder settings, custom tile management, and built-in tutorial."""
from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from cinder_brand import APP_ICON_PNG_PATH, APP_VERSION, app_icon

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStyle,
    QFileIconProvider,
    QInputDialog,
    QVBoxLayout,
    QWidget,
)


STYLE = """
QDialog { background: #0e0f12; color: #f1edef; font-family: 'Segoe UI'; font-size: 9pt; }
QWidget { color: #f1edef; font-family: 'Segoe UI'; font-size: 9pt; background: transparent; }
QLabel { background: transparent; border: none; }
QLabel#heroTitle { font-size: 22pt; font-weight: 760; color: #fffafb; }
QLabel#subtle { color: #a9a2a6; }
QLabel#sectionTitle { font-size: 10.5pt; font-weight: 700; color: #faf4f5; }
QLabel#eyebrow { color: #f47783; font-size: 8pt; font-weight: 800; letter-spacing: 1.25px; }
QLabel#brandMark { background: #111216; border: 1px solid #33242a; border-radius: 12px; }
QLabel#localStatus { color: #d9bfc3; background: #1a1518; border: 1px solid #38272c; border-radius: 8px; padding: 7px 10px; font-size: 8pt; font-weight: 700; }
QPushButton#navButton { background: transparent; color: #aaa7ad; text-align: left; min-height: 25px; padding: 12px 13px; border: 1px solid transparent; border-radius: 10px; font-weight: 650; }
QPushButton#navButton:checked { background: #312027; color: #fff7f8; border: 1px solid #77404a; }
QPushButton#navButton:hover:!checked { background: #1d1e23; color: #fff7f8; border-color: #303138; }
QPushButton { background: #242328; color: #f4edef; border: 1px solid #37343b; border-radius: 9px; padding: 9px 13px; font-weight: 650; }
QPushButton:hover { background: #30272c; border-color: #70414a; }
QPushButton:pressed { background: #21191d; }
QPushButton#primary { background: #cf4655; border-color: #e35a68; color: #fffafb; }
QPushButton#primary:hover { background: #df5362; }
QPushButton#quiet { background: #17181c; border-color: #303137; color: #d7d0d3; }
QPushButton#quiet:hover { background: #242328; }
QLineEdit, QComboBox, QListWidget { background: #111216; color: #faf5f6; border: 1px solid #303138; border-radius: 9px; padding: 9px 11px; selection-background-color: #70303a; }
QLineEdit:focus, QComboBox:focus, QListWidget:focus { border: 1px solid #cd4c5b; }
QComboBox QAbstractItemView { background: #18191e; selection-background-color: #70303a; color: #fff3f5; border: 1px solid #38343b; outline: 0; }
QCheckBox { spacing: 9px; color: #f0eaec; }
QCheckBox::indicator { width: 16px; height: 16px; }
QCheckBox::indicator:unchecked { border: 1px solid #5d565c; background: #151519; border-radius: 5px; }
QCheckBox::indicator:checked { border: 1px solid #f47783; background: #cd4655; border-radius: 5px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #111216; width: 7px; margin: 3px; border-radius: 3px; }
QScrollBar::handle:vertical { background: #4a4249; min-height: 26px; border-radius: 3px; }
QScrollBar::handle:vertical:hover { background: #8e4f5a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QFrame#card { background: #17181d; border: 1px solid #2b2c33; border-radius: 14px; }
QFrame#sidebar { background: #111216; border: 1px solid #26262d; border-radius: 15px; }
QFrame#pageSurface { background: #101115; border: 1px solid #26262d; border-radius: 15px; }
QLabel#navCaption { color: #77727a; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }
QFrame#featureRow { background: #17181d; border: 1px solid #2b2c33; border-radius: 11px; }
QFrame#headerRule { background: #24242a; max-height: 1px; }
QListWidget::item { padding: 10px 8px; border-bottom: 1px solid #29292f; }
QListWidget::item:selected { background: #302025; border-radius: 7px; color: #fff7f8; }
"""


VALID_KEYS = {
    "BACKSPACE", "TAB", "ENTER", "SHIFT", "CTRL", "CONTROL", "ALT", "PAUSE", "CAPSLOCK",
    "ESC", "SPACE", "PAGEUP", "PAGEDOWN", "END", "HOME", "LEFT", "UP", "RIGHT", "DOWN",
    "PRINTSCREEN", "INSERT", "DELETE", "WIN", "VOLUME_MUTE", "VOLUME_DOWN", "VOLUME_UP",
    "EQUALS", "PLUS", "MINUS", "BACKTICK", "MEDIA_NEXT", "MEDIA_PREVIOUS", "MEDIA_STOP",
    "MEDIA_PLAY_PAUSE",
}
VALID_KEYS.update({f"F{i}" for i in range(1, 25)})
VALID_KEYS.update("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


class _MicTestSignals(QObject):
    finished = Signal(str)


def _card(title: str, description: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 11, 14, 11)
    layout.setSpacing(4)
    heading = QLabel(title)
    heading.setObjectName("sectionTitle")
    body = QLabel(description)
    body.setObjectName("subtle")
    body.setWordWrap(True)
    layout.addWidget(heading)
    layout.addWidget(body)
    return frame


class SettingsWindow(QDialog):
    """Cinder launcher and shared settings window."""

    launch_tile_requested = Signal(dict)

    def __init__(self, config: dict[str, Any], config_path: Path,
                 on_saved: Callable[[dict[str, Any]], None], open_wheel: Callable[[], None] | None = None, parent=None):
        super().__init__(parent)
        self.config = copy.deepcopy(config)
        self.config_path = config_path
        self.on_saved = on_saved
        self.open_wheel_callback = open_wheel or (lambda: None)
        self._feature_checks: dict[str, QCheckBox] = {}
        self._position_combo: QComboBox | None = None
        self._mic_combo: QComboBox | None = None
        self._mic_test_button: QPushButton | None = None
        self._mic_test_status: QLabel | None = None
        self._dictation_model_combo: QComboBox | None = None
        self._dictation_language_combo: QComboBox | None = None
        self._mic_test_signals = _MicTestSignals()
        self._mic_test_signals.finished.connect(self._on_mic_test_finished)
        self._app_name_edit: QLineEdit | None = None
        self._pages: dict[str, QWidget] = {}
        self._page_builders: dict[str, Callable[[], QWidget]] = {}
        self._nav_buttons: dict[str, QPushButton] = {}
        self._page_animations: dict[str, QPropertyAnimation] = {}
        self._start_with_windows_check: QCheckBox | None = None
        self._close_to_tray_check: QCheckBox | None = None
        self._animations_check: QCheckBox | None = None
        self._icon_provider = QFileIconProvider()

        brand = str(self.config.get("app_name", "Cinder") or "Cinder").strip() or "Cinder"
        self.setWindowTitle(f"{brand} Launcher")
        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowCloseButtonHint)
        self.setMinimumSize(800, 560)
        self.setMaximumSize(1180, 860)
        self.resize(980, 680)
        self.setStyleSheet(STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 15)
        root.setSpacing(13)

        header = QHBoxLayout()
        header.setSpacing(12)
        brand_mark = QLabel()
        brand_mark.setObjectName("brandMark")
        brand_mark.setFixedSize(54, 54)
        if APP_ICON_PNG_PATH.is_file():
            brand_mark.setPixmap(QPixmap(str(APP_ICON_PNG_PATH)).scaled(46, 46, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        eyebrow = QLabel(f"CINDER  /  LAUNCHER  /  v{APP_VERSION}")
        eyebrow.setObjectName("eyebrow")
        title = QLabel(brand)
        title.setObjectName("heroTitle")
        self._hero_title = title
        subtitle = QLabel("Your dial, controls and shortcuts in one place.")
        subtitle.setObjectName("subtle")
        title_col.addWidget(eyebrow)
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addWidget(brand_mark, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addLayout(title_col, 1)
        self.open_wheel_button = QPushButton("Open wheel  ↗")
        self.open_wheel_button.setObjectName("primary")
        self.open_wheel_button.setMinimumHeight(40)
        self.open_wheel_button.clicked.connect(self.open_wheel_callback)
        header.addWidget(self.open_wheel_button, 0, Qt.AlignmentFlag.AlignVCenter)
        status = QLabel("●  SAVED LOCALLY")
        status.setObjectName("localStatus")
        header.addWidget(status, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(header)

        rule = QFrame()
        rule.setObjectName("headerRule")
        rule.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(rule)

        self._page_builders = {
            "overview": self._build_overview_tab,
            "controls": self._build_features_tab,
            "apps": self._build_apps_tab,
            "dictation": self._build_dictation_tab,
            "tutorial": self._build_tutorial_tab,
        }
        body = QHBoxLayout()
        body.setSpacing(13)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(205)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(9, 14, 9, 12)
        side_layout.setSpacing(5)
        nav_caption = QLabel("WORKSPACE")
        nav_caption.setObjectName("navCaption")
        nav_caption.setContentsMargins(10, 2, 4, 8)
        side_layout.addWidget(nav_caption)
        nav_specs = [
            ("overview", "⌂   Overview"),
            ("controls", "◈   Wheel controls"),
            ("apps", "▦   Apps & shortcuts"),
            ("dictation", "◖   Dictation"),
            ("tutorial", "ⓘ   Help & setup"),
        ]
        for key, label in nav_specs:
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setMinimumHeight(43)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.clicked.connect(lambda checked=False, page_key=key: self._select_page(page_key))
            side_layout.addWidget(button)
            self._nav_buttons[key] = button
        side_layout.addStretch(1)
        side_bottom = QLabel("CINDER  ·  LOCAL\nWindows companion")
        side_bottom.setObjectName("subtle")
        side_bottom.setContentsMargins(10, 10, 5, 2)
        side_layout.addWidget(side_bottom)
        body.addWidget(sidebar)

        self.tabs = QStackedWidget()
        self.tabs.setObjectName("settingsPages")
        self.tabs.setMinimumWidth(0)
        body.addWidget(self.tabs, 1)
        root.addLayout(body, 1)
        self._select_page("overview")

        footer = QHBoxLayout()
        footer_note = QLabel("Settings are stored on this PC · config.json")
        footer_note.setObjectName("subtle")
        footer.addWidget(footer_note, 1)
        hide_btn = QPushButton("Hide to tray")
        hide_btn.setObjectName("quiet")
        hide_btn.clicked.connect(self.hide)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self.save_config)
        save_btn = QPushButton("Save changes")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self.save_config)
        footer.addWidget(hide_btn)
        footer.addWidget(apply_btn)
        footer.addWidget(save_btn)
        root.addLayout(footer)

    def _select_page(self, key: str) -> None:
        if key not in self._page_builders:
            return
        page = self._pages.get(key)
        if page is None:
            # Lazily build content the first time it is requested.
            page = self._page_builders[key]()
            self._pages[key] = page
            self.tabs.addWidget(page)
        self.tabs.setCurrentWidget(page)
        for nav_key, button in self._nav_buttons.items():
            button.setChecked(nav_key == key)
        if bool(self.config.get("preferences", {}).get("wheel_animations", True)):
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            effect = page.graphicsEffect()
            if not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect(page)
                page.setGraphicsEffect(effect)
            animation = self._page_animations.get(key)
            if animation is None:
                animation = QPropertyAnimation(effect, b"opacity", page)
                animation.setDuration(135)
                animation.setEasingCurve(QEasingCurve.Type.OutCubic)
                self._page_animations[key] = animation
            animation.stop()
            effect.setOpacity(0.78)
            animation.setStartValue(0.78)
            animation.setEndValue(1.0)
            animation.start()

    def _preview_brand_name(self, value: str) -> None:
        """Preview the editable branding without saving until Apply is pressed."""
        brand = " ".join(str(value).strip().split())[:24] or "Cinder"
        self._hero_title.setText(brand)
        self.setWindowTitle(f"{brand} Launcher")

    def _build_overview_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(11)

        layout.addWidget(_card(
            "Wheel setup",
            "Choose where the wheel opens, enable the controls you use, and add your own apps or shortcuts. Settings are stored in config.json on this PC.",
        ))

        branding = QFrame()
        branding.setObjectName("card")
        brand_layout = QVBoxLayout(branding)
        brand_layout.setContentsMargins(16, 14, 16, 14)
        brand_layout.setSpacing(6)
        brand_label = QLabel("App name")
        brand_label.setObjectName("sectionTitle")
        brand_desc = QLabel("Change the name shown in the wheel, settings and system tray.")
        brand_desc.setObjectName("subtle")
        brand_desc.setWordWrap(True)
        self._app_name_edit = QLineEdit(str(self.config.get("app_name", "Cinder") or "Cinder"))
        self._app_name_edit.setMaxLength(24)
        self._app_name_edit.setPlaceholderText("Choose a name")
        self._app_name_edit.textChanged.connect(self._preview_brand_name)
        brand_layout.addWidget(brand_label)
        brand_layout.addWidget(brand_desc)
        brand_layout.addWidget(self._app_name_edit)
        layout.addWidget(branding)

        position_card = QFrame()
        position_card.setObjectName("card")
        pos_layout = QVBoxLayout(position_card)
        pos_layout.setContentsMargins(16, 14, 16, 14)
        pos_layout.setSpacing(6)
        lbl = QLabel("Wheel position")
        lbl.setObjectName("sectionTitle")
        desc = QLabel("Choose where the wheel opens. Bottom centre keeps it above the taskbar.")
        desc.setObjectName("subtle")
        desc.setWordWrap(True)
        self._position_combo = QComboBox()
        self._position_combo.addItem("Bottom centre · above taskbar", "bottom-center")
        self._position_combo.addItem("Centre of screen", "screen-center")
        current = self.config.get("wheel", {}).get("position", "bottom-center")
        index = self._position_combo.findData(current)
        self._position_combo.setCurrentIndex(index if index >= 0 else 0)
        pos_layout.addWidget(lbl)
        pos_layout.addWidget(desc)
        pos_layout.addWidget(self._position_combo)
        layout.addWidget(position_card)

        preferences_card = QFrame()
        preferences_card.setObjectName("card")
        pref_layout = QVBoxLayout(preferences_card)
        pref_layout.setContentsMargins(16, 14, 16, 14)
        pref_layout.setSpacing(9)
        pref_heading = QLabel("Launcher & startup")
        pref_heading.setObjectName("sectionTitle")
        pref_desc = QLabel("Choose how Cinder behaves when you sign in or close the launcher.")
        pref_desc.setObjectName("subtle")
        pref_desc.setWordWrap(True)
        pref_layout.addWidget(pref_heading)
        pref_layout.addWidget(pref_desc)
        prefs = self.config.get("preferences", {}) if isinstance(self.config.get("preferences", {}), dict) else {}
        self._start_with_windows_check = QCheckBox("Start Cinder when I sign in to Windows")
        self._start_with_windows_check.setChecked(bool(prefs.get("start_with_windows", False)))
        self._close_to_tray_check = QCheckBox("Keep Cinder running when I close the launcher")
        self._close_to_tray_check.setChecked(bool(prefs.get("close_to_tray", True)))
        self._animations_check = QCheckBox("Use subtle animations in the wheel and launcher")
        self._animations_check.setChecked(bool(prefs.get("wheel_animations", True)))
        pref_layout.addWidget(self._start_with_windows_check)
        pref_layout.addWidget(self._close_to_tray_check)
        pref_layout.addWidget(self._animations_check)
        layout.addWidget(preferences_card)

        layout.addWidget(_card(
            "Quick start",
            "Tap the Smart Dial to open the wheel, rotate to browse and tap to choose. Control modes stay active until you select another mode; app and shortcut tiles run once.",
        ))
        layout.addWidget(_card(
            "Local data",
            "Settings and custom tiles stay in config.json. Dictation runs on this PC after the speech model has been downloaded.",
        ))
        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return tab

    def _build_dictation_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(11)
        layout.addWidget(_card(
            "Local voice input",
            "Choose the microphone you actually speak into, run a quick level test, then tune recognition speed and language. The first dictation downloads the selected model once; decoding stays on this PC.",
        ))

        mic_card = QFrame()
        mic_card.setObjectName("card")
        mic_layout = QVBoxLayout(mic_card)
        mic_layout.setContentsMargins(16, 14, 16, 14)
        mic_layout.setSpacing(8)
        mic_title = QLabel("Input device")
        mic_title.setObjectName("sectionTitle")
        mic_desc = QLabel("Bluetooth headphones may expose more than one endpoint. Test each CMF Buds Pro 2 option and keep the one that captures your voice clearly.")
        mic_desc.setObjectName("subtle")
        mic_desc.setWordWrap(True)
        self._mic_combo = QComboBox()
        self._populate_microphone_combo()
        mic_actions = QHBoxLayout()
        mic_actions.setSpacing(10)
        self._mic_test_button = QPushButton("Test microphone · 3 sec")
        self._mic_test_button.setObjectName("quiet")
        self._mic_test_button.clicked.connect(self._test_selected_microphone)
        self._mic_test_status = QLabel("Select a device, then speak normally during the test.")
        self._mic_test_status.setObjectName("subtle")
        self._mic_test_status.setWordWrap(True)
        mic_actions.addWidget(self._mic_test_button)
        mic_actions.addWidget(self._mic_test_status, 1)
        mic_layout.addWidget(mic_title)
        mic_layout.addWidget(mic_desc)
        mic_layout.addWidget(self._mic_combo)
        mic_layout.addLayout(mic_actions)

        quality_row = QHBoxLayout()
        quality_row.setSpacing(12)
        model_col = QVBoxLayout()
        model_col.setSpacing(5)
        model_label = QLabel("Recognition speed")
        model_label.setObjectName("sectionTitle")
        self._dictation_model_combo = QComboBox()
        self._dictation_model_combo.addItem("Base · faster on CPU (recommended)", "base")
        self._dictation_model_combo.addItem("Small · higher accuracy, slower", "small")
        dict_cfg = self.config.get("dictation", {}) if isinstance(self.config.get("dictation", {}), dict) else {}
        model_idx = self._dictation_model_combo.findData(str(dict_cfg.get("model_size", "base")).lower())
        self._dictation_model_combo.setCurrentIndex(model_idx if model_idx >= 0 else 0)
        model_col.addWidget(model_label)
        model_col.addWidget(self._dictation_model_combo)

        language_col = QVBoxLayout()
        language_col.setSpacing(5)
        language_label = QLabel("Spoken language")
        language_label.setObjectName("sectionTitle")
        self._dictation_language_combo = QComboBox()
        for text, code in (("English", "en"), ("Auto-detect", "auto"), ("Hindi", "hi"), ("Bengali", "bn")):
            self._dictation_language_combo.addItem(text, code)
        lang_idx = self._dictation_language_combo.findData(str(dict_cfg.get("language", "en")).lower())
        self._dictation_language_combo.setCurrentIndex(lang_idx if lang_idx >= 0 else 0)
        language_col.addWidget(language_label)
        language_col.addWidget(self._dictation_language_combo)
        quality_row.addLayout(model_col, 1)
        quality_row.addLayout(language_col, 1)
        mic_layout.addSpacing(3)
        mic_layout.addLayout(quality_row)
        quality_note = QLabel("Base is the faster default. Small trades speed and memory for possible accuracy gains. For short clips, selecting the language you are speaking is usually more reliable than auto-detect.")
        quality_note.setObjectName("subtle")
        quality_note.setWordWrap(True)
        mic_layout.addWidget(quality_note)
        mic_card.layout().setContentsMargins(16, 14, 16, 14)
        layout.addWidget(mic_card)
        layout.addWidget(_card(
            "Dictation workflow",
            "Focus a text field first. Open Dictation, speak, choose Stop & transcribe, review the result, then select Insert text. If the model is still downloading, the status shows the current stage and elapsed time.",
        ))
        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return tab

    def _populate_microphone_combo(self) -> None:
        """List available recording inputs, keeping host-API variants distinct."""
        combo = self._mic_combo
        if combo is None:
            return
        combo.clear()
        combo.addItem("System default microphone", {"name": "", "hostapi_name": ""})
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            seen: set[tuple[str, str]] = set()
            for index, info in enumerate(devices):
                if int(info.get("max_input_channels", 0)) < 1:
                    continue
                raw_name = str(info.get("name", "")).strip()
                lowered = raw_name.casefold()
                # Hide PortAudio wrapper aliases; keep real device endpoints.
                if any(alias in lowered for alias in ("microsoft sound mapper", "primary sound capture driver", "stereo mix")):
                    continue
                api_index = int(info.get("hostapi", -1))
                api_name = str(hostapis[api_index].get("name", "Unknown API")) if 0 <= api_index < len(hostapis) else "Unknown API"
                identity = (raw_name.casefold(), api_name.casefold())
                if identity in seen:
                    continue
                seen.add(identity)
                if "cmf buds pro 2" in lowered:
                    if "hands-free" in lowered or "bthhfenum" in lowered:
                        display = "CMF Buds Pro 2 · Bluetooth hands-free"
                    else:
                        display = "CMF Buds Pro 2 · Headset microphone"
                else:
                    display = raw_name
                # Device number is informational only; the saved selection uses
                # device name + host API, not an unstable numeric index.
                combo.addItem(f"{display}  ·  {api_name}", {"name": raw_name, "hostapi_name": api_name})
        except Exception as exc:
            if self._mic_test_status is not None:
                self._mic_test_status.setText(f"Could not list microphones: {exc}")

        saved = self.config.get("dictation", {}) if isinstance(self.config.get("dictation", {}), dict) else {}
        saved_name = str(saved.get("input_device_name", "") or "").casefold()
        saved_api = str(saved.get("input_hostapi_name", "") or "").casefold()
        selected = 0
        if saved_name:
            for i in range(combo.count()):
                data = combo.itemData(i) or {}
                if str(data.get("name", "")).casefold() == saved_name and str(data.get("hostapi_name", "")).casefold() == saved_api:
                    selected = i
                    break
        else:
            # Cinder is designed around the CMF Smart Dial. On first launch,
            # prefer the Buds Pro 2 microphone if Windows exposes it, rather
            # than silently dictating from the often-distant laptop mic.
            earbuds = []
            for i in range(1, combo.count()):
                data = combo.itemData(i) or {}
                device_name = str(data.get("name", "")).casefold()
                api_name = str(data.get("hostapi_name", "")).casefold()
                if "cmf buds pro 2" in device_name:
                    rank = 0 if "wasapi" in api_name else 1 if "directsound" in api_name else 2 if "mme" in api_name else 3
                    earbuds.append((rank, i))
            if earbuds:
                selected = sorted(earbuds)[0][1]
        combo.setCurrentIndex(selected)

    def _test_selected_microphone(self) -> None:
        if self._mic_combo is None or self._mic_test_button is None:
            return
        selection = self._mic_combo.currentData() or {"name": "", "hostapi_name": ""}
        selection = dict(selection)
        self._mic_test_button.setEnabled(False)
        if self._mic_test_status is not None:
            self._mic_test_status.setText("Recording for 3 seconds… speak now.")
            self._mic_test_status.setStyleSheet("color: #e3c0c4;")

        def worker() -> None:
            try:
                import numpy as np
                import sounddevice as sd
                requested_name = str(selection.get("name", "") or "").strip()
                requested_api = str(selection.get("hostapi_name", "") or "").strip()
                devices = sd.query_devices()
                hostapis = sd.query_hostapis()
                device_index = None
                device_info = None
                if requested_name:
                    matches = []
                    for device_index_candidate, info in enumerate(devices):
                        if int(info.get("max_input_channels", 0)) < 1:
                            continue
                        if str(info.get("name", "")).casefold() != requested_name.casefold():
                            continue
                        api_index = int(info.get("hostapi", -1))
                        api_name = str(hostapis[api_index].get("name", "")) if 0 <= api_index < len(hostapis) else ""
                        matches.append((device_index_candidate, info, api_name))
                    chosen = next((m for m in matches if m[2].casefold() == requested_api.casefold()), matches[0] if matches else None)
                    if chosen is None:
                        raise RuntimeError(f"Microphone '{requested_name}' is no longer available. Reconnect it and reopen Settings.")
                    device_index, device_info, _api = chosen
                else:
                    default_index = sd.default.device[0]
                    if default_index is None or int(default_index) < 0:
                        raise RuntimeError("No default input device is set in Windows.")
                    device_index = int(default_index)
                    device_info = sd.query_devices(device_index)
                if int(device_info.get("max_input_channels", 0)) < 1:
                    raise RuntimeError("The selected device has no input channels.")
                rate = int(device_info.get("default_samplerate", 44100) or 44100)
                recording = sd.rec(int(rate * 3), samplerate=rate, channels=1, dtype="float32", device=device_index)
                sd.wait()
                peak = float(np.max(np.abs(recording))) if recording.size else 0.0
                rms = float(np.sqrt(np.mean(recording * recording))) if recording.size else 0.0
                label = str(device_info.get("name", "microphone"))
                if rms < 0.0005:
                    message = f"Very quiet input from {label} · peak {peak:.4f}, RMS {rms:.4f}. Try the other CMF endpoint (WASAPI/hands-free), check Windows mic access, then test again."
                else:
                    message = f"Mic test OK · {label} · peak {peak:.4f}, RMS {rms:.4f}."
            except Exception as exc:
                message = f"Microphone test failed: {exc}"
            self._mic_test_signals.finished.emit(message)

        threading.Thread(target=worker, name="CinderMicTest", daemon=True).start()

    def _on_mic_test_finished(self, message: str) -> None:
        if self._mic_test_button is not None:
            self._mic_test_button.setEnabled(True)
        if self._mic_test_status is not None:
            self._mic_test_status.setText(message)
            color = "#8be0af" if message.startswith("Mic test OK") else "#f0b3bb"
            self._mic_test_status.setStyleSheet(f"color: {color};")

    def _feature_description(self, item: dict[str, Any]) -> str:
        kind = str(item.get("kind", "action"))
        mode = self.config.get("modes", {}).get(item.get("mode", ""), {}) if kind == "mode" else {}
        if mode:
            return str(mode.get("description", "Turn the dial to run the assigned actions."))
        descriptions = {
            "dictation": "Local speech-to-text. Record, stop, review the transcription, then insert it into the previously focused app. Audio is processed on this PC.",
            "screenshot": "Capture a screenshot using the Windows shortcut.",
            "media_toggle": "Play or pause the active media session.",
            "settings": "Open this settings window.",
            "tutorial": "Show the built-in setup guide.",
        }
        return descriptions.get(str(item.get("id", "")), "Run this one-shot action from the wheel.")

    def _build_features_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)
        heading = QLabel("Wheel controls")
        heading.setObjectName("sectionTitle")
        desc = QLabel("Turn features on or off. Disabled tiles disappear from the wheel; the other controls remain available.")
        desc.setObjectName("subtle")
        desc.setWordWrap(True)
        root.addWidget(heading)
        root.addWidget(desc)

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        inner = QWidget()
        list_layout = QVBoxLayout(inner)
        list_layout.setContentsMargins(3, 3, 3, 3)
        list_layout.setSpacing(8)

        for item in self.config.get("wheel", {}).get("items", []):
            if not item.get("built_in", False):
                continue
            item_id = str(item.get("id", ""))
            row = QFrame()
            row.setObjectName("featureRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 9, 14, 9)
            icon = QLabel()
            icon.setFixedSize(34, 34)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            standard_icons = {
                "volume": QStyle.StandardPixmap.SP_MediaVolume,
                "undo_redo": QStyle.StandardPixmap.SP_ArrowBack,
                "tabs": QStyle.StandardPixmap.SP_FileDialogDetailedView,
                "windows": QStyle.StandardPixmap.SP_ComputerIcon,
                "zoom": QStyle.StandardPixmap.SP_DesktopIcon,
                "scroll": QStyle.StandardPixmap.SP_ArrowUp,
                "page_navigation": QStyle.StandardPixmap.SP_ArrowForward,
                "brightness": QStyle.StandardPixmap.SP_TitleBarShadeButton,
                "slides": QStyle.StandardPixmap.SP_MediaPlay,
                "dictation": QStyle.StandardPixmap.SP_MediaVolume,
                "screenshot": QStyle.StandardPixmap.SP_DesktopIcon,
                "media_toggle": QStyle.StandardPixmap.SP_MediaPlay,
                "settings": QStyle.StandardPixmap.SP_DirOpenIcon,
                "tutorial": QStyle.StandardPixmap.SP_MessageBoxQuestion,
            }
            base_pix = self.style().standardIcon(standard_icons.get(item_id, QStyle.StandardPixmap.SP_FileIcon)).pixmap(QSize(18, 18))
            pix = QPixmap(base_pix.size())
            pix.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pix)
            painter.drawPixmap(0, 0, base_pix)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pix.rect(), QColor("#f07884"))
            painter.end()
            icon.setPixmap(pix)
            icon.setStyleSheet("background: #252024; border: 1px solid #423238; border-radius: 10px; padding: 7px;")
            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            name = QLabel(str(item.get("label", "Feature")))
            name.setStyleSheet("font-weight: 650; background: transparent; border: none;")
            detail = QLabel(self._feature_description(item))
            detail.setObjectName("subtle")
            detail.setWordWrap(True)
            detail.setStyleSheet("background: transparent; border: none;")
            text_col.addWidget(name)
            text_col.addWidget(detail)
            check = QCheckBox("Show")
            check.setChecked(bool(item.get("enabled", True)))
            check.setMinimumWidth(70)
            row_layout.addWidget(icon)
            row_layout.addLayout(text_col, 1)
            row_layout.addWidget(check)
            list_layout.addWidget(row)
            self._feature_checks[item_id] = check
        list_layout.addStretch(1)
        scroller.setWidget(inner)
        root.addWidget(scroller, 1)
        return tab

    def _build_apps_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Your apps and shortcuts")
        title.setObjectName("sectionTitle")
        explain = QLabel("Add an executable, website, or custom keyboard shortcut. Each becomes its own button around the same 360-degree wheel—no app shortcuts are preloaded.")
        explain.setObjectName("subtle")
        explain.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(explain)

        self.apps_list = QListWidget()
        self.apps_list.setAlternatingRowColors(False)
        self.apps_list.setIconSize(QSize(32, 32))
        self.apps_list.itemDoubleClicked.connect(self._edit_custom_tile)
        layout.addWidget(self.apps_list, 1)
        self._refresh_custom_list()

        buttons = QHBoxLayout()
        add_app = QPushButton("＋  Add application")
        add_app.clicked.connect(self._add_application)
        add_site = QPushButton("＋  Add website")
        add_site.clicked.connect(self._add_website)
        add_shortcut = QPushButton("＋  Add shortcut")
        add_shortcut.clicked.connect(self._add_shortcut)
        launch_selected = QPushButton("Open selected")
        launch_selected.clicked.connect(self._launch_selected)
        rename_selected = QPushButton("Rename")
        rename_selected.setObjectName("quiet")
        rename_selected.clicked.connect(lambda: self._edit_custom_tile(self.apps_list.currentItem()) if self.apps_list.currentItem() else None)
        remove = QPushButton("Remove")
        remove.setObjectName("quiet")
        remove.clicked.connect(self._remove_selected)
        buttons.addWidget(add_app)
        buttons.addWidget(add_site)
        buttons.addWidget(add_shortcut)
        buttons.addStretch(1)
        buttons.addWidget(launch_selected)
        buttons.addWidget(rename_selected)
        buttons.addWidget(remove)
        layout.addLayout(buttons)
        note = QLabel("Tip: all controls and custom tiles share one wheel; no pages are used. If you add many tiles, the wheel automatically makes each button smaller to fit.")
        note.setObjectName("subtle")
        note.setWordWrap(True)
        layout.addWidget(note)
        return tab

    def _build_tutorial_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(9)
        heading = QLabel("Quick-start guide")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        inner = QWidget()
        stack = QVBoxLayout(inner)
        stack.setContentsMargins(2, 2, 4, 2)
        stack.setSpacing(8)
        steps = [
            ("01 · Open the wheel", "Tap the Smart Dial once. The wheel appears at your selected screen position."),
            ("02 · Pick a control", "Rotate to highlight a tile, then tap to select. You can also click a tile with the mouse."),
            ("03 · Use a mode", "Undo/Redo, Tabs, Brightness, Scroll, Slides and Zoom map dial rotation to the active mode."),
            ("04 · Add apps", "Open Apps & shortcuts to add a local .exe, website, or custom keyboard shortcut."),
            ("05 · Customize", "Use Controls to hide built-in tiles. Custom tiles share the same wheel; there are no pages."),
            ("06 · Dictation", "Dictation uses a local Whisper model. The first run downloads the model; afterward transcription runs on this PC."),
        ]
        for title, body in steps:
            stack.addWidget(_card(title, body))
        stack.addStretch(1)
        scroller.setWidget(inner)
        layout.addWidget(scroller, 1)
        return tab

    def show_tutorial(self) -> None:
        self._select_page("tutorial")
        self.show()
        self.raise_()
        self.activateWindow()

    def _refresh_custom_list(self) -> None:
        self.apps_list.clear()
        for item in self.config.get("wheel", {}).get("items", []):
            if not (item.get("is_custom_app") or item.get("is_custom_shortcut")):
                continue
            label = str(item.get("label", "Custom tile"))
            kind = "Keyboard shortcut" if item.get("is_custom_shortcut") else "Custom app / website"
            line = QListWidgetItem(f"{label}     ·     {kind}")
            line.setData(Qt.ItemDataRole.UserRole, str(item.get("id", "")))
            actions = item.get("actions", [])
            launch = next((a for a in actions if isinstance(a, dict) and a.get("type") == "launch"), None) if isinstance(actions, list) else None
            if launch and launch.get("program"):
                try:
                    file_info = QFileInfo(str(launch["program"]))
                    if file_info.exists():
                        line.setIcon(self._icon_provider.icon(file_info))
                except Exception:
                    pass
            elif any(isinstance(a, dict) and a.get("type") == "open_url" for a in (actions if isinstance(actions, list) else [])):
                line.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon))
            else:
                line.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
            line.setToolTip("Select to open a shortcut; double-click to rename it.")
            self.apps_list.addItem(line)

    def _new_tile(self, label: str, icon: str, action: dict[str, Any], custom_type: str) -> dict[str, Any]:
        return {
            "id": f"custom_{uuid.uuid4().hex[:8]}",
            "label": label.strip()[:24],
            "icon": (icon.strip() or label[:1] or "•")[:3],
            "kind": "action",
            "actions": [action],
            "enabled": True,
            "built_in": False,
            "is_custom_app": custom_type in {"app", "website"},
            "is_custom_shortcut": custom_type == "shortcut",
            "custom_type": custom_type,
        }

    def _add_application(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose an application", str(Path.home()), "Applications (*.exe);;All files (*.*)")
        if not path:
            return
        suggested = Path(path).stem.replace("_", " ").strip() or "My App"
        label, ok = QInputDialog.getText(self, "Name this tile", "Tile name:", text=suggested)
        if not ok or not label.strip():
            return
        # The wheel reads the executable's real Windows icon at render time.
        item = self._new_tile(label, "", {"type": "launch", "program": path}, "app")
        self.config["wheel"]["items"].append(item)
        self._refresh_custom_list()
        self.apps_list.setCurrentRow(self.apps_list.count() - 1)

    def _add_website(self) -> None:
        label, ok = QInputDialog.getText(self, "Add website", "Tile name (e.g. Docs, YouTube):")
        if not ok or not label.strip():
            return
        url, ok = QInputDialog.getText(self, "Add website", "Website URL:", text="https://")
        if not ok or not url.strip():
            return
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            QMessageBox.warning(self, "Invalid URL", "Enter a complete URL starting with http:// or https://.")
            return
        item = self._new_tile(label, label.strip()[:1].upper(), {"type": "open_url", "url": url.strip()}, "website")
        self.config["wheel"]["items"].append(item)
        self._refresh_custom_list()
        self.apps_list.setCurrentRow(self.apps_list.count() - 1)

    def _add_shortcut(self) -> None:
        label, ok = QInputDialog.getText(self, "Add keyboard shortcut", "Tile name:")
        if not ok or not label.strip():
            return
        keys_text, ok = QInputDialog.getText(self, "Add keyboard shortcut", "Key combination (e.g. CTRL+SHIFT+S):")
        if not ok or not keys_text.strip():
            return
        keys = [key.strip().upper() for key in keys_text.split("+") if key.strip()]
        if not keys or any(key not in VALID_KEYS for key in keys):
            QMessageBox.warning(self, "Unsupported key", "Use supported key names such as CTRL, ALT, SHIFT, WIN, TAB, ENTER, arrows, letters, digits, or F1–F24.")
            return
        if len(keys) > 6:
            QMessageBox.warning(self, "Too many keys", "A shortcut can contain up to six keys.")
            return
        item = self._new_tile(label, "⌘", {"type": "hotkey", "keys": keys}, "shortcut")
        self.config["wheel"]["items"].append(item)
        self._refresh_custom_list()
        self.apps_list.setCurrentRow(self.apps_list.count() - 1)

    def _launch_selected(self) -> None:
        selected = self.apps_list.currentItem()
        if selected is None:
            QMessageBox.information(self, "Choose a shortcut", "Select an application or website first.")
            return
        item_id = selected.data(Qt.ItemDataRole.UserRole)
        item = next((x for x in self.config.get("wheel", {}).get("items", []) if x.get("id") == item_id), None)
        if item is None:
            return
        actions = item.get("actions", [])
        if not isinstance(actions, list) or not actions:
            QMessageBox.information(self, "Nothing to open", "This tile does not have an action to launch.")
            return
        if any(not isinstance(a, dict) or a.get("type") not in {"launch", "open_url", "open_uri"} for a in actions):
            QMessageBox.information(self, "Keyboard shortcut", "Select a keyboard shortcut from the wheel to run it in the active app.")
            return
        self.launch_tile_requested.emit({"label": str(item.get("label", "Shortcut")), "actions": actions})

    def _edit_custom_tile(self, _list_item: QListWidgetItem) -> None:
        selected = self.apps_list.currentItem()
        if selected is None:
            return
        item_id = selected.data(Qt.ItemDataRole.UserRole)
        item = next((x for x in self.config["wheel"]["items"] if x.get("id") == item_id), None)
        if item is None:
            return
        label, ok = QInputDialog.getText(self, "Edit tile label", "Tile name:", text=str(item.get("label", "")))
        if ok and label.strip():
            item["label"] = label.strip()[:24]
            self._refresh_custom_list()

    def _remove_selected(self) -> None:
        selected = self.apps_list.currentItem()
        if selected is None:
            return
        item_id = selected.data(Qt.ItemDataRole.UserRole)
        answer = QMessageBox.question(self, "Remove tile", "Remove this custom tile from the wheel?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.config["wheel"]["items"] = [x for x in self.config["wheel"]["items"] if x.get("id") != item_id]
        self._refresh_custom_list()

    def _apply_controls_to_config(self) -> None:
        if self._app_name_edit is not None:
            app_name = " ".join(self._app_name_edit.text().strip().split())[:24] or "Cinder"
            self.config["app_name"] = app_name
            self.setWindowTitle(f"{app_name} Launcher")
        for item in self.config.get("wheel", {}).get("items", []):
            item_id = str(item.get("id", ""))
            if item_id in self._feature_checks:
                item["enabled"] = self._feature_checks[item_id].isChecked()
        if self._position_combo is not None:
            self.config.setdefault("wheel", {})["position"] = str(self._position_combo.currentData() or "bottom-center")
        if self._mic_combo is not None:
            chosen = self._mic_combo.currentData() or {"name": "", "hostapi_name": ""}
            dictation_cfg = self.config.setdefault("dictation", {})
            dictation_cfg["input_device_name"] = str(chosen.get("name", "") or "")
            dictation_cfg["input_hostapi_name"] = str(chosen.get("hostapi_name", "") or "")
        prefs = self.config.setdefault("preferences", {})
        if not isinstance(prefs, dict):
            prefs = {}
            self.config["preferences"] = prefs
        if self._start_with_windows_check is not None:
            prefs["start_with_windows"] = self._start_with_windows_check.isChecked()
        if self._close_to_tray_check is not None:
            prefs["close_to_tray"] = self._close_to_tray_check.isChecked()
        if self._animations_check is not None:
            prefs["wheel_animations"] = self._animations_check.isChecked()
        dictation_cfg = self.config.setdefault("dictation", {})
        if self._dictation_model_combo is not None:
            dictation_cfg["model_size"] = str(self._dictation_model_combo.currentData() or "base")
        if self._dictation_language_combo is not None:
            dictation_cfg["language"] = str(self._dictation_language_combo.currentData() or "en")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        prefs = self.config.get("preferences", {}) if isinstance(self.config.get("preferences", {}), dict) else {}
        if bool(prefs.get("close_to_tray", True)):
            event.ignore()
            self.hide()
        else:
            event.accept()
            app = QApplication.instance()
            if app is not None:
                QTimer.singleShot(0, app.quit)

    def save_config(self) -> bool:
        self._apply_controls_to_config()
        # The settings dialog can remain open while the wheel is used. Preserve
        # the controller's most recent runtime selection if it changed after this
        # dialog was created, instead of writing stale values back to config.json.
        try:
            latest = json.loads(self.config_path.read_text(encoding="utf-8"))
            latest_wheel = latest.get("wheel", {}) if isinstance(latest, dict) else {}
            if isinstance(latest_wheel, dict):
                wheel_cfg = self.config.setdefault("wheel", {})
                for runtime_key in ("last_selected_item_id", "last_active_mode"):
                    if runtime_key in latest_wheel:
                        wheel_cfg[runtime_key] = latest_wheel[runtime_key]
        except (OSError, json.JSONDecodeError):
            pass
        if not any(item.get("enabled", True) for item in self.config.get("wheel", {}).get("items", [])):
            QMessageBox.warning(self, "Keep one tile enabled", "The wheel needs at least one enabled tile. Turn one feature back on and try again.")
            return False
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.config_path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(self.config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temp, self.config_path)
        except OSError as exc:
            QMessageBox.critical(self, "Could not save", f"Could not write config.json:\n{exc}")
            return False
        self.on_saved(copy.deepcopy(self.config))
        return True

    def save_and_close(self) -> None:
        if self.save_config():
            self.accept()
