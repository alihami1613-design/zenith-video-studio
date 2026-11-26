"""Compact Qt plots for luma waveform, RGB parade and vectorscope."""
from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from color_scopes import SCOPE_WIDTH
from advanced_scopes import VECTOR_SIZE


class ScopeMatrixWidget(QWidget):
    def __init__(self, mode: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if mode not in ("waveform", "parade"):
            raise ValueError("mode must be waveform or parade")
        self.mode = mode
        self._data = None
        self.setMinimumHeight(145 if mode == "waveform" else 190)
        self.setMaximumHeight(210)
        self.setToolTip("تحلیل نمونه‌ای یک فریم کوچک؛ مقیاس افقی متناظر با عرض تصویر است")

    def set_data(self, data) -> None:
        self._data = data
        self.update()

    def _draw_matrix(self, painter: QPainter, matrix: Sequence[Sequence[int]],
                     rect, color: QColor) -> None:
        maximum = max((max(row) for row in matrix), default=0) or 1
        for value in range(256):
            y = rect.bottom() - (value / 255) * rect.height()
            for x in range(SCOPE_WIDTH):
                count = matrix[value][x]
                if count:
                    alpha = min(255, 45 + int(210 * count / maximum))
                    painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), alpha), 1))
                    px = rect.left() + (x / (SCOPE_WIDTH - 1)) * rect.width()
                    painter.drawPoint(round(px), round(y))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101114"))
        painter.setRenderHint(QPainter.Antialiasing, False)
        if self.mode == "waveform":
            area = self.rect().adjusted(8, 8, -8, -20)
            self._grid(painter, area)
            if self._data is None:
                self._empty(painter, area, "برای تحلیل، Waveform را اجرا کنید")
                return
            self._draw_matrix(painter, self._data, area, QColor(235, 235, 235))
            self._labels(painter, area)
            return
        if self._data is None:
            area = self.rect().adjusted(8, 8, -8, -20)
            self._empty(painter, area, "برای تحلیل، RGB Parade را اجرا کنید")
            return
        colors = (QColor(235, 85, 85), QColor(90, 205, 125), QColor(90, 145, 245))
        outer = self.rect().adjusted(8, 8, -8, -20)
        gap = 8
        panel_width = max(1, (outer.width() - gap * 2) // 3)
        for index, (matrix, color) in enumerate(zip(self._data, colors)):
            left = outer.left() + index * (panel_width + gap)
            area = outer.adjusted(left - outer.left(), 0, left + panel_width - outer.right(), 0)
            self._grid(painter, area)
            self._draw_matrix(painter, matrix, area, color)
            painter.setPen(color)
            painter.drawText(area, Qt.AlignHCenter | Qt.AlignBottom, ("R", "G", "B")[index])
            self._labels(painter, area)

    @staticmethod
    def _grid(painter: QPainter, area) -> None:
        painter.setPen(QPen(QColor("#34363b"), 1))
        for fraction in (0.25, 0.5, 0.75):
            y = area.bottom() - round(area.height() * fraction)
            painter.drawLine(area.left(), y, area.right(), y)

    @staticmethod
    def _empty(painter: QPainter, area, message: str) -> None:
        painter.setPen(QColor("#9a9ca3"))
        painter.drawText(area, Qt.AlignCenter, message)

    @staticmethod
    def _labels(painter: QPainter, area) -> None:
        painter.setPen(QColor("#9a9ca3"))
        painter.drawText(area.left(), area.bottom() + 14, "0")
        painter.drawText(area.right() - 20, area.bottom() + 14, "255")


class VectorScopeWidget(QWidget):
    """Circular chroma plot with neutral center and hue-axis guides."""
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = None
        self.setMinimumHeight(205)
        self.setMaximumHeight(235)
        self.setToolTip("پراکندگی رنگ‌ها در فضای کروی رنگ؛ مرکز نشان‌دهنده خنثی/کم‌اشباع است")

    def set_data(self, data) -> None:
        self._data = data
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101114"))
        painter.setRenderHint(QPainter.Antialiasing, True)
        side = max(20, min(self.width() - 24, self.height() - 24))
        area = self.rect().center()
        radius = side / 2
        cx, cy = area.x(), area.y() - 3
        painter.setPen(QPen(QColor("#4a4c52"), 1))
        painter.drawEllipse(round(cx - radius), round(cy - radius), round(side), round(side))
        painter.drawEllipse(round(cx - radius * 0.5), round(cy - radius * 0.5),
                            round(radius), round(radius))
        painter.drawLine(round(cx - radius), round(cy), round(cx + radius), round(cy))
        painter.drawLine(round(cx), round(cy - radius), round(cx), round(cy + radius))
        # Hue-axis guides: R, Y, G, C, B, M.
        for angle, label, color in (
            (0, "R", QColor("#ef5555")), (60, "Y", QColor("#e8d35a")),
            (120, "G", QColor("#62c77c")), (180, "C", QColor("#62cbd0")),
            (240, "B", QColor("#6898ed")), (300, "M", QColor("#c17bd8")),
        ):
            import math
            rad = math.radians(angle)
            tx, ty = cx + math.cos(rad) * radius * 0.78, cy - math.sin(rad) * radius * 0.78
            painter.setPen(QPen(color, 1))
            painter.drawEllipse(round(tx - 3), round(ty - 3), 6, 6)
            painter.drawText(round(tx + 5), round(ty + 4), label)
        if self._data is None:
            painter.setPen(QColor("#9a9ca3"))
            painter.drawText(self.rect(), Qt.AlignCenter, "برای تحلیل، Vectorscope را اجرا کنید")
            return
        maximum = max((max(row) for row in self._data), default=0) or 1
        for y, row in enumerate(self._data):
            for x, count in enumerate(row):
                if not count:
                    continue
                alpha = min(255, 65 + int(190 * count / maximum))
                painter.setPen(QPen(QColor(100, 220, 180, alpha), 2))
                px = cx + (x - (VECTOR_SIZE - 1) / 2) / ((VECTOR_SIZE - 1) / 2) * radius
                py = cy + (y - (VECTOR_SIZE - 1) / 2) / ((VECTOR_SIZE - 1) / 2) * radius
                painter.drawPoint(round(px), round(py))
