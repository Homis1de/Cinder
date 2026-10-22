"""Local speech-to-text dictation overlay for Cinder.

Audio capture uses sounddevice. Transcription runs locally through faster-whisper;
recorded audio is not sent to a remote speech service. The model is downloaded the
first time dictation is used and cached under the user's Local AppData directory.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QMimeData,
    QPointF,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen
from cinder_brand import app_icon

from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


# Keep the original cache directory so model downloads survive app rebranding/upgrades.
MODEL_DIR = Path.home() / "AppData" / "Local" / "DialLab" / "models"


class ListeningWaveform(QWidget):
    """Animated level meter driven by the current microphone input level."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self.phase = 0.0
        self.listening = True
        self.setMinimumHeight(45)
        self.setMaximumHeight(54)

    def advance(self, level: float, listening: bool) -> None:
        self.level = max(0.0, min(1.0, float(level)))
        self.listening = listening
        self.phase += 0.29
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width = self.width()
        centre_y = self.height() / 2.0
        bars = 39
        usable = max(20.0, width - 40.0)
        gap = usable / bars
        for index in range(bars):
            x = 20.0 + gap * (index + 0.5)
            wave = abs(math.sin(self.phase + index * 0.62))
            envelope = 0.22 + 0.78 * wave
            activity = (0.10 + self.level * 2.8) if self.listening else 0.25
            height = max(3.0, min(23.0, (2.0 + 19.0 * envelope * activity)))
            if not self.listening:
                height *= 0.54
            if index < bars * 0.2:
                color = QColor(177, 56, 70, 205)
            elif index > bars * 0.8:
                color = QColor(255, 135, 144, 205)
            else:
                color = QColor(239, 78, 93, 225)
            if not self.listening:
                color.setAlpha(105)
            painter.setPen(QPen(color, 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(x, centre_y - height / 2.0), QPointF(x, centre_y + height / 2.0))


class DictationOverlay(QWidget):
    """Non-activating local dictation UI that can paste text into the prior app."""

    transcription_ready = Signal(str, str)  # recognized text, error string
    transcription_progress = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.brand_name = "Cinder"
        self.setWindowTitle(f"{self.brand_name} · Dictation")
        self.setWindowIcon(app_icon())
        self.setFixedSize(540, 316)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        self._stream: Any = None
        self._chunks: list[Any] = []
        self._chunks_lock = threading.Lock()
        self._captured_samples = 0
        self._recording = False
        self._transcribing = False
        self._input_level = 0.0
        self._sample_rate = 48000
        # Persist a friendly device name and host API, not a raw index alone:
        # PortAudio device indices can change when Bluetooth devices reconnect.
        self._input_device_name = ""
        self._input_hostapi_name = ""
        # Base is the responsive default for CPU-only Windows laptops. Users can
        # choose Small in Settings when they prefer accuracy over latency.
        self._model_size = "base"
        self._language = "en"
        self._loaded_model_size = ""
        self._transcription_started_at = 0.0
        self._transcription_stage = ""
        self._target_hwnd = 0
        self._transcript = ""
        self._model: Any = None
        self._old_clipboard_formats: list[tuple[str, bytes]] = []
        self._restore_clipboard_timer = QTimer(self)
        self._restore_clipboard_timer.setSingleShot(True)
        self._restore_clipboard_timer.timeout.connect(self._restore_clipboard)

        panel = QWidget(self)
        panel.setObjectName("panel")
        panel.setGeometry(0, 0, self.width(), self.height())
        panel.setStyleSheet("""
            QWidget#panel { background: rgba(17, 11, 13, 248); border: 1px solid #71303b; border-radius: 22px; }
            QLabel { color: #f7edef; background: transparent; border: none; font-family: 'Segoe UI'; }
            QLabel#eyebrow { color: #ff8790; font-size: 8pt; font-weight: 800; letter-spacing: 1px; }
            QLabel#title { color: #fff5f6; font-size: 16pt; font-weight: 750; }
            QLabel#status { color: #cdb7bc; font-size: 9pt; }
            QLabel#transcript { color: #f1e4e7; font-size: 9pt; background: rgba(255, 110, 126, 8); border: 1px solid rgba(164, 65, 79, 120); border-radius: 9px; padding: 7px; }
            QPushButton { background: #2c171c; border: 1px solid #63303a; border-radius: 9px; color: #fae9ec; padding: 8px 12px; font-family: 'Segoe UI'; font-weight: 650; }
            QPushButton:hover { background: #432027; border-color: #a3414e; }
            QPushButton#primary { background: #c93c4a; border-color: #ef6470; color: #fffafb; }
            QPushButton#primary:hover { background: #e24756; }
            QPushButton:disabled { color: #88767a; background: #1b1114; border-color: #39232a; }
        """)

        root = QVBoxLayout(panel)
        root.setContentsMargins(20, 17, 20, 14)
        root.setSpacing(5)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        eyebrow = QLabel(f"{self.brand_name.upper()}  /  DICTATION")
        eyebrow.setObjectName("eyebrow")
        self.brand_label = eyebrow
        title = QLabel("Dictation")
        title.setObjectName("title")
        titles.addWidget(eyebrow)
        titles.addWidget(title)
        header.addLayout(titles, 1)
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("color: #ff8790; font-size: 19pt; background: transparent;")
        header.addWidget(self.status_dot, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        self.status_label = QLabel("Starting microphone…")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(28)
        root.addWidget(self.status_label)

        self.waveform = ListeningWaveform(panel)
        root.addWidget(self.waveform)

        self.transcript_label = QLabel("Audio stays on this PC. Stop when you've finished speaking.")
        self.transcript_label.setObjectName("transcript")
        self.transcript_label.setTextFormat(Qt.TextFormat.PlainText)
        self.transcript_label.setWordWrap(True)
        self.transcript_label.setMinimumHeight(46)
        self.transcript_label.setMaximumHeight(60)
        root.addWidget(self.transcript_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_dictation)
        self.primary_button = QPushButton("Stop & transcribe")
        self.primary_button.setObjectName("primary")
        self.primary_button.clicked.connect(self._primary_clicked)
        self.insert_button = QPushButton("Insert text")
        self.insert_button.setEnabled(False)
        self.insert_button.clicked.connect(self.insert_transcript)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        buttons.addWidget(self.primary_button)
        buttons.addWidget(self.insert_button)
        root.addLayout(buttons)

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(170)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(45)
        self._ui_timer.timeout.connect(self._update_meter)
        self._transcription_status_timer = QTimer(self)
        self._transcription_status_timer.setInterval(1000)
        self._transcription_status_timer.timeout.connect(self._refresh_transcription_status)

        self.transcription_ready.connect(self._on_transcription_ready, Qt.ConnectionType.QueuedConnection)
        self.transcription_progress.connect(self._on_transcription_progress, Qt.ConnectionType.QueuedConnection)

    def _position_overlay(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.move(100, 100)
            return
        bounds = screen.availableGeometry()
        x = bounds.left() + (bounds.width() - self.width()) // 2
        y = bounds.bottom() - self.height() - 22
        self.move(max(bounds.left(), x), max(bounds.top(), y))

    def set_brand_name(self, name: str) -> None:
        """Keep the dictation overlay aligned with the editable app branding."""
        cleaned = " ".join(str(name).strip().split())[:24] or "Cinder"
        self.brand_name = cleaned
        self.setWindowTitle(f"{cleaned} · Dictation")
        self.setWindowIcon(app_icon())
        if hasattr(self, "brand_label"):
            self.brand_label.setText(f"{cleaned.upper()}  /  DICTATION")

    def start_dictation(self) -> None:
        """Open overlay and begin recording; called from Cinder's UI thread."""
        if self._recording or self._transcribing:
            self.show()
            self.raise_()
            return
        self._position_overlay()
        self._target_hwnd = self._get_foreground_hwnd()
        self._transcript = ""
        self.transcript_label.setText("Audio stays on this PC. Stop when you've finished speaking.")
        self.insert_button.setEnabled(False)
        self.primary_button.setText("Stop & transcribe")
        self.primary_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.status_label.setText("Listening… speak naturally, then select Stop & transcribe.")
        self.status_dot.setStyleSheet("color: #ff8790; font-size: 19pt; background: transparent;")
        self._opacity.setOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        QTimer.singleShot(180, self._start_recording)

    @staticmethod
    def _get_foreground_hwnd() -> int:
        if not hasattr(ctypes, "windll"):
            return 0
        try:
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = wintypes.HWND
            handle = user32.GetForegroundWindow()
            return int(handle or 0)
        except Exception:
            return 0

    def set_input_device(self, device_name: str = "", hostapi_name: str = "") -> None:
        """Choose the audio input used for future dictation recordings.

        Empty names mean use the current Windows/sounddevice default input.
        """
        self._input_device_name = str(device_name or "").strip()
        self._input_hostapi_name = str(hostapi_name or "").strip()

    def set_transcription_options(self, model_size: str = "base", language: str = "en") -> None:
        """Apply local Whisper quality/language preferences.

        Changing the model size releases the old model reference so the new
        model is loaded on the next transcription, not on the UI thread.
        """
        model_size = str(model_size or "base").strip().lower()
        if model_size not in {"base", "small"}:
            model_size = "base"
        language = str(language or "en").strip().lower()
        if language not in {"auto", "en", "hi", "bn"}:
            language = "en"
        if model_size != self._model_size:
            self._model = None
            self._loaded_model_size = ""
        self._model_size = model_size
        self._language = language

    @staticmethod
    def _resolve_input_device(sd, requested_name: str, requested_hostapi: str):
        """Return (index, info, host API name), or explain why selection is missing."""
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        requested_name = (requested_name or "").strip()
        requested_hostapi = (requested_hostapi or "").strip()

        if not requested_name:
            default_input = sd.default.device[0]
            if default_input is None or int(default_input) < 0:
                raise RuntimeError("Windows has no default microphone. Choose one in Cinder Settings → Dictation.")
            index = int(default_input)
            info = sd.query_devices(index)
            if int(info.get("max_input_channels", 0)) < 1:
                raise RuntimeError("The default audio device is not an input device. Choose a microphone in Cinder Settings.")
            api_index = int(info.get("hostapi", -1))
            api_name = str(hostapis[api_index].get("name", "")) if 0 <= api_index < len(hostapis) else ""
            return index, info, api_name

        exact_matches = []
        requested_lower = requested_name.casefold()
        for index, info in enumerate(devices):
            if int(info.get("max_input_channels", 0)) < 1:
                continue
            if str(info.get("name", "")).casefold() != requested_lower:
                continue
            api_index = int(info.get("hostapi", -1))
            api_name = str(hostapis[api_index].get("name", "")) if 0 <= api_index < len(hostapis) else ""
            exact_matches.append((index, info, api_name))
        if requested_hostapi:
            for result in exact_matches:
                if result[2].casefold() == requested_hostapi.casefold():
                    return result
        if exact_matches:
            return exact_matches[0]
        available = sorted({str(info.get("name", "")) for info in devices if int(info.get("max_input_channels", 0)) > 0})
        raise RuntimeError(
            f"Selected microphone '{requested_name}' is not available. Reconnect it, or choose another device in Settings → Dictation. "
            f"Available inputs: {', '.join(available) if available else 'none'}"
        )

    def _start_recording(self) -> None:
        if not self.isVisible() or self._recording or self._transcribing:
            return
        # The overlay does not activate; this should remain the target app.
        # Refreshing here also lets a user choose a new target before retrying.
        self._target_hwnd = self._get_foreground_hwnd()
        self._transcript = ""
        self.insert_button.setEnabled(False)
        self.primary_button.setText("Stop & transcribe")
        self.primary_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Cancel")
        self.status_dot.setStyleSheet("color: #ff8790; font-size: 19pt; background: transparent;")
        try:
            import numpy as np
            import sounddevice as sd

            self._chunks = []
            self._captured_samples = 0
            self._input_level = 0.0
            device_index, device_info, hostapi_name = self._resolve_input_device(
                sd, self._input_device_name, self._input_hostapi_name
            )
            # Use the device's actual default rate; some Bluetooth hands-free
            # endpoints expose 16 kHz (and a few expose 8 kHz). The transcription
            # worker resamples to Whisper's 16 kHz format after capture.
            self._sample_rate = max(8000, int(device_info.get("default_samplerate", 48000) or 48000))
            chosen_name = str(device_info.get("name", "microphone"))
            self._active_input_label = chosen_name

            def audio_callback(indata, frames, _time_info, status):
                if status:
                    # Status is surfaced on-screen via the shared message only if
                    # capture fails; minor under/overflows do not stop dictation.
                    pass
                chunk = indata[:, 0].copy()
                with self._chunks_lock:
                    if self._recording:
                        self._chunks.append(chunk)
                        self._captured_samples += chunk.size
                # More visible meter at quiet Bluetooth mic levels; recognition
                # itself uses capped gain adjustment on the completed recording.
                self._input_level = min(1.0, float(np.sqrt(np.mean(chunk * chunk))) * 32.0)

            self._recording = True
            self._stream = sd.InputStream(
                device=device_index,
                samplerate=self._sample_rate,
                channels=1,
                dtype="float32",
                callback=audio_callback,
                blocksize=0,
            )
            self._stream.start()
            self._ui_timer.start()
            self.status_label.setText(f"Listening on {chosen_name} · {self._sample_rate // 1000} kHz")
            self.transcript_label.setText("Speak clearly. Click Stop & transcribe when you're done.")
        except Exception as exc:
            self._recording = False
            self._close_stream()
            self._show_error(f"Could not start microphone: {exc}")

    def _update_meter(self) -> None:
        self.waveform.advance(self._input_level, self._recording)
        if self._recording and self._stream is not None:
            # Avoid unlimited memory use: automatically stop at two minutes.
            with self._chunks_lock:
                captured_seconds = self._captured_samples / max(1, self._sample_rate)
            if captured_seconds >= 120:
                self.status_label.setText("Two-minute limit reached. Transcribing your recording…")
                self._stop_recording_and_transcribe()

    def _primary_clicked(self) -> None:
        if self._recording:
            self._stop_recording_and_transcribe()
        elif not self._transcribing and not self._transcript:
            self._start_recording()
        elif self._transcript:
            self._start_recording()

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    def _stop_recording_and_transcribe(self) -> None:
        if not self._recording:
            return
        self._recording = False
        self._close_stream()
        with self._chunks_lock:
            chunks = self._chunks[:]
            self._chunks = []
            self._captured_samples = 0
        self._input_level = 0.0

        try:
            import numpy as np
            audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        except Exception as exc:
            self._show_error(f"Could not prepare audio: {exc}")
            return
        if audio.size < int(self._sample_rate * 0.30):
            self._show_error("That was too short to transcribe. Try speaking for a second or two.")
            return

        # Capture diagnostics before launching transcription. Whisper cannot
        # recover words from a silent/near-silent input, so report that clearly.
        rms = float((audio.astype("float64") ** 2).mean() ** 0.5) if audio.size else 0.0
        peak = float(abs(audio).max()) if audio.size else 0.0
        if peak < 0.000001 or rms < 0.0000001:
            self._show_error(
                f"The selected microphone captured almost no sound (peak {peak:.5f}, RMS {rms:.5f}). "
                "Open Settings → Dictation and test the CMF Buds Pro 2 microphone."
            )
            return

        self._transcribing = True
        self.primary_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.insert_button.setEnabled(False)
        self.status_dot.setStyleSheet("color: #f0c36b; font-size: 19pt; background: transparent;")
        model_note = "Small model prioritizes accuracy; Base prioritizes speed."
        self._transcription_started_at = time.monotonic()
        self._transcription_stage = "Preparing local recognizer…"
        self.status_label.setText(f"Preparing dictation · {self._model_size.title()} model")
        self.transcript_label.setText(f"{model_note} First use may download the model once. Audio stays on this PC.")
        self._transcription_status_timer.start()
        worker = threading.Thread(
            target=self._transcribe_worker,
            args=(audio, self._sample_rate, self._model_size, self._language),
            name="CinderLocalWhisper",
            daemon=True,
        )
        worker.start()

    def _transcribe_worker(self, audio, sample_rate: int, model_size: str, language: str) -> None:
        """Run model setup and decoding away from Qt's UI thread.

        The Base model and a small beam make CPU transcription much more
        responsive than Small + beam 5. The progress signal keeps first-run
        model downloads distinguishable from a frozen window.
        """
        try:
            import numpy as np
            # Give huggingface_hub bounded network waits so a dead/unresponsive
            # endpoint raises a useful error rather than appearing to hang forever.
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "12")
            os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "35")
            from faster_whisper import WhisperModel

            if self._model is None or self._loaded_model_size != model_size:
                MODEL_DIR.mkdir(parents=True, exist_ok=True)
                self.transcription_progress.emit(
                    f"Loading {model_size.title()} model · first use downloads it once…"
                )
                self._model = WhisperModel(
                    model_size,
                    device="cpu",
                    compute_type="int8",
                    download_root=str(MODEL_DIR),
                    cpu_threads=max(2, min(8, (os.cpu_count() or 4) - 1)),
                    num_workers=1,
                )
                self._loaded_model_size = model_size

            self.transcription_progress.emit("Preparing audio…")
            audio = np.asarray(audio, dtype=np.float32)
            if sample_rate != 16000:
                try:
                    from scipy.signal import resample_poly
                    from math import gcd
                    divisor = gcd(int(sample_rate), 16000)
                    audio = resample_poly(audio, 16000 // divisor, int(sample_rate) // divisor).astype(np.float32)
                except Exception:
                    duration = audio.size / float(sample_rate)
                    target_size = max(1, int(duration * 16000))
                    source_positions = np.arange(audio.size, dtype=np.float64)
                    target_positions = np.arange(target_size, dtype=np.float64) * (sample_rate / 16000.0)
                    audio = np.interp(target_positions, source_positions, audio).astype(np.float32)

            # Remove DC offset and normalize quiet headset capture, with a cap
            # to avoid making background noise dominate speech.
            audio = audio - float(np.mean(audio))
            rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) if audio.size else 0.0
            peak = float(np.max(np.abs(audio))) if audio.size else 0.0
            if rms < 1e-7 or peak < 1e-6:
                raise RuntimeError(
                    "The microphone recording is effectively silent. Open Settings → Dictation, "
                    "test the selected input, and choose the microphone that captures your voice."
                )
            gain = min(40.0, 0.07 / max(rms, 1e-8))
            audio *= gain
            peak = float(np.max(np.abs(audio))) if audio.size else 0.0
            if peak > 0.95:
                audio *= 0.95 / peak
            audio = np.clip(audio, -1.0, 1.0).astype(np.float32)

            chosen_language = None if language == "auto" else language
            vad_parameters = {
                "threshold": 0.32,
                "min_speech_duration_ms": 100,
                "min_silence_duration_ms": 450,
                "speech_pad_ms": 250,
            }
            self.transcription_progress.emit("Recognizing speech locally…")
            segments, _info = self._model.transcribe(
                audio,
                language=chosen_language,
                beam_size=1,
                best_of=1,
                temperature=0,
                condition_on_previous_text=False,
                vad_filter=True,
                vad_parameters=vad_parameters,
            )
            text_parts = []
            for segment in segments:
                part = segment.text.strip()
                if part:
                    text_parts.append(part)
                    self.transcription_progress.emit(
                        f"Recognizing speech locally… ({len(text_parts)} segment{'s' if len(text_parts) != 1 else ''})"
                    )
            text = " ".join(text_parts).strip()

            # One no-VAD retry helps when a quiet Bluetooth mic is incorrectly
            # classified as silence; keep decoding settings fast on this path too.
            if not text:
                self.transcription_progress.emit("Checking quiet speech…")
                segments, _info = self._model.transcribe(
                    audio,
                    language=chosen_language,
                    beam_size=1,
                    best_of=1,
                    temperature=0,
                    condition_on_previous_text=False,
                    vad_filter=False,
                )
                text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
            self.transcription_ready.emit(text, "")
        except Exception as exc:
            self.transcription_ready.emit("", str(exc))

    def _on_transcription_progress(self, message: str) -> None:
        if not self._transcribing:
            return
        self._transcription_stage = str(message or "Working locally…")
        self._refresh_transcription_status()

    def _refresh_transcription_status(self) -> None:
        if not self._transcribing:
            self._transcription_status_timer.stop()
            return
        elapsed = max(0, int(time.monotonic() - self._transcription_started_at))
        minutes, seconds = divmod(elapsed, 60)
        elapsed_text = f"{minutes}:{seconds:02d} elapsed" if minutes else f"{seconds}s elapsed"
        stage = self._transcription_stage or "Working locally…"
        self.status_label.setText(f"{stage} · {elapsed_text}")
        if elapsed >= 150:
            self.transcript_label.setText(
                "This is taking longer than expected. First-run model download needs internet; "
                "if it stays here, restart Cinder and try the Base model after checking your connection."
            )

    def _on_transcription_ready(self, text: str, error: str) -> None:
        self._transcribing = False
        self._transcription_status_timer.stop()
        self._transcription_started_at = 0.0
        self._ui_timer.stop()
        self.cancel_button.setEnabled(True)
        self.primary_button.setEnabled(True)
        if error:
            self._show_error(f"Local transcription failed: {error}")
            return
        if not text:
            self._show_error("No speech was detected. Check your microphone, then try again.")
            return
        self._transcript = text
        preview = text if len(text) <= 245 else text[:242].rstrip() + "…"
        self.transcript_label.setText(preview)
        self.status_label.setText("Transcription ready · processed locally")
        self.status_dot.setStyleSheet("color: #ff8790; font-size: 19pt; background: transparent;")
        self.primary_button.setText("Dictate again")
        self.insert_button.setEnabled(True)
        self.cancel_button.setText("Close")

    def _show_error(self, message: str) -> None:
        self._ui_timer.stop()
        self._transcription_status_timer.stop()
        self._transcription_started_at = 0.0
        self.status_label.setText(message)
        self.transcript_label.setText("Check microphone permissions and the selected input. Audio is processed locally; no recording is uploaded.")
        self.status_dot.setStyleSheet("color: #ee8b8b; font-size: 19pt; background: transparent;")
        self.primary_button.setText("Try again")
        self.primary_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.insert_button.setEnabled(bool(self._transcript))
        self._transcribing = False

    def cancel_dictation(self) -> None:
        self._recording = False
        self._ui_timer.stop()
        self._close_stream()
        self._transcribing = False
        self._transcription_status_timer.stop()
        self._chunks = []
        self._fade.stop()
        self.hide()

    def insert_transcript(self) -> None:
        if not self._transcript.strip():
            return
        clipboard = QApplication.clipboard()
        old_mime = clipboard.mimeData()
        self._old_clipboard_formats = []
        if old_mime is not None:
            for fmt in old_mime.formats():
                try:
                    self._old_clipboard_formats.append((str(fmt), bytes(old_mime.data(fmt))))
                except Exception:
                    pass
        clipboard.setText(self._transcript)
        target = int(self._target_hwnd or 0)
        self._fade.stop()
        self.hide()
        QTimer.singleShot(180, lambda: self._paste_to_target(target))
        self._restore_clipboard_timer.start(1400)

    def _paste_to_target(self, target: int) -> None:
        try:
            user32 = ctypes.windll.user32
            user32.IsWindow.argtypes = [wintypes.HWND]
            user32.IsWindow.restype = wintypes.BOOL
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            hwnd = wintypes.HWND(target) if target else None
            if hwnd and user32.IsWindow(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
            time.sleep(0.08)
            # Simulate Ctrl+V into the previously focused app. Audio never leaves
            # this computer; only the final recognized text is placed on clipboard.
            VK_CONTROL, VK_V, KEYUP = 0x11, 0x56, 0x0002
            user32.keybd_event(VK_CONTROL, 0, 0, 0)
            user32.keybd_event(VK_V, 0, 0, 0)
            user32.keybd_event(VK_V, 0, KEYUP, 0)
            user32.keybd_event(VK_CONTROL, 0, KEYUP, 0)
        except Exception as exc:
            self.status_label.setText(f"Text recognized, but paste failed: {exc}")
            self.show()
            self.raise_()

    def _restore_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        if not self._old_clipboard_formats:
            clipboard.clear()
            return
        mime = QMimeData()
        for fmt, data in self._old_clipboard_formats:
            try:
                mime.setData(fmt, QByteArray(data))
            except Exception:
                pass
        clipboard.setMimeData(mime)
        self._old_clipboard_formats = []

    def shutdown(self) -> None:
        self._recording = False
        self._ui_timer.stop()
        self._restore_clipboard_timer.stop()
        self._transcription_status_timer.stop()
        self._close_stream()

