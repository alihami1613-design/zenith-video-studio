"""Interactive polygon-mask handles for the lightweight program monitor."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QBrush, QPen, QPolygonF
from PySide6.QtWidgets import QWidget


def fitted_video_rect(width: float, height: float, frame_width: float, frame_height: float) -> QRectF:
    """Return the centered letterboxed frame rectangle in widget coordinates."""
    if min(width, height, frame_width, frame_height) <= 0:
        return QRectF()
    scale = min(width / frame_width, height / frame_height)
    w, h = frame_width * scale, frame_height * scale
    return QRectF((width - w) / 2.0, (height - h) / 2.0, w, h)


def normalized_point_to_widget(point: list[float], rect: QRectF) -> QPointF:
    return QPointF(rect.left() + float(point[0]) * rect.width(),
                   rect.top() + float(point[1]) * rect.height())


def widget_point_to_normalized(point: QPointF, rect: QRectF) -> list[float]:
    if rect.width() <= 0 or rect.height() <= 0:
        return [0.0, 0.0]
    return [max(0.0, min(1.0, (point.x() - rect.left()) / rect.width())),
            max(0.0, min(1.0, (point.y() - rect.top()) / rect.height()))]


class PolygonMaskOverlay(QWidget):
    """Mouse-editable polygon overlay; no video decoding or extra frame buffers."""
    editingStarted = Signal()
    pointsChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[list[float]] = []
        self._frame_size = (1920, 1080)
        self._active = False
        self._drag_index: int | None = None
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.hide()

    def set_mask(self, points, frame_width: int, frame_height: int, active: bool):
        self._points = [[float(p[0]), float(p[1])] for p in points]
        self._frame_size = (max(1, int(frame_width)), max(1, int(frame_height)))
        self._active = bool(active and len(self._points) >= 3)
        self._drag_index = None
        self.setVisible(self._active)
        self.raise_()
        self.update()

    def _video_rect(self) -> QRectF:
        return fitted_video_rect(self.width(), self.height(), *self._frame_size)

    def _handle_at(self, pos: QPointF) -> int | None:
        rect = self._video_rect()
        nearest, nearest_distance = None, 14.0
        for index, point in enumerate(self._points):
            target = normalized_point_to_widget(point, rect)
            distance = ((target.x() - pos.x()) ** 2 + (target.y() - pos.y()) ** 2) ** 0.5
            if distance <= nearest_distance:
                nearest, nearest_distance = index, distance
        return nearest

    def paintEvent(self, _event):
        if not self._active or len(self._points) < 3:
            return
        from PySide6.QtGui import QPainter
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self._video_rect()
        polygon = QPolygonF([normalized_point_to_widget(p, rect) for p in self._points])
        painter.setPen(QPen(QColor(255, 214, 112, 230), 2))
        painter.setBrush(QBrush(QColor(255, 214, 112, 35)))
        painter.drawPolygon(polygon)
        for index, point in enumerate(self._points):
            center = normalized_point_to_widget(point, rect)
            painter.setPen(QPen(QColor("#241B08"), 1))
            painter.setBrush(QBrush(QColor("#FFF0B5" if index == self._drag_index else "#D6AE55")))
            painter.drawEllipse(center, 6.0, 6.0)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            index = self._handle_at(event.position())
            if index is not None:
                self._drag_index = index
                self.editingStarted.emit()
                self.update()
                event.accept()
                return
        event.ignore()

    def mouseMoveEvent(self, event):
        if self._drag_index is not None:
            self._points[self._drag_index] = widget_point_to_normalized(
                event.position(), self._video_rect()
            )
            self.pointsChanged.emit([[round(x, 6), round(y, 6)] for x, y in self._points])
            self.update()
            event.accept()
            return
        self.setCursor(Qt.OpenHandCursor if self._handle_at(event.position()) is not None else Qt.ArrowCursor)
        event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_index is not None:
            self._drag_index = None
            self.update()
            event.accept()
            return
        event.ignore()
