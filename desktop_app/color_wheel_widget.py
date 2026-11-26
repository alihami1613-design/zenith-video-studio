"""Compact, mouse-driven three-way color wheel controls."""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QColor, QConicalGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from color_wheel_math import wheel_to_rgb, rgb_to_wheel


class ColorWheelWidget(QWidget):
    valuesChanged = Signal(float, float)
    editingStarted = Signal()
    editingFinished = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self._x = 0.0
        self._y = 0.0
        self._dragging = False
        self.setMinimumSize(112, 132)
        self.setMaximumHeight(150)
        self.setToolTip("برای انتخاب ته‌رنگ، نشانگر را داخل چرخ بکشید؛ مرکز حالت خنثی است")

    def values(self) -> tuple[float, float]:
        return self._x, self._y

    def set_values(self, x: float, y: float) -> None:
        length = math.hypot(x, y)
        if length > 1.0:
            x, y = x / length, y / length
        self._x, self._y = float(x), float(y)
        self.update()

    def _geometry(self):
        side = max(40, min(self.width() - 18, self.height() - 34))
        radius = side / 2.0
        center = QPointF(self.width() / 2.0, 19.0 + radius)
        return center, radius

    def _set_from_position(self, position) -> None:
        center, radius = self._geometry()
        dx = (position.x() - center.x()) / radius
        dy = (center.y() - position.y()) / radius
        length = math.hypot(dx, dy)
        if length > 1.0:
            dx, dy = dx / length, dy / length
        self._x, self._y = dx, dy
        self.valuesChanged.emit(dx, dy)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self.editingStarted.emit()
            self._set_from_position(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._dragging and event.buttons() & Qt.LeftButton:
            self._set_from_position(event.position())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._dragging and event.button() == Qt.LeftButton:
            self._dragging = False
            self.editingFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#17181c"))
        painter.setPen(QColor("#e5e5e5"))
        painter.drawText(0, 14, self.width(), 16, Qt.AlignCenter, self.title)
        center, radius = self._geometry()
        rect = (center.x() - radius, center.y() - radius,
                radius * 2, radius * 2)
        gradient = QConicalGradient(center, 0)
        for angle, color in (
            (0.0, QColor("#e84b4b")), (60.0, QColor("#e9d34c")),
            (120.0, QColor("#56bd68")), (180.0, QColor("#45c5c9")),
            (240.0, QColor("#548be8")), (300.0, QColor("#c15bd0")),
            (360.0, QColor("#e84b4b")),
        ):
            gradient.setColorAt(angle / 360.0, color)
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QPointF(center), radius, radius)
        painter.setBrush(QColor("#24262b"))
        painter.setPen(QPen(QColor("#777b84"), 1))
        painter.drawEllipse(QPointF(center), radius * 0.30, radius * 0.30)
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.drawLine(round(center.x() - radius), round(center.y()),
                         round(center.x() + radius), round(center.y()))
        painter.drawLine(round(center.x()), round(center.y() - radius),
                         round(center.x()), round(center.y() + radius))
        marker = QPointF(center.x() + self._x * radius * 0.88,
                         center.y() - self._y * radius * 0.88)
        painter.setBrush(QColor("#101114"))
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawEllipse(marker, 5.5, 5.5)
