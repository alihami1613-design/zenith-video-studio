from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QFont
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QMessageBox,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QSplitter, QFrame, QStatusBar, QSlider
)

APP_NAME = "ZENITH Desktop"
PROJECT_VERSION = 1
MEDIA_FILTER = "Media files (*.mp4 *.mov *.mkv *.avi *.webm *.mp3 *.wav *.m4a *.aac *.png *.jpg *.jpeg);;All files (*.*)"


def format_time(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class ZenithEditor(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project_path: Path | None = None
        self.media_items: list[dict[str, Any]] = []
        self.timeline_items: list[dict[str, Any]] = []
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.8)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.positionChanged.connect(self._position_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.setWindowTitle(f"{APP_NAME} | Video Editor")
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)
        self._build_menu()
        self._build_ui()
        self._apply_theme()
        self.statusBar().showMessage("آماده | یک پروژه جدید بسازید یا فایل‌های رسانه‌ای را وارد کنید")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("فایل")
        new_action = QAction("پروژه جدید", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self.new_project)
        open_action = QAction("باز کردن پروژه", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_project)
        save_action = QAction("ذخیره پروژه", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_project)
        import_action = QAction("وارد کردن رسانه", self)
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(self.import_media)
        file_menu.addActions([new_action, open_action, save_action, import_action])

    def _build_ui(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        header = QHBoxLayout()
        brand = QLabel("ZENITH <span style='color:#D6AE55'>BEYOND</span>")
        brand.setObjectName("brand")
        subtitle = QLabel("DESKTOP VIDEO STUDIO  •  1080P WORKFLOW")
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

        preview_panel = self._panel("پیش‌نمایش رسانه")
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

        inspector_panel = self._panel("اطلاعات رسانه")
        inspector_layout = inspector_panel.layout()
        self.media_info = QLabel("برای پیش‌نمایش، یک فایل ویدیویی یا صوتی را از فهرست رسانه‌ها انتخاب کنید.")
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
        controls.addWidget(QLabel("V1  ویدیو"))
        controls.addWidget(QLabel("A1  صدا"))
        controls.addStretch(1)
        remove_btn = QPushButton("حذف از تایم‌لاین")
        remove_btn.clicked.connect(self.remove_selected_from_timeline)
        controls.addWidget(remove_btn)
        timeline_layout.addLayout(controls)
        self.timeline_list = QListWidget()
        self.timeline_list.setObjectName("timeline")
        timeline_layout.addWidget(self.timeline_list)
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
            QPushButton { background:#28292D; color:#F2F2F2; border:1px solid #49433A; border-radius:5px; padding:8px 12px; }
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
            self.media_info.setText(f"فایل پیدا نشد:\n{path}")
            return
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.media_info.setText(f"{item['name']}\n{path}")
        self.statusBar().showMessage(f"آماده پخش: {item['name']}")

    def _toggle_playback(self) -> None:
        if self.player.source().isEmpty():
            self.statusBar().showMessage("ابتدا یک فایل رسانه‌ای را انتخاب کنید")
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _duration_changed(self, duration: int) -> None:
        self.seek_slider.setRange(0, duration)
        self._update_time_label(self.player.position(), duration)

    def _position_changed(self, position: int) -> None:
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(position)
        self._update_time_label(position, self.player.duration())

    def _update_time_label(self, position: int, duration: int) -> None:
        self.time_label.setText(f"{format_time(position)} / {format_time(duration)}")

    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play_button.setText("Ⅱ مکث" if state == QMediaPlayer.PlayingState else "▶ پخش")

    def new_project(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
        self.project_path = None
        self.media_items.clear()
        self.timeline_items.clear()
        self.media_list.clear()
        self.timeline_list.clear()
        self.media_info.setText("برای پیش‌نمایش، یک فایل ویدیویی یا صوتی را از فهرست رسانه‌ها انتخاب کنید.")
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
            record = {"path": path, "name": Path(path).name}
            self.media_items.append(record)
            self.media_list.addItem(QListWidgetItem(record["name"]))
            known.add(path)
            added += 1
        self.statusBar().showMessage(f"{added} فایل جدید وارد شد")

    def add_selected_to_timeline(self, *_: Any) -> None:
        row = self.media_list.currentRow()
        if row < 0 or row >= len(self.media_items):
            return
        source = self.media_items[row]
        clip = {"path": source["path"], "name": source["name"], "track": "V1"}
        self.timeline_items.append(clip)
        self.timeline_list.addItem(QListWidgetItem(f"V1  |  {clip['name']}"))
        self.statusBar().showMessage(f"به تایم‌لاین اضافه شد: {clip['name']}")

    def remove_selected_from_timeline(self) -> None:
        row = self.timeline_list.currentRow()
        if row < 0:
            return
        self.timeline_list.takeItem(row)
        self.timeline_items.pop(row)

    def _project_data(self) -> dict[str, Any]:
        return {
            "app": APP_NAME,
            "version": PROJECT_VERSION,
            "media": self.media_items,
            "timeline": self.timeline_items,
        }

    def save_project(self) -> None:
        if self.project_path is None:
            filename, _ = QFileDialog.getSaveFileName(self, "ذخیره پروژه", "Untitled.znproj", "ZENITH Project (*.znproj)")
            if not filename:
                return
            self.project_path = Path(filename)
        try:
            self.project_path.write_text(json.dumps(self._project_data(), ensure_ascii=False, indent=2), encoding="utf-8")
            self.statusBar().showMessage(f"پروژه ذخیره شد: {self.project_path.name}")
        except OSError as exc:
            QMessageBox.critical(self, "خطای ذخیره", str(exc))

    def open_project(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "باز کردن پروژه", "", "ZENITH Project (*.znproj)")
        if not filename:
            return
        try:
            data = json.loads(Path(filename).read_text(encoding="utf-8"))
            self.media_items = data.get("media", [])
            self.timeline_items = data.get("timeline", [])
            self.project_path = Path(filename)
            self.media_list.clear()
            self.timeline_list.clear()
            for item in self.media_items:
                self.media_list.addItem(item.get("name", Path(item["path"]).name))
            for clip in self.timeline_items:
                self.timeline_list.addItem(f"{clip.get('track', 'V1')}  |  {clip.get('name', Path(clip['path']).name)}")
            self.statusBar().showMessage(f"پروژه باز شد: {self.project_path.name}")
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "خطای باز کردن", str(exc))


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    window = ZenithEditor()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
