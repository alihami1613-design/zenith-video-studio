"""Lightweight mouse-editable cubic Bezier easing graph."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class BezierCurveWidget(QWidget):
    valuesChanged = Signal(float, float)
    editingStarted = Signal()
    editingFinished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._y1, self._y2 = 0.0, 1.0
        self._drag_index = 0
        self.setMinimumHeight(154)
        self.setMaximumHeight(190)
        self.setToolTip("دستگیره‌های کنترل را با ماوس بالا و پایین بکشید؛ برای تنظیم دقیق‌تر از اعداد استفاده کنید")

    def values(self) -> tuple[float, float]:
        return self._y1, self._y2

    def set_values(self, y1: float, y2: float) -> None:
        self._y1 = min(1.0, max(0.0, float(y1)))
        self._y2 = min(1.0, max(0.0, float(y2)))
        self.update()

    def _plot(self):
        return (QPointF(18.0, self.height() - 18.0),
                QPointF(self.width() - 18.0, 18.0))

    def _handle_points(self):
        start, end = self._plot()
        return (QPointF(start.x() + (end.x() - start.x()) / 3.0,
                        start.y() + (end.y() - start.y()) * self._y1),
                QPointF(start.x() + 2.0 * (end.x() - start.x()) / 3.0,
                        start.y() + (end.y() - start.y()) * self._y2))

    def _set_handle_from_mouse(self, point: QPointF) -> None:
        start, end = self._plot()
        span = max(1.0, start.y() - end.y())
        value = min(1.0, max(0.0, (start.y() - point.y()) / span))
        if self._drag_index == 1:
            self._y1 = value
        else:
            self._y2 = value
        self.valuesChanged.emit(self._y1, self._y2)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            points = self._handle_points()
            self._drag_index = 1 if (event.position() - points[0]).manhattanLength() > (event.position() - points[1]).manhattanLength() else 0
            self.editingStarted.emit()
            self._set_handle_from_mouse(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.LeftButton:
            self._set_handle_from_mouse(event.position())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.editingFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#17181c"))
        start, end = self._plot()
        painter.setPen(QPen(QColor("#454952"), 1, Qt.DashLine))
        for step in range(1, 4):
            x = start.x() + (end.x() - start.x()) * step / 4
            y = start.y() + (end.y() - start.y()) * step / 4
            painter.drawLine(QPointF(x, start.y()), QPointF(x, end.y()))
            painter.drawLine(QPointF(start.x(), y), QPointF(end.x(), y))
        painter.setPen(QPen(QColor("#777d89"), 1))
        painter.drawLine(start, end)
        h1, h2 = self._handle_points()
        painter.setPen(QPen(QColor("#b9a06a"), 1, Qt.DashLine))
        painter.drawLine(start, h1)
        painter.drawLine(end, h2)
        path = []
        for index in range(41):
            t = index / 40.0
            u = 1.0 - t
            y = 3*u*u*t*self._y1 + 3*u*t*t*self._y2 + t*t*t
            path.append(QPointF(start.x() + (end.x()-start.x())*t,
                                start.y() + (end.y()-start.y())*y))
        painter.setPen(QPen(QColor("#e0bd73"), 2))
        for left, right in zip(path, path[1:]):
            painter.drawLine(left, right)
        for point in (h1, h2):
            painter.setBrush(QColor("#e0bd73"))
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.drawEllipse(point, 5.5, 5.5)
        painter.setPen(QColor("#d5d7dc"))
        painter.drawText(18, self.height() - 3, "START")
        painter.drawText(self.width() - 62, 13, "END")
