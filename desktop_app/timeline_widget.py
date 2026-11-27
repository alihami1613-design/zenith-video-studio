"""Lightweight multitrack timeline with trim handles, snapping and frame-based edits."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPoint, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPainterPath, QPolygonF
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QFrame

TRACKS = ("V4", "V3", "V2", "V1", "A1", "A2", "A3", "A4")
RULER_HEIGHT, TRACK_HEIGHT, LABEL_WIDTH = 30, 42, 54
MIN_PIXELS_PER_SECOND, MAX_PIXELS_PER_SECOND = 12, 120
TRIM_HANDLE_PX = 8
SNAP_DISTANCE_PX = 9


class TimelineCanvas(QWidget):
    clipSelected = Signal(str)
    playheadChanged = Signal(int)
    clipMoved = Signal(str, int, str)
    clipTrimmed = Signal(str, int, int)
    editStarted = Signal()
    speedRampChanged = Signal(str, list)
    transformKeyframeMoved = Signal(str, int, int)
    transformKeyframeSelected = Signal(str, int)
    maskKeyframeMoved = Signal(str, int, int)
    maskKeyframeSelected = Signal(str, int)

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.pixels_per_second = 30
        self.selected_clip_id = None
        self._drag_clip_id = None
        self._drag_origin = QPoint()
        self._drag_start_frame = 0
        self._drag_track = "V1"
        self._drag_mode = "move"
        self._original_end = 0
        self._original_source_in = 0
        self._preview_state = None
        self._drag_ramp_index = None
        self._drag_transform_keyframe_frame = None
        self._preview_transform_keyframe_frame = None
        self.selected_transform_keyframe_frame = None
        self._drag_mask_keyframe_frame = None
        self._preview_mask_keyframe_frame = None
        self.selected_mask_keyframe_frame = None
        self._preview_ramp_points = None
        self._playhead_dragging = False
        self.waveforms = {}
        self.setMouseTracking(True)
        self.setMinimumHeight(RULER_HEIGHT + len(TRACKS) * TRACK_HEIGHT + 2)
        self.setMinimumWidth(900)

    def sizeHint(self):
        seconds = max(30, self.project.duration_frames / max(1, self.project.fps) + 10)
        return QSize(min(20000, max(900, LABEL_WIDTH + int(seconds * self.pixels_per_second))), RULER_HEIGHT + len(TRACKS) * TRACK_HEIGHT)

    def set_waveforms(self, waveforms):
        self.waveforms = waveforms or {}
        self.update()

    def set_project(self, project):
        self.project = project
        self._preview_state = None
        self._drag_clip_id = None
        self.update_geometry_for_project()
        self.update()

    def set_zoom(self, value):
        self.pixels_per_second = max(MIN_PIXELS_PER_SECOND, min(MAX_PIXELS_PER_SECOND, int(value)))
        self.update_geometry_for_project()
        self.update()

    def update_geometry_for_project(self):
        seconds = max(30, self.project.duration_frames / max(1, self.project.fps) + 10)
        self.setMinimumWidth(min(20000, max(900, LABEL_WIDTH + int(seconds * self.pixels_per_second))))
        self.resize(self.sizeHint())
        self.updateGeometry()

    def _frame_x(self, frame):
        return LABEL_WIDTH + int((frame / max(1, self.project.fps)) * self.pixels_per_second)

    def _x_frame(self, x):
        return max(0, int(round(max(0, x - LABEL_WIDTH) / max(1, self.pixels_per_second) * self.project.fps)))

    def _track_at(self, y):
        index = (y - RULER_HEIGHT) // TRACK_HEIGHT
        return TRACKS[index] if 0 <= index < len(TRACKS) else None

    def _clip_at(self, point):
        track = self._track_at(point.y())
        if not track:
            return None
        for clip in reversed(self.project.clips_on_track(track)):
            left, right = self._frame_x(clip.start_frame), self._frame_x(clip.end_frame)
            if left - TRIM_HANDLE_PX <= point.x() <= right + TRIM_HANDLE_PX:
                return clip
        return None

    def _snap(self, frame, clip_id, mode):
        """Snap moved/trimmed edges to nearby clip boundaries and playhead."""
        candidates = [self.project.playhead_frame]
        for other in self.project.clips:
            if other.clip_id != clip_id:
                candidates.extend((other.start_frame, other.end_frame))
        threshold = max(1, round(SNAP_DISTANCE_PX / max(1, self.pixels_per_second) * self.project.fps))
        nearest = min(candidates, key=lambda point: abs(point - frame), default=frame)
        return nearest if abs(nearest - frame) <= threshold else frame

    def _drag_mode_for(self, clip, x):
        left, right = self._frame_x(clip.start_frame), self._frame_x(clip.end_frame)
        if abs(x - left) <= TRIM_HANDLE_PX:
            return "left"
        if abs(x - right) <= TRIM_HANDLE_PX:
            return "right"
        return "move"

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
            painter.fillRect(0, y, width, TRACK_HEIGHT, QColor("#191A1D") if index % 2 == 0 else QColor("#16171A"))
            painter.fillRect(0, y, LABEL_WIDTH, TRACK_HEIGHT, QColor("#242529"))
            painter.setPen(QColor("#D6AE55") if track.startswith("V") else QColor("#8EB6C8"))
            painter.drawText(12, y + 25, track)
            painter.setPen(QPen(QColor("#303136"), 1))
            painter.drawLine(0, y + TRACK_HEIGHT - 1, width, y + TRACK_HEIGHT - 1)
            for clip in self.project.clips:
                preview = self._preview_state if self._preview_state and self._preview_state["clip_id"] == clip.clip_id else None
                clip_track = preview["track"] if preview else clip.track
                if clip_track != track:
                    continue
                start_frame = preview["start_frame"] if preview else clip.start_frame
                duration_frames = preview["duration_frames"] if preview else clip.duration_frames
                end_frame = start_frame + duration_frames
                x1, x2 = self._frame_x(start_frame), max(self._frame_x(start_frame) + 5, self._frame_x(end_frame))
                rect_y, rect_h = y + 5, TRACK_HEIGHT - 10
                selected = clip.clip_id == self.selected_clip_id
                fill = QColor("#A77F35") if selected and track.startswith("V") else QColor("#477E91") if selected else QColor("#66502C") if track.startswith("V") else QColor("#315766")
                painter.setBrush(QBrush(fill))
                painter.setPen(QPen(QColor("#F3D58F") if selected else fill.lighter(135), 1))
                painter.drawRoundedRect(x1, rect_y, x2 - x1, rect_h, 4, 4)
                # Keep clip-level audio state visible without opening Inspector.
                audio_badges = []
                if bool(getattr(clip, "audio_muted", False)):
                    audio_badges.append(("MUTE", QColor("#7A3434")))
                elif bool(getattr(clip, "audio_solo", False)):
                    audio_badges.append(("SOLO", QColor("#28745E")))
                if audio_badges and x2 - x1 >= 42:
                    painter.save()
                    painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
                    badge_x = x1 + 5
                    for badge_text, badge_color in audio_badges:
                        badge_width = painter.fontMetrics().horizontalAdvance(badge_text) + 8
                        badge_rect = painter.boundingRect(
                            badge_x, rect_y + 2, badge_width, 13,
                            Qt.AlignCenter, badge_text,
                        )
                        painter.setPen(Qt.NoPen)
                        painter.setBrush(QBrush(badge_color))
                        painter.drawRoundedRect(badge_rect, 3, 3)
                        painter.setPen(QColor("#FFFFFF"))
                        painter.drawText(badge_rect, Qt.AlignCenter, badge_text)
                        badge_x += badge_width + 3
                    painter.restore()
                has_audio = clip.media_type == "audio" or (
                    clip.media_type == "video" and bool(getattr(clip, "has_audio", False))
                )
                waveform = self.waveforms.get(clip.path) if has_audio else None
                if waveform:
                    # Keep embedded-video waveforms in the lower half so the
                    # clip title remains readable; audio-only clips use the
                    # full center band for a larger, clearer envelope.
                    if clip.media_type == "video":
                        center_y = rect_y + rect_h * 3 // 4
                        half_height = max(2, rect_h // 4 - 2)
                    else:
                        center_y = rect_y + rect_h // 2
                        half_height = max(2, rect_h // 2 - 4)
                    samples_per_second = 20.0
                    first_sample = max(0, int((clip.source_in / max(1, self.project.fps)) * samples_per_second))
                    visible_width = max(0, x2 - x1 - 8)
                    for pixel_offset in range(visible_width):
                        sample_index = first_sample + int(
                            (pixel_offset / max(1, self.pixels_per_second)) * samples_per_second
                        )
                        if sample_index >= len(waveform):
                            break
                        amplitude = waveform[sample_index]
                        relative_frame = (
                            pixel_offset / max(1, self.pixels_per_second)
                        ) * self.project.fps
                        envelope = min(1.0, max(0.0, clip.volume))
                        if clip.fade_in_frames:
                            envelope = min(
                                envelope,
                                relative_frame / max(1, clip.fade_in_frames),
                            )
                        if clip.fade_out_frames:
                            remaining = clip.duration_frames - relative_frame
                            envelope = min(
                                envelope,
                                remaining / max(1, clip.fade_out_frames),
                            )
                        bar_height = max(1, int(amplitude * half_height * max(0.0, envelope)))
                        px = x1 + 4 + pixel_offset
                        painter.setPen(QPen(QColor("#B7D8E5"), 1))
                        painter.drawLine(px, center_y - bar_height, px, center_y + bar_height)
                ramp_source = (
                    self._preview_ramp_points
                    if self._drag_clip_id == clip.clip_id and self._preview_ramp_points is not None
                    else getattr(clip, "speed_ramp", [])
                )
                ramp_points = sorted(
                    ramp_source or [], key=lambda point: int(point["frame"])
                ) if clip.media_type == "video" else []
                if ramp_points and duration_frames > 0:
                    def ramp_y(rate):
                        normalized = (max(0.25, min(4.0, float(rate))) - 0.25) / 3.75
                        return rect_y + rect_h - 5 - int(normalized * max(1, rect_h - 10))
                    path = QPainterPath()
                    first_x = x1 + 3
                    last_x = x2 - 3
                    first_rate = float(ramp_points[0]["rate"])
                    path.moveTo(first_x, ramp_y(first_rate))
                    for point in ramp_points:
                        point_x = x1 + int(
                            max(0, min(duration_frames, int(point["frame"]))) /
                            max(1, duration_frames) * (x2 - x1)
                        )
                        path.lineTo(point_x, ramp_y(point["rate"]))
                    path.lineTo(last_x, ramp_y(ramp_points[-1]["rate"]))
                    painter.setPen(QPen(QColor("#FFF0A6"), 2))
                    painter.setBrush(QBrush(QColor("#FFF0A6")))
                    painter.drawPath(path)
                    for point in ramp_points:
                        point_x = x1 + int(
                            max(0, min(duration_frames, int(point["frame"]))) /
                            max(1, duration_frames) * (x2 - x1)
                        )
                        painter.drawEllipse(point_x - 3, ramp_y(point["rate"]) - 3, 6, 6)
                if selected and clip.media_type == "video" and clip.track.startswith("V"):
                    key_y = rect_y + rect_h // 2
                    for key in clip.transform_keyframes:
                        original_frame = int(key["frame"])
                        shown_frame = (self._preview_transform_keyframe_frame
                                       if self._drag_transform_keyframe_frame == original_frame
                                       and self._preview_transform_keyframe_frame is not None
                                       else original_frame)
                        key_x = x1 + int(shown_frame / max(1, clip.duration_frames) * (x2 - x1))
                        diamond = QPolygonF([QPoint(key_x, key_y - 6), QPoint(key_x + 6, key_y),
                                             QPoint(key_x, key_y + 6), QPoint(key_x - 6, key_y)])
                        active = original_frame == self.selected_transform_keyframe_frame
                        painter.setBrush(QBrush(QColor("#FFF1B8") if active else QColor("#F2D27A")))
                        painter.setPen(QPen(QColor("#33270D"), 1))
                        painter.drawPolygon(diamond)
                    for key in clip.mask_keyframes:
                        mask_frame = int(key["frame"])
                        shown_mask_frame = (self._preview_mask_keyframe_frame
                                            if self._drag_mask_keyframe_frame == mask_frame
                                            and self._preview_mask_keyframe_frame is not None
                                            else mask_frame)
                        mask_x = x1 + int(shown_mask_frame / max(1, clip.duration_frames) * (x2 - x1))
                        mask_y = rect_y + rect_h - 8
                        mask_diamond = QPolygonF([
                            QPoint(mask_x, mask_y - 4), QPoint(mask_x + 4, mask_y),
                            QPoint(mask_x, mask_y + 4), QPoint(mask_x - 4, mask_y),
                        ])
                        active_mask = mask_frame == self.selected_mask_keyframe_frame
                        painter.setBrush(QBrush(QColor("#D1FFF6") if active_mask else QColor("#75D6C8")))
                        painter.setPen(QPen(QColor("#123A35"), 1))
                        painter.drawPolygon(mask_diamond)
                if selected:
                    painter.fillRect(x1, rect_y, 4, rect_h, QColor("#FFF0C2"))
                    painter.fillRect(x2 - 4, rect_y, 4, rect_h, QColor("#FFF0C2"))
                painter.setPen(QColor("#FFFFFF"))
                painter.setFont(QFont("Segoe UI", 8))
                painter.drawText(x1 + 6, rect_y + 17, max(0, x2 - x1 - 10), 15, Qt.AlignLeft | Qt.AlignVCenter, clip.name)
        playhead_x = self._frame_x(self.project.playhead_frame)
        painter.setPen(QPen(QColor("#E45D5D"), 2))
        painter.drawLine(playhead_x, 0, playhead_x, height)
        painter.end()

    def _ramp_point_y(self, rate: float, clip) -> int:
        track_index = TRACKS.index(clip.track)
        rect_y = RULER_HEIGHT + track_index * TRACK_HEIGHT + 5
        rect_h = TRACK_HEIGHT - 10
        normalized = (max(0.25, min(4.0, float(rate))) - 0.25) / 3.75
        return rect_y + rect_h - 5 - int(normalized * max(1, rect_h - 10))

    def _ramp_point_at(self, clip, point):
        if clip.media_type != "video" or not getattr(clip, "speed_ramp", None):
            return None
        left, right = self._frame_x(clip.start_frame), self._frame_x(clip.end_frame)
        width = max(1, right - left)
        nearest = None
        nearest_distance = 10 ** 9
        for index, key in enumerate(clip.speed_ramp):
            x = left + int(int(key["frame"]) / max(1, clip.duration_frames) * width)
            y = self._ramp_point_y(float(key["rate"]), clip)
            distance = (point.x() - x) ** 2 + (point.y() - y) ** 2
            if distance <= 100 and distance < nearest_distance:
                nearest, nearest_distance = index, distance
        return nearest

    def _transform_keyframe_at(self, clip, point):
        if clip.media_type != "video" or not clip.track.startswith("V"):
            return None
        left, right = self._frame_x(clip.start_frame), self._frame_x(clip.end_frame)
        width = max(1, right - left)
        center_y = RULER_HEIGHT + TRACKS.index(clip.track) * TRACK_HEIGHT + TRACK_HEIGHT // 2
        nearest, distance_min = None, 145
        for key in clip.transform_keyframes:
            frame = int(key["frame"])
            x = left + int(frame / max(1, clip.duration_frames) * width)
            distance = (point.x() - x) ** 2 + (point.y() - center_y) ** 2
            if distance < distance_min:
                nearest, distance_min = frame, distance
        return nearest

    def _mask_keyframe_at(self, clip, point):
        if clip.media_type != "video" or not clip.track.startswith("V"):
            return None
        left, right = self._frame_x(clip.start_frame), self._frame_x(clip.end_frame)
        width = max(1, right - left)
        track_y = RULER_HEIGHT + TRACKS.index(clip.track) * TRACK_HEIGHT + 5
        marker_y = track_y + (TRACK_HEIGHT - 10) - 8
        nearest, distance_min = None, 81
        for key in clip.mask_keyframes:
            frame = int(key["frame"])
            x = left + int(frame / max(1, clip.duration_frames) * width)
            distance = (point.x() - x) ** 2 + (point.y() - marker_y) ** 2
            if distance < distance_min:
                nearest, distance_min = frame, distance
        return nearest

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        point = event.position().toPoint()
        clip = self._clip_at(point)
        if clip:
            self.selected_clip_id = clip.clip_id
            keyframe_frame = self._transform_keyframe_at(clip, point)
            if keyframe_frame is not None:
                self.selected_transform_keyframe_frame = keyframe_frame
                self._drag_clip_id = clip.clip_id
                self._drag_mode = "transform_keyframe"
                self._drag_transform_keyframe_frame = keyframe_frame
                self._preview_transform_keyframe_frame = keyframe_frame
                self._drag_origin = point
                self.editStarted.emit()
                self.clipSelected.emit(clip.clip_id)
                self.transformKeyframeSelected.emit(clip.clip_id, keyframe_frame)
                self.update()
                return
            mask_frame = self._mask_keyframe_at(clip, point)
            if mask_frame is not None:
                self.selected_mask_keyframe_frame = mask_frame
                self._drag_clip_id = clip.clip_id
                self._drag_mode = "mask_keyframe"
                self._drag_mask_keyframe_frame = mask_frame
                self._preview_mask_keyframe_frame = mask_frame
                self._drag_origin = point
                self.editStarted.emit()
                self.clipSelected.emit(clip.clip_id)
                self.maskKeyframeSelected.emit(clip.clip_id, mask_frame)
                self.update()
                return
            self.selected_transform_keyframe_frame = None
            self.selected_mask_keyframe_frame = None
            self._drag_clip_id = clip.clip_id
            self._drag_origin = point
            self._drag_start_frame = clip.start_frame
            self._drag_track = clip.track
            self._original_end = clip.end_frame
            self._original_source_in = clip.source_in
            ramp_index = self._ramp_point_at(clip, point)
            if ramp_index is not None:
                self._drag_mode = "ramp"
                self._drag_ramp_index = ramp_index
                self._preview_ramp_points = [dict(item) for item in clip.speed_ramp]
            else:
                self._drag_mode = self._drag_mode_for(clip, point.x())
                self._drag_ramp_index = None
                self._preview_ramp_points = None
            self.editStarted.emit()
            self.clipSelected.emit(clip.clip_id)
        else:
            self.selected_clip_id = None
            self._drag_clip_id = None
            self._playhead_dragging = True
            self.playheadChanged.emit(self._x_frame(point.x()))
        self.update()

    def mouseMoveEvent(self, event):
        if self._playhead_dragging and (event.buttons() & Qt.LeftButton):
            self.playheadChanged.emit(self._x_frame(event.position().toPoint().x()))
            return
        if not self._drag_clip_id or not (event.buttons() & Qt.LeftButton):
            return
        delta_x = event.position().toPoint().x() - self._drag_origin.x()
        delta_frames = int(round(delta_x / max(1, self.pixels_per_second) * self.project.fps))
        clip = self.project.get_clip(self._drag_clip_id)
        if self._drag_mode == "transform_keyframe":
            keys = sorted(clip.transform_keyframes, key=lambda item: int(item["frame"]))
            index = next((i for i, item in enumerate(keys) if int(item["frame"]) == self._drag_transform_keyframe_frame), -1)
            if index >= 0:
                left = self._frame_x(clip.start_frame)
                width = max(1, self._frame_x(clip.end_frame) - left)
                local = int(round((event.position().toPoint().x() - left) / width * clip.duration_frames))
                low = int(keys[index - 1]["frame"]) + 1 if index else 0
                high = int(keys[index + 1]["frame"]) - 1 if index + 1 < len(keys) else clip.duration_frames - 1
                self._preview_transform_keyframe_frame = max(low, min(high, local))
        elif self._drag_mode == "mask_keyframe":
            keys = sorted(clip.mask_keyframes, key=lambda item: int(item["frame"]))
            index = next((i for i, item in enumerate(keys) if int(item["frame"]) == self._drag_mask_keyframe_frame), -1)
            if index >= 0:
                left = self._frame_x(clip.start_frame)
                width = max(1, self._frame_x(clip.end_frame) - left)
                local = int(round((event.position().toPoint().x() - left) / width * clip.duration_frames))
                low = int(keys[index - 1]["frame"]) + 1 if index else 0
                high = int(keys[index + 1]["frame"]) - 1 if index + 1 < len(keys) else clip.duration_frames - 1
                self._preview_mask_keyframe_frame = max(low, min(high, local))
        elif self._drag_mode == "ramp":
            index = self._drag_ramp_index
            if index is not None and self._preview_ramp_points:
                left = self._frame_x(clip.start_frame)
                width = max(1, self._frame_x(clip.end_frame) - left)
                local_frame = int(round(
                    (event.position().toPoint().x() - left) / width * clip.duration_frames
                ))
                previous_frame = (
                    int(self._preview_ramp_points[index - 1]["frame"]) + 1
                    if index > 0 else 0
                )
                next_frame = (
                    int(self._preview_ramp_points[index + 1]["frame"]) - 1
                    if index + 1 < len(self._preview_ramp_points)
                    else clip.duration_frames - 1
                )
                local_frame = max(previous_frame, min(next_frame, local_frame))
                track_index = TRACKS.index(clip.track)
                rect_y = RULER_HEIGHT + track_index * TRACK_HEIGHT + 5
                rect_h = TRACK_HEIGHT - 10
                rate_range = max(1, rect_h - 10)
                normalized = (rect_y + rect_h - 5 - event.position().toPoint().y()) / rate_range
                rate = 0.25 + max(0.0, min(1.0, normalized)) * 3.75
                self._preview_ramp_points[index] = {
                    "frame": local_frame, "rate": round(rate, 2)
                }
        elif self._drag_mode == "move":
            new_start = self._snap(max(0, self._drag_start_frame + delta_frames), clip.clip_id, "move")
            target_track = self._track_at(event.position().toPoint().y()) or self._drag_track
            if target_track.startswith("V") != self._drag_track.startswith("V"):
                target_track = self._drag_track
            self._preview_state = {
                "clip_id": clip.clip_id, "start_frame": max(0, new_start),
                "track": target_track, "source_in": clip.source_in,
                "duration_frames": clip.duration_frames,
            }
        elif self._drag_mode == "left":
            proposed = self._snap(self._drag_start_frame + delta_frames, clip.clip_id, "left")
            earliest_start = max(0, self._drag_start_frame - self._original_source_in)
            new_start = max(earliest_start, min(proposed, self._original_end - 1))
            self._preview_state = {
                "clip_id": clip.clip_id, "start_frame": new_start,
                "track": self._drag_track,
                "source_in": self._original_source_in + (new_start - self._drag_start_frame),
                "duration_frames": self._original_end - new_start,
            }
        else:
            proposed = self._snap(self._original_end + delta_frames, clip.clip_id, "right")
            new_end = max(self._drag_start_frame + 1, proposed)
            self._preview_state = {
                "clip_id": clip.clip_id, "start_frame": self._drag_start_frame,
                "track": self._drag_track, "source_in": self._original_source_in,
                "duration_frames": new_end - self._drag_start_frame,
            }
        self.update()

    def mouseReleaseEvent(self, event):
        if self._playhead_dragging:
            self._playhead_dragging = False
            self.update()
            return
        if not self._drag_clip_id:
            return
        clip = self.project.get_clip(self._drag_clip_id)
        preview = self._preview_state
        if self._drag_mode == "mask_keyframe":
            if (self._drag_mask_keyframe_frame is not None and self._preview_mask_keyframe_frame is not None
                    and self._preview_mask_keyframe_frame != self._drag_mask_keyframe_frame):
                self.maskKeyframeMoved.emit(clip.clip_id, self._drag_mask_keyframe_frame, self._preview_mask_keyframe_frame)
        elif self._drag_mode == "transform_keyframe":
            if (self._drag_transform_keyframe_frame is not None and self._preview_transform_keyframe_frame is not None
                    and self._preview_transform_keyframe_frame != self._drag_transform_keyframe_frame):
                self.transformKeyframeMoved.emit(clip.clip_id, self._drag_transform_keyframe_frame, self._preview_transform_keyframe_frame)
        elif self._drag_mode == "ramp" and self._preview_ramp_points is not None:
            if self._preview_ramp_points != clip.speed_ramp:
                self.speedRampChanged.emit(clip.clip_id, self._preview_ramp_points)
        elif preview:
            if self._drag_mode == "move":
                if preview["start_frame"] != clip.start_frame or preview["track"] != clip.track:
                    self.clipMoved.emit(clip.clip_id, preview["start_frame"], preview["track"])
            else:
                end_frame = preview["start_frame"] + preview["duration_frames"]
                if preview["start_frame"] != clip.start_frame or end_frame != clip.end_frame:
                    self.clipTrimmed.emit(clip.clip_id, preview["start_frame"], end_frame)
        self._preview_state = None
        self._preview_ramp_points = None
        self._drag_ramp_index = None
        self._drag_transform_keyframe_frame = None
        self._preview_transform_keyframe_frame = None
        self._drag_mask_keyframe_frame = None
        self._preview_mask_keyframe_frame = None
        self._drag_clip_id = None
        self.update_geometry_for_project()


class TimelineWidget(QWidget):
    clipSelected = Signal(str)
    playheadChanged = Signal(int)
    clipMoved = Signal(str, int, str)
    clipTrimmed = Signal(str, int, int)
    editStarted = Signal()
    speedRampChanged = Signal(str, list)
    transformKeyframeMoved = Signal(str, int, int)
    transformKeyframeSelected = Signal(str, int)

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        toolbar = QHBoxLayout()
        self.info_label = QLabel("کشیدن بدنه: جابه‌جایی | لبه‌ها: کوتاه‌کردن | نقاط Speed Ramp: تغییر زمان و سرعت | چسباندن خودکار")
        self.info_label.setStyleSheet("color:#A7A7A7;")
        toolbar.addWidget(self.info_label)
        toolbar.addStretch(1)
        zoom_out, zoom_in = QPushButton("−"), QPushButton("+")
        zoom_out.setFixedWidth(32); zoom_in.setFixedWidth(32)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(MIN_PIXELS_PER_SECOND, MAX_PIXELS_PER_SECOND)
        self.zoom_slider.setValue(30); self.zoom_slider.setFixedWidth(120)
        zoom_out.clicked.connect(lambda: self.zoom_slider.setValue(self.zoom_slider.value() - 5))
        zoom_in.clicked.connect(lambda: self.zoom_slider.setValue(self.zoom_slider.value() + 5))
        toolbar.addWidget(zoom_out); toolbar.addWidget(self.zoom_slider); toolbar.addWidget(zoom_in)
        root.addLayout(toolbar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.canvas = TimelineCanvas(project)
        self.scroll.setWidget(self.canvas)
        root.addWidget(self.scroll, 1)
        self.zoom_slider.valueChanged.connect(self.canvas.set_zoom)
        self.canvas.clipSelected.connect(self.clipSelected)
        self.canvas.playheadChanged.connect(self.playheadChanged)
        self.canvas.clipMoved.connect(self.clipMoved)
        self.canvas.clipTrimmed.connect(self.clipTrimmed)
        self.canvas.editStarted.connect(self.editStarted)
        self.canvas.speedRampChanged.connect(self.speedRampChanged)
        self.canvas.transformKeyframeMoved.connect(self.transformKeyframeMoved)
        self.canvas.transformKeyframeSelected.connect(self.transformKeyframeSelected)
        self.canvas.maskKeyframeMoved.connect(self.maskKeyframeMoved)
        self.canvas.maskKeyframeSelected.connect(self.maskKeyframeSelected)

    def set_project(self, project):
        self.project = project
        self.canvas.set_project(project)

    def set_waveforms(self, waveforms):
        self.canvas.set_waveforms(waveforms)

    def refresh(self):
        self.canvas.update_geometry_for_project()
        self.canvas.update()
