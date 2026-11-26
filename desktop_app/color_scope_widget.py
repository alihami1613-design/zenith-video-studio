"""Qt visualization widget for the lightweight RGB histogram scope."""
from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


    """Compact RGB histogram; receives already-computed data from a worker."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._histogram: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]] | None = None
        self.setMinimumHeight(132)
        self.setMaximumHeight(160)
        self.setToolTip("هیستوگرام RGB از یک فریم نمونه‌برداری‌شده؛ مقیاس نمایش نرمال شده است")

    def set_histogram(self, histogram: Sequence[Sequence[int]] | None) -> None:
        if histogram is None:
            self._histogram = None
        else:
            if len(histogram) != 3 or any(len(channel) != 256 for channel in histogram):
                raise ValueError("RGB histogram must contain three 256-bin channels")
            self._histogram = tuple(tuple(int(value) for value in channel) for channel in histogram)  # type: ignore[assignment]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#101114"))
        area = self.rect().adjusted(8, 8, -8, -20)
        painter.setPen(QPen(QColor("#34363b"), 1))
        for fraction in (0.25, 0.5, 0.75):
            y = area.bottom() - round(area.height() * fraction)
            painter.drawLine(area.left(), y, area.right(), y)
        if self._histogram is None:
            painter.setPen(QColor("#9a9ca3"))
            painter.drawText(area, Qt.AlignCenter, "برای تحلیل، دکمه «تحلیل هیستوگرام RGB» را بزنید")
            return
        maximum = max((max(channel) for channel in self._histogram), default=0) or 1
        colors = (QColor(235, 85, 85, 190), QColor(90, 205, 125, 190), QColor(90, 145, 245, 190))
        for channel, color in zip(self._histogram, colors):
            path = QPainterPath()
            for index, value in enumerate(channel):
                x = area.left() + (index / 255) * area.width()
                y = area.bottom() - (value / maximum) * area.height()
                if index == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            painter.setPen(QPen(color, 1.25))
            painter.drawPath(path)
        painter.setPen(QColor("#9a9ca3"))
        painter.drawText(8, self.height() - 4, "0")
        painter.drawText(self.width() - 20, self.height() - 4, "255")

