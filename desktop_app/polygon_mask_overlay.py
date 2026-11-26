"""Lightweight interactive mask handles for the Program Monitor.

Only normalized geometry is drawn/edited here. No video frame is decoded or copied.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QBrush, QPen, QPolygonF, QPainter
from PySide6.QtWidgets import QWidget


def _fit_rect(width: float, height: float, frame_width: float, frame_height: float) -> QRectF:
    if min(width, height, frame_width, frame_height) <= 0:
        return QRectF()
    scale = min(width / frame_width, height / frame_height)
    w, h = frame_width * scale, frame_height * scale
    return QRectF((width - w) / 2.0, (height - h) / 2.0, w, h)


class PolygonMaskOverlay(QWidget):
    editingStarted = Signal()
    pointsChanged = Signal(object)
    geometryChanged = Signal(object)
    rotationChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[list[float]] = []
        self._frame_size = (1920, 1080)
        self._active = False
        self._shape = "polygon"
        self._rect = [0.0, 0.0, 1.0, 1.0]
        self._rotation = 0.0
        self._rotation_start = 0.0
        self._pointer_angle_start = 0.0
        self._drag_kind: str | None = None
        self._drag_index: int | None = None
        self._last_pos = QPointF()
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.hide()

    def set_mask(self, points, frame_width: int, frame_height: int, active: bool,
                 shape: str = "polygon", rect=None, geometry_editable: bool = False,
                 rotation: float = 0.0):
        self._points = [[float(p[0]), float(p[1])] for p in points]
        self._frame_size = (max(1, int(frame_width)), max(1, int(frame_height)))
        self._shape = shape if shape in {"rectangle", "ellipse", "polygon"} else "polygon"
        self._rect = [float(v) for v in (rect or [0.0, 0.0, 1.0, 1.0])]
        self._rotation = float(rotation)
        self._active = bool(active and (
            (self._shape == "polygon" and len(self._points) >= 3)
            or (self._shape in {"rectangle", "ellipse"} and len(self._rect) == 4)
        ))
        self._geometry_editable = bool(geometry_editable)
        self._drag_kind = None
        self._drag_index = None
        self.setVisible(self._active)
        self.raise_()
        self.update()

    def _video_rect(self) -> QRectF:
        return _fit_rect(self.width(), self.height(), *self._frame_size)

    def _to_widget(self, x: float, y: float) -> QPointF:
        frame = self._video_rect()
        return QPointF(frame.left() + x * frame.width(), frame.top() + y * frame.height())

    def _to_normalized(self, point: QPointF) -> tuple[float, float]:
        frame = self._video_rect()
        if frame.width() <= 0 or frame.height() <= 0:
            return 0.0, 0.0
        return (
            max(0.0, min(1.0, (point.x() - frame.left()) / frame.width())),
            max(0.0, min(1.0, (point.y() - frame.top()) / frame.height())),
        )

    def _rect_widget(self) -> QRectF:
        x, y, width, height = self._rect
        p1, p2 = self._to_widget(x, y), self._to_widget(x + width, y + height)
        return QRectF(p1, p2).normalized()

    def _local_pos(self, pos: QPointF) -> QPointF:
        center = self._rect_widget().center()
        return center + self._rotate_vector(pos - center, -self._rotation)

    @staticmethod
    def _rotate_vector(vector: QPointF, degrees: float) -> QPointF:
        from math import cos, radians, sin
        angle = radians(degrees)
        return QPointF(vector.x() * cos(angle) - vector.y() * sin(angle),
                       vector.x() * sin(angle) + vector.y() * cos(angle))

    def _rotation_handle(self) -> QPointF:
        rect = self._rect_widget()
        local = QPointF(rect.center().x(), rect.top() - 28.0)
        return rect.center() + self._rotate_vector(local - rect.center(), self._rotation)

    def _hit_polygon(self, pos: QPointF) -> int | None:
        pos = self._local_pos(pos)
        nearest, distance = None, 14.0
        frame = self._video_rect()
        for index, (x, y) in enumerate(self._points):
            target = QPointF(frame.left() + x * frame.width(), frame.top() + y * frame.height())
            d = ((target.x() - pos.x()) ** 2 + (target.y() - pos.y()) ** 2) ** 0.5
            if d <= distance:
                nearest, distance = index, d
        return nearest

    def _hit_geometry(self, pos: QPointF) -> str | None:
        handle = self._rotation_handle()
        if (handle - pos).manhattanLength() <= 20:
            return "rotate"
        pos = self._local_pos(pos)
        rect = self._rect_widget()
        corners = {
            "nw": rect.topLeft(), "ne": rect.topRight(),
            "sw": rect.bottomLeft(), "se": rect.bottomRight(),
        }
        for name, point in corners.items():
            if (point - pos).manhattanLength() <= 18:
                return name
        if rect.contains(pos):
            return "move"
        return None

    def paintEvent(self, _event):
        if not self._active:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self._rect_widget()
        painter.save()
        painter.translate(rect.center())
        painter.rotate(self._rotation)
        painter.translate(-rect.center())
        painter.setPen(QPen(QColor(255, 214, 112, 230), 2))
        painter.setBrush(QBrush(QColor(255, 214, 112, 35)))
        if self._shape == "polygon":
            frame = self._video_rect()
            polygon = QPolygonF([
                QPointF(frame.left() + x * frame.width(), frame.top() + y * frame.height())
                for x, y in self._points
            ])
            painter.drawPolygon(polygon)
            for index, point in enumerate(polygon):
                painter.setPen(QPen(QColor("#241B08"), 1))
                painter.setBrush(QBrush(QColor("#FFF0B5" if index == self._drag_index else "#D6AE55")))
                painter.drawEllipse(point, 6.0, 6.0)
        else:
            if self._shape == "ellipse":
                painter.drawEllipse(rect)
            else:
                painter.drawRect(rect)
            if self._geometry_editable:
                painter.setPen(QPen(QColor("#241B08"), 1))
                painter.setBrush(QBrush(QColor("#FFF0B5")))
                for point in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
                    painter.drawEllipse(point, 6.0, 6.0)
                painter.setBrush(QBrush(QColor("#D6AE55")))
                painter.drawEllipse(rect.center(), 4.5, 4.5)
        painter.restore()
        if self._geometry_editable and self._shape in {"rectangle", "ellipse"}:
            handle = self._rotation_handle()
            painter.setPen(QPen(QColor("#D6AE55"), 1.5))
            painter.setBrush(QBrush(QColor("#FFF0B5")))
            top = self._to_widget(self._rect[0] + self._rect[2] / 2, self._rect[1])
            painter.drawLine(self._rect_widget().center() + self._rotate_vector(top - self._rect_widget().center(), self._rotation), handle)
            painter.drawEllipse(handle, 7.0, 7.0)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self._active:
            event.ignore()
            return
        if self._shape == "polygon":
            index = self._hit_polygon(event.position())
            if index is not None:
                self._drag_kind, self._drag_index = "point", index
        if self._geometry_editable and self._shape in {"rectangle", "ellipse"}:
            self._drag_kind = self._hit_geometry(event.position())
            if self._drag_kind == "rotate":
                from math import atan2, degrees
                center = self._rect_widget().center()
                self._pointer_angle_start = degrees(atan2(
                    event.position().y() - center.y(), event.position().x() - center.x()
                ))
                self._rotation_start = self._rotation
        if self._drag_kind:
            self._last_pos = event.position()
            self.editingStarted.emit()
            self.update()
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self._drag_kind == "point" and self._drag_index is not None:
            self._points[self._drag_index] = list(self._to_normalized(self._local_pos(event.position())))
            self.pointsChanged.emit([[round(x, 6), round(y, 6)] for x, y in self._points])
            self.update()
            event.accept()
            return
        if self._drag_kind == "rotate":
            from math import atan2, degrees
            center = self._rect_widget().center()
            pointer_angle = degrees(atan2(
                event.position().y() - center.y(), event.position().x() - center.x()
            ))
            delta = (pointer_angle - self._pointer_angle_start + 180.0) % 360.0 - 180.0
            self._rotation = max(-3600.0, min(3600.0, self._rotation_start + delta))
            self.rotationChanged.emit(round(self._rotation, 4))
            self.update()
            event.accept()
            return
        if self._drag_kind and self._shape in {"rectangle", "ellipse"}:
            dx, dy = event.position().x() - self._last_pos.x(), event.position().y() - self._last_pos.y()
            frame = self._video_rect()
            if frame.width() <= 0 or frame.height() <= 0:
                return
            if self._drag_kind != "move":
                local_delta = self._rotate_vector(QPointF(dx, dy), -self._rotation)
                dx, dy = local_delta.x(), local_delta.y()
            nx, ny = dx / frame.width(), dy / frame.height()
            x, y, width, height = self._rect
            if self._drag_kind == "move":
                x = max(0.0, min(1.0 - width, x + nx))
                y = max(0.0, min(1.0 - height, y + ny))
            else:
                left, top, right, bottom = x, y, x + width, y + height
                if "w" in self._drag_kind:
                    left = max(0.0, min(right - 0.01, left + nx))
                if "e" in self._drag_kind:
                    right = max(left + 0.01, min(1.0, right + nx))
                if "n" in self._drag_kind:
                    top = max(0.0, min(bottom - 0.01, top + ny))
                if "s" in self._drag_kind:
                    bottom = max(top + 0.01, min(1.0, bottom + ny))
                x, y, width, height = left, top, right - left, bottom - top
            self._rect = [x, y, width, height]
            self._last_pos = event.position()
            self.geometryChanged.emit(list(self._rect))
            self.update()
            event.accept()
            return
        if self._shape == "polygon":
            self.setCursor(Qt.OpenHandCursor if self._hit_polygon(event.position()) is not None else Qt.ArrowCursor)
        elif self._geometry_editable:
            hit = self._hit_geometry(event.position())
            self.setCursor(Qt.SizeAllCursor if hit == "move" else Qt.CrossCursor if hit == "rotate" else Qt.SizeFDiagCursor if hit in {"nw", "se"} else Qt.SizeBDiagCursor if hit else Qt.ArrowCursor)
        event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_kind:
            self._drag_kind = None
            self._drag_index = None
            self.update()
            event.accept()
            return
        event.ignore()
