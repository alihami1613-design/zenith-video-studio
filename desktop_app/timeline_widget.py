"""Lightweight, frame-based multitrack timeline widget for ZENITH Desktop.

The widget only paints the visible project data; it does not decode media.
Editing operations are emitted as signals so the project model remains the
single source of truth.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPoint, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSlider,
)

TRACKS = ("V4", "V3", "V2", "V1", "A1", "A2", "A3", "A4")
RULER_HEIGHT = 30
TRACK_HEIGHT = 42
LABEL_WIDTH = 54
MIN_PIXELS_PER_SECOND = 12
MAX_PIXELS_PER_SECOND = 120


class TimelineCanvas(QWidget):
    clipSelected = Signal(str)
    playheadChanged = Signal(int)
    clipMoved = Signal(str, int, str)

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.pixels_per_second = 30
        self.selected_clip_id = None
        self._drag_clip_id = None
        self._drag_origin = QPoint()
        self._drag_start_frame = 0
        self._drag_track = "V1"
        self.setMouseTracking(True)
        self.setMinimumHeight(RULER_HEIGHT + len(TRACKS) * TRACK_HEIGHT + 2)
        self.setMinimumWidth(900)

    def sizeHint(self):
        seconds = max(30, (self.project.duration_frames / max(1, self.project.fps)) + 10)
        return QSize(min(20000, max(900, LABEL_WIDTH + int(seconds * self.pixels_per_second))),
                     RULER_HEIGHT + len(TRACKS) * TRACK_HEIGHT)

    def set_project(self, project):
        self.project = project
        self.update_geometry_for_project()
        self.update()

    def set_zoom(self, value):
        self.pixels_per_second = max(MIN_PIXELS_PER_SECOND, min(MAX_PIXELS_PER_SECOND, int(value)))
        self.update_geometry_for_project()
        self.update()

    def update_geometry_for_project(self):
        seconds = max(30, (self.project.duration_frames / max(1, self.project.fps)) + 10)
        width = LABEL_WIDTH + int(seconds * self.pixels_per_second)
        self.setMinimumWidth(min(20000, max(900, width)))
        self.updateGeometry()

    def _frame_x(self, frame):
        return LABEL_WIDTH + int((frame / max(1, self.project.fps)) * self.pixels_per_second)

    def _x_frame(self, x):
        seconds = max(0, x - LABEL_WIDTH) / max(1, self.pixels_per_second)
        return max(0, int(round(seconds * self.project.fps)))

    def _track_at(self, y):
        index = (y - RULER_HEIGHT) // TRACK_HEIGHT
        return TRACKS[index] if 0 <= index < len(TRACKS) else None

    def _clip_at(self, point):
        track = self._track_at(point.y())
        if not track:
            return None
        frame = self._x_frame(point.x())
        for clip in reversed(self.project.clips_on_track(track)):
            if clip.start_frame <= frame < clip.end_frame:
                return clip
        return None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101113"))
        painter.setRenderHint(QPainter.Antialiasing, False)
        width = self.width()
        height = RULER_HEIGHT + len(TRACKS) * TRACK_HEIGHT

        painter.fillRect(0, 0, width, RULER_HEIGHT, QColor("#202125"))
        painter.setPen(QPen(QColor("#777777"), 1))
        painter.setFont(QFont("Segoe UI", 8))
        seconds_visible = max(1, int((width - LABEL_WIDTH) / max(1, self.pixels_per_second)))
        step = 5 if self.pixels_per_second >= 24 else 10
        for sec in range(0, seconds_visible + step, step):
            x = LABEL_WIDTH + sec * self.pixels_per_second
            painter.drawLine(x, 0, x, height)
            painter.drawText(x + 3, 19, f"{sec // 60:02d}:{sec % 60:02d}")

        for index, track in enumerate(TRACKS):
            y = RULER_HEIGHT + index * TRACK_HEIGHT
            bg = QColor("#191A1D") if index % 2 == 0 else QColor("#16171A")
            painter.fillRect(0, y, width, TRACK_HEIGHT, bg)
            painter.fillRect(0, y, LABEL_WIDTH, TRACK_HEIGHT, QColor("#242529"))
            painter.setPen(QColor("#D6AE55") if track.startswith("V") else QColor("#8EB6C8"))
            painter.drawText(12, y + 25, track)
            painter.setPen(QPen(QColor("#303136"), 1))
            painter.drawLine(0, y + TRACK_HEIGHT - 1, width, y + TRACK_HEIGHT - 1)

            for clip in self.project.clips_on_track(track):
                x1 = self._frame_x(clip.start_frame)
                x2 = max(x1 + 5, self._frame_x(clip.end_frame))
                rect_y = y + 5
                rect_h = TRACK_HEIGHT - 10
                if clip.clip_id == self.selected_clip_id:
                    fill = QColor("#A77F35") if track.startswith("V") else QColor("#477E91")
                    border = QColor("#F3D58F")
                else:
                    fill = QColor("#66502C") if track.startswith("V") else QColor("#315766")
                    border = fill.lighter(135)
                painter.setBrush(QBrush(fill))
                painter.setPen(QPen(border, 1))
                painter.drawRoundedRect(x1, rect_y, x2 - x1, rect_h, 4, 4)
                painter.setPen(QColor("#FFFFFF"))
                painter.setFont(QFont("Segoe UI", 8))
                painter.drawText(x1 + 6, rect_y + 17, max(0, x2 - x1 - 10), 15,
                                 Qt.AlignLeft | Qt.AlignVCenter, clip.name)

        playhead_x = self._frame_x(self.project.playhead_frame)
        painter.setPen(QPen(QColor("#E45D5D"), 2))
        painter.drawLine(playhead_x, 0, playhead_x, height)
        painter.setBrush(QColor("#E45D5D"))
        painter.setPen(Qt.NoPen)
        painter.drawLine(playhead_x - 5, 0, playhead_x + 5, 0)
        painter.drawLine(playhead_x - 5, 0, playhead_x, 8)
        painter.drawLine(playhead_x + 5, 0, playhead_x, 8)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        point = event.position().toPoint()
        clip = self._clip_at(point)
        if clip:
            self.selected_clip_id = clip.clip_id
            self._drag_clip_id = clip.clip_id
            self._drag_origin = point
            self._drag_start_frame = clip.start_frame
            self._drag_track = clip.track
            self.clipSelected.emit(clip.clip_id)
        else:
            self.selected_clip_id = None
            if point.y() >= RULER_HEIGHT:
                self.playheadChanged.emit(self._x_frame(point.x()))
        self.update()

    def mouseMoveEvent(self, event):
        if self._drag_clip_id and (event.buttons() & Qt.LeftButton):
            delta_x = event.position().toPoint().x() - self._drag_origin.x()
            delta_frames = int(round((delta_x / max(1, self.pixels_per_second)) * self.project.fps))
            preview_start = max(0, self._drag_start_frame + delta_frames)
            self.project.get_clip(self._drag_clip_id).start_frame = preview_start
            target_track = self._track_at(event.position().toPoint().y()) or self._drag_track
            if target_track == self._drag_track or (
                target_track.startswith("V") == self._drag_track.startswith("V")
            ):
                self.project.get_clip(self._drag_clip_id).track = target_track
            self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_clip_id:
            clip = self.project.get_clip(self._drag_clip_id)
            self.clipMoved.emit(clip.clip_id, clip.start_frame, clip.track)
            self._drag_clip_id = None
            self.update_geometry_for_project()


class TimelineWidget(QWidget):
    clipSelected = Signal(str)
    playheadChanged = Signal(int)
    clipMoved = Signal(str, int, str)

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        toolbar = QHBoxLayout()
        self.info_label = QLabel("تایم‌لاین چندلایه | جابه‌جایی کلیپ با کشیدن ماوس")
        self.info_label.setStyleSheet("color:#A7A7A7;")
        toolbar.addWidget(self.info_label)
        toolbar.addStretch(1)
        zoom_out = QPushButton("−")
        zoom_in = QPushButton("+")
        zoom_out.setFixedWidth(32)
        zoom_in.setFixedWidth(32)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(MIN_PIXELS_PER_SECOND, MAX_PIXELS_PER_SECOND)
        self.zoom_slider.setValue(30)
        self.zoom_slider.setFixedWidth(120)
        zoom_out.clicked.connect(lambda: self.zoom_slider.setValue(self.zoom_slider.value() - 5))
        zoom_in.clicked.connect(lambda: self.zoom_slider.setValue(self.zoom_slider.value() + 5))
        toolbar.addWidget(zoom_out)
        toolbar.addWidget(self.zoom_slider)
        toolbar.addWidget(zoom_in)
        root.addLayout(toolbar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.canvas = TimelineCanvas(project)
        self.scroll.setWidget(self.canvas)
        root.addWidget(self.scroll, 1)

        self.zoom_slider.valueChanged.connect(self.canvas.set_zoom)
        self.canvas.clipSelected.connect(self.clipSelected)
        self.canvas.playheadChanged.connect(self.playheadChanged)
        self.canvas.clipMoved.connect(self.clipMoved)

    def set_project(self, project):
        self.project = project
        self.canvas.set_project(project)

    def refresh(self):
        self.canvas.update_geometry_for_project()
        self.canvas.update()
