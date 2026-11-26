from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl, QSignalBlocker, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QAction, QFont
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QMessageBox,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QSplitter, QFrame, QStatusBar, QSlider
)

from timeline_model import TimelineProject
from timeline_widget import TimelineWidget
from media_probe import probe_media, duration_to_frames

APP_NAME = "ZENITH Desktop"
PROJECT_VERSION = 2
MEDIA_FILTER = (
    "Media files (*.mp4 *.mov *.mkv *.avi *.webm *.mp3 *.wav *.m4a *.aac *.ogg *.flac "
    "*.png *.jpg *.jpeg);;All files (*.*)"
)
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


def format_time(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class MediaProbeSignals(QObject):
    finished = Signal(str, object, str)


class MediaProbeTask(QRunnable):
    """Run metadata probing off the GUI thread; it never decodes media frames."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path
        self.signals = MediaProbeSignals()

    def run(self) -> None:
        try:
            result = probe_media(self.path)
            self.signals.finished.emit(self.path, result, "")
        except Exception as exc:
            self.signals.finished.emit(self.path, None, str(exc))


class ZenithEditor(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project_path: Path | None = None
        self.media_items: list[dict[str, Any]] = []
        self._probe_pool = QThreadPool(self)
        self._probe_pool.setMaxThreadCount(2)
        self._probe_tasks: list[MediaProbeTask] = []
        self.timeline_project = TimelineProject()
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.8)
        self._pending_seek_ms: int | None = None
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.positionChanged.connect(self._position_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.setWindowTitle(f"{APP_NAME} | Video Editor")
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)
        self._build_menu()
        self._build_ui()
        self._apply_theme()
        self.statusBar().showMessage("آماده | فایل‌های رسانه‌ای را وارد کنید")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("فایل")
        actions = [
            ("پروژه جدید", "Ctrl+N", self.new_project),
            ("باز کردن پروژه", "Ctrl+O", self.open_project),
            ("ذخیره پروژه", "Ctrl+S", self.save_project),
            ("وارد کردن رسانه", "Ctrl+I", self.import_media),
        ]
        for title, shortcut, callback in actions:
            action = QAction(title, self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            file_menu.addAction(action)

    def _build_ui(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        header = QHBoxLayout()
        brand = QLabel("ZENITH <span style='color:#D6AE55'>BEYOND</span>")
        brand.setObjectName("brand")
        subtitle = QLabel("DESKTOP VIDEO STUDIO  •  PERFORMANCE FIRST")
        subtitle.setObjectName("subtitle")
        header.addWidget(brand)
        header.addStretch(1)
        header.addWidget(subtitle)
        outer.addLayout(header)

        top_split = QSplitter(Qt.Horizontal)
        media_panel = self._panel("رسانه‌ها")
        media_layout = media_panel.layout()
        self.media_list = QListWidget()
        self.media_list.currentRowChanged.connect(self._preview_media_row)
        self.media_list.itemDoubleClicked.connect(self.add_selected_to_timeline)
        import_btn = QPushButton("＋  وارد کردن فایل")
        import_btn.clicked.connect(self.import_media)
        add_btn = QPushButton("افزودن به تایم‌لاین  →")
        add_btn.clicked.connect(self.add_selected_to_timeline)
        media_layout.addWidget(self.media_list)
        media_layout.addWidget(import_btn)
        media_layout.addWidget(add_btn)

        preview_panel = self._panel("پیش‌نمایش")
        preview_layout = preview_panel.layout()
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(300)
        self.video_widget.setStyleSheet("background:#050506;")
        self.player.setVideoOutput(self.video_widget)
        preview_layout.addWidget(self.video_widget, 1)

        playback = QHBoxLayout()
        self.play_button = QPushButton("▶ پخش")
        self.play_button.clicked.connect(self._toggle_playback)
        stop_button = QPushButton("■ توقف")
        stop_button.clicked.connect(self.player.stop)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("muted")
        playback.addWidget(self.play_button)
        playback.addWidget(stop_button)
        playback.addStretch(1)
        playback.addWidget(self.time_label)
        preview_layout.addLayout(playback)
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderMoved.connect(self.player.setPosition)
        preview_layout.addWidget(self.seek_slider)

        inspector_panel = self._panel("اطلاعات")
        inspector_layout = inspector_panel.layout()
        self.media_info = QLabel("برای پیش‌نمایش، یک فایل را از فهرست رسانه‌ها انتخاب کنید.")
        self.media_info.setWordWrap(True)
        self.media_info.setObjectName("muted")
        inspector_layout.addWidget(self.media_info)
        inspector_layout.addStretch(1)

        top_split.addWidget(media_panel)
        top_split.addWidget(preview_panel)
        top_split.addWidget(inspector_panel)
        top_split.setSizes([280, 760, 300])
        outer.addWidget(top_split, 3)

        timeline_panel = self._panel("تایم‌لاین چندلایه")
        timeline_layout = timeline_panel.layout()
        controls = QHBoxLayout()
        self.playhead_label = QLabel("مکان‌نما: 00:00")
        self.playhead_label.setObjectName("muted")
        controls.addWidget(self.playhead_label)
        controls.addStretch(1)
        self.split_button = QPushButton("تقسیم در مکان‌نما")
        self.split_button.clicked.connect(self.split_selected_clip)
        self.remove_button = QPushButton("حذف کلیپ")
        self.remove_button.clicked.connect(self.remove_selected_from_timeline)
        controls.addWidget(self.split_button)
        controls.addWidget(self.remove_button)
        timeline_layout.addLayout(controls)

        self.timeline_widget = TimelineWidget(self.timeline_project)
        self.timeline_widget.clipSelected.connect(self._select_timeline_clip)
        self.timeline_widget.playheadChanged.connect(self._set_playhead)
        self.timeline_widget.clipMoved.connect(self._clip_moved)
        timeline_layout.addWidget(self.timeline_widget, 1)
        outer.addWidget(timeline_panel, 2)

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())

    def _panel(self, title: str) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 12)
        heading = QLabel(title)
        heading.setObjectName("panel_title")
        layout.addWidget(heading)
        return panel

    def _apply_theme(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#111214; color:#E9E9E9; font-family:'Segoe UI','Tahoma'; font-size:10pt; }
            QMenuBar, QMenu { background:#191A1D; color:#EEE; }
            QMenuBar::item:selected, QMenu::item:selected { background:#33302A; }
            #brand { color:#F4F0E7; font-size:20pt; font-weight:700; letter-spacing:2px; }
            #subtitle { color:#9B9B9B; font-size:8pt; letter-spacing:1px; }
            #panel { background:#191A1D; border:1px solid #303136; border-radius:8px; }
            #panel_title { color:#D6AE55; font-weight:700; padding-bottom:5px; }
            #muted { color:#858585; }
            QListWidget { background:#101113; border:1px solid #303136; border-radius:5px; padding:5px; }
            QListWidget::item { padding:8px; border-bottom:1px solid #26272A; }
            QListWidget::item:selected { background:#393124; color:#F5D78F; }
            QPushButton { background:#28292D; color:#F2F2F2; border:1px solid #49433A; border-radius:5px; padding:7px 11px; }
            QPushButton:hover { background:#393124; border-color:#D6AE55; }
            QSlider::groove:horizontal { height:5px; background:#3A3B3F; border-radius:2px; }
            QSlider::handle:horizontal { background:#D6AE55; width:13px; margin:-5px 0; border-radius:6px; }
            QStatusBar { color:#B8B8B8; background:#191A1D; }
        """)

    def _preview_media_row(self, row: int) -> None:
        if row < 0 or row >= len(self.media_items):
            return
        item = self.media_items[row]
        path = Path(item["path"])
        if not path.exists():
            self.media_info.setText(f"فایل پیدا نشد؛ بعداً امکان اتصال مجدد اضافه می‌شود:\n{path}")
            return
        self._load_preview_source(path, 0)
        self.media_info.setText(f"{item['name']}\n{path}")
        self.statusBar().showMessage(f"آماده پخش: {item['name']}")

    def _select_timeline_clip(self, clip_id: str) -> None:
        try:
            clip = self.timeline_project.get_clip(clip_id)
        except KeyError:
            return
        self.media_info.setText(f"کلیپ انتخاب‌شده: {clip.name}\nمسیر: {clip.track}")
        if Path(clip.path).exists():
            position_ms = int(clip.source_in * 1000 / self.timeline_project.fps)
            self._load_preview_source(Path(clip.path), position_ms)
            for index, media in enumerate(self.media_items):
                if media.get("path") == clip.path:
                    # Updating the bin selection must not reload the source and
                    # cancel the clip's source-in seek.
                    blocker = QSignalBlocker(self.media_list)
                    self.media_list.setCurrentRow(index)
                    del blocker
                    break

    def _load_preview_source(self, path: Path, position_ms: int = 0) -> None:
        self.player.stop()
        self._pending_seek_ms = max(0, int(position_ms))
        self.player.setSource(QUrl.fromLocalFile(str(path)))

    def _apply_pending_seek(self) -> None:
        if self._pending_seek_ms is None:
            return
        target = self._pending_seek_ms
        duration = self.player.duration()
        if duration > 0:
            target = min(target, duration)
        self.player.setPosition(target)
        self._pending_seek_ms = None

    def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self._apply_pending_seek()

    def _set_playhead(self, frame: int) -> None:
        self.timeline_project.playhead_frame = max(0, frame)
        seconds = self.timeline_project.playhead_frame // max(1, self.timeline_project.fps)
        self.playhead_label.setText(f"مکان‌نما: {seconds // 60:02d}:{seconds % 60:02d}")
        self.timeline_widget.refresh()

    def _clip_moved(self, clip_id: str, start_frame: int, track: str) -> None:
        try:
            self.timeline_project.move_clip(clip_id, start_frame, track)
        except (KeyError, ValueError) as exc:
            self.statusBar().showMessage(f"جابه‌جایی انجام نشد: {exc}")
        self.timeline_widget.refresh()

    def _toggle_playback(self) -> None:
        if self.player.source().isEmpty():
            self.statusBar().showMessage("ابتدا یک فایل رسانه‌ای یا کلیپ را انتخاب کنید")
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _duration_changed(self, duration: int) -> None:
        self.seek_slider.setRange(0, duration)
        self._apply_pending_seek()
        self._update_time_label(self.player.position(), duration)

    def _position_changed(self, position: int) -> None:
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(position)
        self._update_time_label(position, self.player.duration())

    def _update_time_label(self, position: int, duration: int) -> None:
        self.time_label.setText(f"{format_time(position)} / {format_time(duration)}")

    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play_button.setText("Ⅱ مکث" if state == QMediaPlayer.PlayingState else "▶ پخش")

    def _refresh_timeline(self) -> None:
        self.timeline_widget.set_project(self.timeline_project)

    def new_project(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
        self.project_path = None
        self.media_items = []
        self.timeline_project = TimelineProject()
        self.media_list.clear()
        self.media_info.setText("برای پیش‌نمایش، یک فایل را از فهرست رسانه‌ها انتخاب کنید.")
        self._refresh_timeline()
        self._set_playhead(0)
        self.statusBar().showMessage("پروژه جدید ایجاد شد")

    def import_media(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "انتخاب فایل‌های رسانه‌ای", "", MEDIA_FILTER)
        if not paths:
            return
        known = {item["path"] for item in self.media_items}
        added = 0
        for raw_path in paths:
            path = str(Path(raw_path).resolve())
            if path in known:
                continue
            record = {
                "path": path, "name": Path(path).name,
                "metadata": None, "probe_state": "pending",
            }
            self.media_items.append(record)
            self.media_list.addItem(QListWidgetItem(record["name"] + "  •  در حال بررسی"))
            task = MediaProbeTask(path)
            task.signals.finished.connect(self._media_probe_finished)
            self._probe_tasks.append(task)
            self._probe_pool.start(task)
            known.add(path)
            added += 1
        self.statusBar().showMessage(f"{added} فایل جدید وارد شد")

    def _media_probe_finished(self, path: str, metadata: object, error: str) -> None:
        self._probe_tasks = [task for task in self._probe_tasks if task.path != path]
        for index, item in enumerate(self.media_items):
            if item.get("path") != path:
                continue
            if metadata is not None:
                item["metadata"] = metadata
                item["probe_state"] = "ready"
                details = []
                seconds = metadata.get("duration_seconds")
                if seconds:
                    details.append(format_time(round(seconds * 1000)))
                if metadata.get("width") and metadata.get("height"):
                    details.append(f"{metadata['width']}×{metadata['height']}")
                if metadata.get("fps"):
                    details.append(f"{metadata['fps']:.2f} fps")
                if metadata.get("has_audio"):
                    details.append("صدا")
                label = item["name"] + ("  •  " + " | ".join(details) if details else "  •  مشخصات خوانده شد")
                self.media_list.item(index).setText(label)
            else:
                item["probe_state"] = "failed"
                item["probe_error"] = error
                self.media_list.item(index).setText(item["name"] + "  •  خطا در خواندن مشخصات")
                self.statusBar().showMessage(f"خواندن مشخصات {item['name']} ناموفق بود: {error}")
            break

    def add_selected_to_timeline(self, *_: Any) -> None:
        row = self.media_list.currentRow()
        if row < 0 or row >= len(self.media_items):
            return
        source = self.media_items[row]
        extension = Path(source["path"]).suffix.lower()
        track = "A1" if extension in AUDIO_EXTENSIONS else "V1"
        metadata = source.get("metadata")
        if source.get("probe_state") == "pending":
            self.statusBar().showMessage("در حال خواندن مدت واقعی فایل؛ کمی صبر کنید و دوباره افزودن را بزنید.")
            return
        duration_frames = duration_to_frames(
            (metadata or {}).get("duration_seconds"), self.timeline_project.fps
        )
        if duration_frames is None:
            if extension in {".png", ".jpg", ".jpeg"}:
                duration_frames = 5 * self.timeline_project.fps
            else:
                self.statusBar().showMessage("مدت واقعی این فایل خوانده نشد؛ برای جلوگیری از تایم‌لاین اشتباه، اضافه نشد.")
                return
        existing = self.timeline_project.clips_on_track(track)
        start = max((clip.end_frame for clip in existing), default=0)
        try:
            self.timeline_project.add_clip(
                path=source["path"], name=source["name"], track=track,
                start_frame=start, duration_frames=duration_frames,
                media_type="audio" if track.startswith("A") else "video",
            )
        except ValueError as exc:
            QMessageBox.warning(self, "افزودن کلیپ", str(exc))
            return
        self._refresh_timeline()
        seconds = duration_frames / self.timeline_project.fps
        self.statusBar().showMessage(
            f"{source['name']} اضافه شد | مدت: {format_time(round(seconds * 1000))}"
        )

    def _selected_clip_id(self) -> str | None:
        return self.timeline_widget.canvas.selected_clip_id

    def remove_selected_from_timeline(self) -> None:
        clip_id = self._selected_clip_id()
        if not clip_id:
            self.statusBar().showMessage("ابتدا یک کلیپ را در تایم‌لاین انتخاب کنید")
            return
        try:
            self.timeline_project.remove_clip(clip_id, ripple=False)
        except KeyError:
            return
        self.timeline_widget.canvas.selected_clip_id = None
        self._refresh_timeline()
        self.statusBar().showMessage("کلیپ از تایم‌لاین حذف شد؛ فایل اصلی دست‌نخورده باقی ماند.")

    def split_selected_clip(self) -> None:
        clip_id = self._selected_clip_id()
        if not clip_id:
            self.statusBar().showMessage("ابتدا کلیپ موردنظر را انتخاب کنید")
            return
        try:
            left, right = self.timeline_project.split_clip(
                clip_id, self.timeline_project.playhead_frame
            )
        except ValueError:
            self.statusBar().showMessage("مکان‌نما باید داخل محدوده کلیپ انتخاب‌شده باشد")
            return
        self.timeline_widget.canvas.selected_clip_id = right.clip_id
        self._refresh_timeline()
        self.statusBar().showMessage(f"کلیپ در فریم {self.timeline_project.playhead_frame} تقسیم شد")

    def _project_data(self) -> dict[str, Any]:
        return {
            "app": APP_NAME,
            "version": PROJECT_VERSION,
            "media": self.media_items,
            "timeline_project": self.timeline_project.to_dict(),
        }

    def save_project(self) -> None:
        if self.project_path is None:
            filename, _ = QFileDialog.getSaveFileName(
                self, "ذخیره پروژه", "Untitled.znproj", "ZENITH Project (*.znproj)"
            )
            if not filename:
                return
            self.project_path = Path(filename)
        temp_path = self.project_path.with_name(self.project_path.name + ".tmp")
        try:
            payload = json.dumps(self._project_data(), ensure_ascii=False, indent=2)
            temp_path.write_text(payload, encoding="utf-8")
            os.replace(temp_path, self.project_path)
            self.statusBar().showMessage(f"پروژه ذخیره شد: {self.project_path.name}")
        except (OSError, TypeError, ValueError) as exc:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            QMessageBox.critical(self, "خطای ذخیره", str(exc))

    def open_project(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "باز کردن پروژه", "", "ZENITH Project (*.znproj)"
        )
        if not filename:
            return
        try:
            data = json.loads(Path(filename).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("ساختار فایل پروژه معتبر نیست")
            media = data.get("media", [])
            if not isinstance(media, list):
                raise ValueError("فهرست رسانه‌های پروژه معتبر نیست")
            # Accept both the new schema and older projects containing
            # a simple 'timeline' list. Validate before replacing current state.
            timeline_data = data.get("timeline_project", data)
            loaded_timeline = TimelineProject.from_dict(timeline_data)
            loaded_media = []
            for item in media:
                if not isinstance(item, dict) or not item.get("path"):
                    continue
                path = str(item["path"])
                cached_metadata = item.get("metadata")
                loaded_media.append({
                    "path": path,
                    "name": str(item.get("name") or Path(path).name),
                    "metadata": cached_metadata if isinstance(cached_metadata, dict) else None,
                    "probe_state": "ready" if isinstance(cached_metadata, dict) else "pending",
                })
        except (OSError, ValueError, TypeError, KeyError) as exc:
            QMessageBox.critical(self, "خطای باز کردن", f"پروژه بارگذاری نشد؛ پروژه فعلی حفظ شد.\n{exc}")
            return

        self.player.stop()
        self.player.setSource(QUrl())
        self.timeline_project = loaded_timeline
        self.media_items = loaded_media
        self.project_path = Path(filename)
        self.media_list.clear()
        for item in self.media_items:
            metadata = item.get("metadata")
            if isinstance(metadata, dict):
                seconds = metadata.get("duration_seconds")
                details = [format_time(round(seconds * 1000))] if seconds else []
                if metadata.get("width") and metadata.get("height"):
                    details.append(f"{metadata['width']}×{metadata['height']}")
                label = item["name"] + ("  •  " + " | ".join(details) if details else "")
                self.media_list.addItem(label)
            else:
                self.media_list.addItem(item["name"] + "  •  در حال بررسی")
                task = MediaProbeTask(item["path"])
                task.signals.finished.connect(self._media_probe_finished)
                self._probe_tasks.append(task)
                self._probe_pool.start(task)
        self._refresh_timeline()
        self._set_playhead(self.timeline_project.playhead_frame)
        self.statusBar().showMessage(f"پروژه باز شد: {self.project_path.name}")


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    window = ZenithEditor()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
