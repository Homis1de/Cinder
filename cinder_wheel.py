"""Animated charcoal-and-crimson radial Smart Dial wheel."""
from __future__ import annotations

import math
import time
from typing import Any

from PySide6.QtCore import QFileInfo, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QRadialGradient, QRegion
from PySide6.QtWidgets import QApplication, QFileIconProvider, QWidget

from cinder_brand import app_icon


class ControlWheel(QWidget):
    """Single-ring circular launcher with springy selection feedback."""

    item_clicked = Signal(int)

    SIZE = 560
    OUTER_RADIUS = 268
    RING_RADIUS = 188
    HUB_RADIUS = 90
    BASE_NODE_DIAMETER = 58

    # Unified charcoal / ember palette.
    BG_OUTER = QColor("#0a0b0e")
    BG_MID = QColor("#131419")
    BG_INNER = QColor("#20171b")
    SURFACE = QColor("#1a1b20")
    SURFACE_HOVER = QColor("#292126")
    RED = QColor("#e94a59")
    RED_LIGHT = QColor("#ff8b94")
    RED_DARK = QColor("#7f2631")
    TEXT = QColor("#f8f4f5")
    MUTED = QColor("#aaa1a4")

    def __init__(self, items: list[dict[str, Any]], position: str = "bottom-center", parent=None):
        super().__init__(parent)
        self.items = list(items)
        self.position = position
        self.selected_index = 0
        self.active_mode = "Volume Control"
        self.brand_name = "CINDER"
        self._progress = 0.0
        self._animation_direction = 0
        self._animation_started = 0.0
        self._animation_start_progress = 0.0
        self._pop_started = 0.0
        self._pop_index = -1
        self._hover_index = -1
        self._flash_started = 0.0
        self.animations_enabled = True
        self._app_icon_cache: dict[str, QIcon] = {}
        self._icon_provider = QFileIconProvider()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance_animation)

        self.setWindowIcon(app_icon())
        self.setFixedSize(self.SIZE, self.SIZE)
        r = self.OUTER_RADIUS
        pad = (self.SIZE - 2 * r) // 2
        self.setMask(QRegion(pad, pad, 2 * r, 2 * r, QRegion.RegionType.Ellipse))
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

    def set_animations_enabled(self, enabled: bool) -> None:
        self.animations_enabled = bool(enabled)
        if not self.animations_enabled:
            self._timer.stop()
            self._animation_direction = 0
            self._progress = 1.0 if self.isVisible() else 0.0
            self._pop_started = 0.0
            self._flash_started = 0.0
            self.update()

    def _tile_app_icon(self, item: dict[str, Any]) -> QIcon:
        if not item.get("is_custom_app"):
            return QIcon()
        actions = item.get("actions", [])
        action = next((a for a in actions if isinstance(a, dict) and a.get("type") == "launch"), None) if isinstance(actions, list) else None
        program = str(action.get("program", "") if action else "")
        if not program:
            return QIcon()
        cached = self._app_icon_cache.get(program)
        if cached is not None:
            return cached
        icon = QIcon()
        try:
            info = QFileInfo(program)
            if info.exists():
                icon = self._icon_provider.icon(info)
        except Exception:
            pass
        self._app_icon_cache[program] = icon
        return icon

    def _draw_tile_icon(self, painter: QPainter, item: dict[str, Any], key: str,
                        center: QPointF, size: float, color: QColor) -> None:
        icon = self._tile_app_icon(item)
        if not icon.isNull():
            side = max(12, int(size * 1.35))
            pixmap = icon.pixmap(side, side)
            target = QRectF(center.x() - size * 0.675, center.y() - size * 0.675,
                            size * 1.35, size * 1.35)
            painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
            return
        self._draw_icon(painter, key, center, size, color, str(item.get("label", "Action")))

    def set_items(self, items: list[dict[str, Any]]) -> None:
        self.items = list(items)
        self.selected_index = min(self.selected_index, max(0, len(self.items) - 1))
        self._hover_index = -1
        self.update()

    def set_brand_name(self, name: str) -> None:
        cleaned = " ".join(str(name).strip().split())[:24]
        self.brand_name = (cleaned or "CINDER").upper()
        self.update()

    def show_at_cursor(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.move(100, 100)
        else:
            bounds = screen.availableGeometry()
            if self.position == "screen-center":
                x = bounds.left() + (bounds.width() - self.width()) // 2
                y = bounds.top() + (bounds.height() - self.height()) // 2
            else:
                x = bounds.left() + (bounds.width() - self.width()) // 2
                y = bounds.top() + bounds.height() - self.height() - 8
            x = max(bounds.left(), min(x, bounds.right() - self.width() + 1))
            y = max(bounds.top(), min(y, bounds.bottom() - self.height() + 1))
            self.move(x, y)
        self._progress = 0.0
        self._animation_direction = 1
        self._animation_start_progress = 0.0
        self._animation_started = time.monotonic()
        self._pop_started = time.monotonic()
        self._pop_index = self.selected_index
        if self.animations_enabled:
            self._timer.start()
        else:
            self._progress = 1.0
        self.show()
        self.raise_()
        self.update()

    def hide_animated(self) -> None:
        if not self.animations_enabled:
            self.hide()
            return
        if not self.isVisible():
            self._timer.stop()
            self._progress = 0.0
            return
        self._animation_direction = -1
        self._animation_start_progress = max(0.0, self._progress)
        self._animation_started = time.monotonic()
        self._timer.start()

    def hide(self) -> None:  # noqa: A003
        self._timer.stop()
        self._progress = 0.0
        self._animation_direction = 0
        super().hide()

    def _advance_animation(self) -> None:
        running = False
        now = time.monotonic()
        if self._animation_direction:
            elapsed = max(0.0, now - self._animation_started)
            duration = 0.28 if self._animation_direction > 0 else 0.16
            t = min(1.0, elapsed / duration)
            if self._animation_direction > 0:
                self._progress = 1.0 - (1.0 - t) ** 3
            else:
                self._progress = self._animation_start_progress * (1.0 - t) ** 2
            running = t < 1.0
            if t >= 1.0:
                closing = self._animation_direction < 0
                self._animation_direction = 0
                if closing:
                    self._progress = 0.0
                    QWidget.hide(self)
                else:
                    self._progress = 1.0
        if self._pop_started and now - self._pop_started < 0.38:
            running = True
        elif self._pop_started:
            self._pop_started = 0.0
        if self._flash_started and now - self._flash_started < 0.22:
            running = True
        elif self._flash_started:
            self._flash_started = 0.0
        self.update()
        if not running:
            self._timer.stop()

    def set_selected(self, index: int) -> None:
        if not self.items:
            self.selected_index = 0
            return
        normalized = index % len(self.items)
        if normalized != self.selected_index:
            self.selected_index = normalized
            if self.animations_enabled:
                self._pop_index = normalized
                self._pop_started = time.monotonic()
                self._timer.start()
        self.update()

    def set_active_mode(self, label: str) -> None:
        self.active_mode = str(label)
        self.update()

    def set_position(self, position: str) -> None:
        self.position = position if position in {"bottom-center", "screen-center"} else "bottom-center"

    def move_selected(self, delta: int) -> None:
        if self.items:
            self.set_selected(self.selected_index + delta)

    def pop_selected(self) -> None:
        if self.items and self.animations_enabled:
            self._pop_index = self.selected_index
            self._pop_started = time.monotonic()
            self._flash_started = self._pop_started
            self._timer.start()
            self.update()

    def _centre(self) -> QPointF:
        return QPointF(self.SIZE / 2.0, self.SIZE / 2.0)

    def _node_diameter(self, count: int) -> float:
        if count <= 1:
            return float(self.BASE_NODE_DIAMETER)
        spacing = (2.0 * math.pi * self.RING_RADIUS) / count
        return max(34.0, min(float(self.BASE_NODE_DIAMETER), spacing * 0.67))

    def _pop_scale(self, index: int) -> float:
        if index != self._pop_index or not self._pop_started:
            return 1.0
        t = min(1.0, max(0.0, (time.monotonic() - self._pop_started) / 0.38))
        # A short, visible overshoot followed by an eased spring settle.
        if t < 0.28:
            return 1.0 + 0.30 * math.sin((t / 0.28) * math.pi / 2)
        settle = (t - 0.28) / 0.72
        return 1.0 + 0.30 * (1.0 - settle) ** 2 * math.cos(settle * math.pi / 2)

    def _tile_centres(self) -> list[tuple[int, dict[str, Any], QPointF, float, float]]:
        count = len(self.items)
        if not count:
            return []
        centre = self._centre()
        progress = max(0.0, min(1.0, self._progress))
        ease = 1.0 - (1.0 - progress) ** 3
        result = []
        for index, item in enumerate(self.items):
            angle = -90.0 + index * 360.0 / count
            angle -= (1.0 - ease) * 20.0
            radians = math.radians(angle)
            radius = self.RING_RADIUS * (0.78 + 0.22 * ease)
            point = QPointF(centre.x() + radius * math.cos(radians), centre.y() + radius * math.sin(radians))
            diameter = self._node_diameter(count) * (0.78 + 0.22 * ease)
            diameter *= self._pop_scale(index)
            if index == self._hover_index and index != self.selected_index:
                diameter *= 1.04
            result.append((index, item, point, angle, diameter))
        return result

    @staticmethod
    def _icon_key(item: dict[str, Any]) -> str:
        item_id = str(item.get("id", "")).lower()
        if item_id in {"volume", "undo_redo", "tabs", "windows", "zoom", "scroll", "page_navigation", "brightness", "slides", "dictation", "screenshot", "media_toggle", "settings", "tutorial"}:
            return item_id
        mode = str(item.get("mode", "")).lower()
        if mode in {"volume", "undo_redo", "tabs", "windows", "zoom", "scroll", "page_navigation", "brightness", "slides"}:
            return mode
        return "custom"

    @classmethod
    def _draw_icon(cls, painter: QPainter, key: str, center: QPointF, size: float,
                   color: QColor, custom_label: str = "") -> None:
        painter.save()
        painter.translate(center)
        scale = size / 24.0
        painter.scale(scale, scale)
        pen = QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()

        if key == "volume":
            path.moveTo(-10, -4); path.lineTo(-6, -4); path.lineTo(-1, -8); path.lineTo(-1, 8); path.lineTo(-6, 4); path.lineTo(-10, 4); path.closeSubpath()
            painter.drawPath(path)
            painter.drawArc(QRectF(0, -7, 8, 14), -55 * 16, 110 * 16)
            painter.drawArc(QRectF(1, -10, 13, 20), -55 * 16, 110 * 16)
        elif key == "undo_redo":
            path.moveTo(-8, -4); path.cubicTo(-8, -9, 4, -10, 5, -3); path.lineTo(5, 1)
            path.moveTo(1, -2); path.lineTo(5, 2); path.lineTo(9, -2)
            path.moveTo(8, 4); path.cubicTo(8, 9, -4, 10, -5, 3); path.lineTo(-5, -1)
            path.moveTo(-1, 2); path.lineTo(-5, -2); path.lineTo(-9, 2)
            painter.drawPath(path)
        elif key == "tabs":
            painter.drawRoundedRect(QRectF(-9, -8, 18, 16), 2, 2)
            painter.drawLine(QPointF(-9, -3), QPointF(9, -3))
            painter.drawLine(QPointF(-5, 1), QPointF(5, 1))
            painter.drawLine(QPointF(-5, 5), QPointF(3, 5))
        elif key == "windows":
            painter.drawRoundedRect(QRectF(-10, -8, 14, 12), 1.5, 1.5)
            painter.drawRoundedRect(QRectF(-4, -3, 14, 12), 1.5, 1.5)
        elif key == "zoom":
            painter.drawEllipse(QRectF(-8, -9, 13, 13))
            painter.drawLine(QPointF(2, 2), QPointF(9, 9))
        elif key == "scroll":
            painter.drawLine(QPointF(0, -8), QPointF(0, 8))
            path.moveTo(-4, -4); path.lineTo(0, -9); path.lineTo(4, -4)
            path.moveTo(-4, 4); path.lineTo(0, 9); path.lineTo(4, 4)
            painter.drawPath(path)
        elif key == "page_navigation":
            path.moveTo(-1, -6); path.lineTo(-7, 0); path.lineTo(-1, 6)
            path.moveTo(-7, 0); path.lineTo(5, 0)
            path.moveTo(1, -6); path.lineTo(7, 0); path.lineTo(1, 6)
            painter.drawPath(path)
        elif key == "brightness":
            painter.drawEllipse(QRectF(-4, -4, 8, 8))
            for i in range(8):
                a = math.radians(i * 45)
                painter.drawLine(QPointF(math.cos(a) * 7, math.sin(a) * 7), QPointF(math.cos(a) * 10, math.sin(a) * 10))
        elif key == "slides":
            painter.drawRoundedRect(QRectF(-10, -7, 20, 14), 2, 2)
            path.moveTo(-2, -4); path.lineTo(4, 0); path.lineTo(-2, 4); path.closeSubpath()
            painter.setBrush(color); painter.drawPath(path)
        elif key == "dictation":
            painter.drawRoundedRect(QRectF(-3.5, -10, 7, 13), 3.5, 3.5)
            painter.drawArc(QRectF(-7, -7, 14, 15), 185 * 16, 170 * 16)
            painter.drawLine(QPointF(0, 8), QPointF(0, 11))
            painter.drawLine(QPointF(-4, 11), QPointF(4, 11))
        elif key == "screenshot":
            painter.drawRoundedRect(QRectF(-10, -7, 20, 14), 2, 2)
            painter.drawEllipse(QRectF(-4, -4, 8, 8))
            painter.drawLine(QPointF(-6, -9), QPointF(-2, -9))
        elif key == "media_toggle":
            path.moveTo(-3, -8); path.lineTo(7, 0); path.lineTo(-3, 8); path.closeSubpath()
            painter.setBrush(color); painter.drawPath(path)
            painter.drawRoundedRect(QRectF(-9, -7, 2, 14), 1, 1)
        elif key == "settings":
            painter.drawEllipse(QRectF(-5, -5, 10, 10))
            painter.drawEllipse(QRectF(-1.6, -1.6, 3.2, 3.2))
            for i in range(8):
                a = math.radians(i * 45)
                painter.drawLine(QPointF(math.cos(a) * 7, math.sin(a) * 7), QPointF(math.cos(a) * 10, math.sin(a) * 10))
        elif key == "tutorial":
            painter.drawEllipse(QRectF(-9, -9, 18, 18))
            painter.drawEllipse(QRectF(-1, -5.5, 2, 2))
            painter.drawLine(QPointF(0, -1), QPointF(0, 5))
        else:
            # Custom apps use a clean initial badge rather than mixed emoji fonts.
            initials = (custom_label.strip()[:1] or "A").upper()
            painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            painter.drawText(QRectF(-10, -11, 20, 22), Qt.AlignmentFlag.AlignCenter, initials)
        painter.restore()

    def _draw_text(self, painter: QPainter, rect: QRectF, text: str, size: int,
                   color: QColor, bold: bool = False, align=Qt.AlignmentFlag.AlignCenter) -> None:
        font = QFont("Segoe UI", size, QFont.Weight.Bold if bold else QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(color)
        fm = QFontMetrics(font)
        painter.drawText(rect, align, fm.elidedText(text, Qt.TextElideMode.ElideRight, max(12, int(rect.width() - 4))))

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setOpacity(max(0.0, min(1.0, self._progress)))
        centre = self._centre()
        outer = QRectF(centre.x() - self.OUTER_RADIUS, centre.y() - self.OUTER_RADIUS,
                       self.OUTER_RADIUS * 2, self.OUTER_RADIUS * 2)

        gradient = QRadialGradient(centre, self.OUTER_RADIUS)
        gradient.setColorAt(0.0, self.BG_INNER)
        gradient.setColorAt(0.68, self.BG_MID)
        gradient.setColorAt(1.0, self.BG_OUTER)
        painter.setPen(QPen(QColor(83, 57, 64, 210), 1.35))
        painter.setBrush(gradient)
        painter.drawEllipse(outer)

        # Minimal double rim: elegant circular hardware rather than radar markings.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(242, 78, 93, 92), 1.0))
        painter.drawEllipse(outer.adjusted(5, 5, -5, -5))
        # No inner guide ring: the selection nodes should feel like floating
        # hardware controls, not radar markers.

        nodes = self._tile_centres()
        # A short ember arc follows the current selection; no spokes or radial tick marks.
        if self.items:
            start = int((-90 + self.selected_index * 360.0 / len(self.items) - 8) * 16)
            arc_rect = outer.adjusted(10, 10, -10, -10)
            painter.setPen(QPen(QColor(239, 78, 93, 210), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(arc_rect, start, 16 * 16)

        # Hub: dark glass with one warm accent and legible selected-control info.
        hub_rect = QRectF(centre.x() - self.HUB_RADIUS, centre.y() - self.HUB_RADIUS,
                          self.HUB_RADIUS * 2, self.HUB_RADIUS * 2)
        hub_gradient = QRadialGradient(centre, self.HUB_RADIUS)
        hub_gradient.setColorAt(0.0, QColor("#282126"))
        hub_gradient.setColorAt(1.0, QColor("#111216"))
        painter.setPen(QPen(QColor(102, 58, 66, 210), 1.1))
        painter.setBrush(hub_gradient)
        painter.drawEllipse(hub_rect)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(239, 78, 93, 145), 1.1))
        painter.drawEllipse(hub_rect.adjusted(5, 5, -5, -5))

        selected_item = self.items[self.selected_index] if self.items else {"label": "No controls", "id": "custom", "kind": "action"}
        self._draw_text(painter, QRectF(centre.x() - 64, centre.y() - 68, 128, 13), self.brand_name,
                        8, self.RED_LIGHT, True)
        key = self._icon_key(selected_item)
        self._draw_tile_icon(painter, selected_item, key, QPointF(centre.x(), centre.y() - 35), 28, QColor("#ff8790"))
        label = str(selected_item.get("label", "Action"))
        self._draw_text(painter, QRectF(centre.x() - 70, centre.y() - 17, 140, 21), label, 11, self.TEXT, True)
        kind = str(selected_item.get("kind", "action")).lower()
        detail = "MODE" if kind == "mode" else "SETTINGS" if kind == "settings" else "HELP" if kind == "tutorial" else "ACTION"
        self._draw_text(painter, QRectF(centre.x() - 69, centre.y() + 5, 138, 13), detail, 7, self.MUTED, True)
        painter.setPen(QPen(QColor(100, 48, 56, 170), 1.0))
        painter.drawLine(QPointF(centre.x() - 48, centre.y() + 26), QPointF(centre.x() + 48, centre.y() + 26))
        self._draw_text(painter, QRectF(centre.x() - 68, centre.y() + 32, 136, 13),
                        f"ACTIVE  ·  {self.active_mode}", 7, QColor("#efb8bd"), False)
        self._draw_text(painter, QRectF(centre.x() - 70, centre.y() + 49, 140, 13),
                        "TURN  ·  SELECT", 7, QColor("#d4b9bd"), True)

        show_all_labels = len(nodes) <= 16
        for index, item, node, _angle, diameter in nodes:
            selected = index == self.selected_index
            hovered = index == self._hover_index
            rect = QRectF(node.x() - diameter / 2, node.y() - diameter / 2, diameter, diameter)
            if selected:
                # Ember halo + a soft radial fill make selection feel tactile.
                pulse = 0.0
                if self._flash_started:
                    age = max(0.0, time.monotonic() - self._flash_started)
                    pulse = max(0.0, 1.0 - age / 0.22)
                glow_alpha = int(52 + pulse * 88)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(239, 78, 93, glow_alpha), 5.5 + pulse * 2.0))
                painter.drawEllipse(rect.adjusted(-5, -5, 5, 5))
                painter.setPen(QPen(QColor("#ff929b"), 1.35))
                node_gradient = QRadialGradient(rect.center(), diameter * 0.85)
                node_gradient.setColorAt(0.0, QColor("#653039"))
                node_gradient.setColorAt(1.0, QColor("#291419"))
                painter.setBrush(node_gradient)
            else:
                painter.setPen(QPen(QColor("#5c4247") if hovered else QColor("#373337"), 1.0))
                node_gradient = QRadialGradient(rect.center(), diameter * 0.9)
                if hovered:
                    node_gradient.setColorAt(0.0, QColor("#33272b"))
                    node_gradient.setColorAt(1.0, QColor("#1d191c"))
                else:
                    node_gradient.setColorAt(0.0, QColor("#242326"))
                    node_gradient.setColorAt(1.0, QColor("#141315"))
                painter.setBrush(node_gradient)
            painter.drawEllipse(rect)

            icon_color = QColor("#fff0f1") if selected else QColor("#cfbfc2")
            self._draw_tile_icon(painter, item, self._icon_key(item), node, min(23.0, diameter * 0.48), icon_color)

            if show_all_labels:
                available = max(38, int((2 * math.pi * self.RING_RADIUS / max(1, len(nodes))) * 0.92))
                font_size = 8 if len(nodes) <= 11 else 7
                text = str(item.get("label", "Action"))
                text_color = QColor("#fff1f2") if selected else QColor("#c8b7bb")
                rect_label = QRectF(node.x() - available / 2, node.y() + diameter / 2 + 2, available, 14)
                self._draw_text(painter, rect_label, text, font_size, text_color, selected)
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        for index, _item, node, _angle, diameter in self._tile_centres():
            hit = QRectF(node.x() - diameter / 2 - 6, node.y() - diameter / 2 - 6,
                         diameter + 12, diameter + 12)
            if hit.contains(point):
                self.set_selected(index)
                self.item_clicked.emit(index)
                event.accept()
                return

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        point = event.position()
        closest: tuple[float, int] | None = None
        for index, _item, node, _angle, diameter in self._tile_centres():
            distance = math.hypot(point.x() - node.x(), point.y() - node.y())
            if distance <= diameter * 0.96 and (closest is None or distance < closest[0]):
                closest = (distance, index)
        new_hover = closest[1] if closest else -1
        if new_hover != self._hover_index:
            self._hover_index = new_hover
            if new_hover >= 0:
                self.set_selected(new_hover)
            else:
                self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_index = -1
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            self.move_selected(-1 if delta > 0 else 1)
            event.accept()
        else:
            event.ignore()
