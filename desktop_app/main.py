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
    QListWidgetItem, QSplitter, QFrame, QStatusBar, QSlider, QCheckBox, QComboBox, QProgressBar
)

from timeline_model import TimelineProject
from timeline_widget import TimelineWidget
from media_probe import probe_media, duration_to_frames
from proxy_manager import create_proxy
from waveform_manager import create_waveform, load_waveform
from audio_render import render_audio_mix
from audio_meter import estimate_track_peaks, peak_to_dbfs
from color_preview import create_color_preview
from video_render import render_timeline_mp4

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


class ProxyTaskSignals(QObject):
    finished = Signal(str, str, str)


class ProxyTask(QRunnable):
    """Generate one proxy in the background with a single task per source."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path
        self.signals = ProxyTaskSignals()

    def run(self) -> None:
        try:
            result = create_proxy(self.path)
            self.signals.finished.emit(self.path, str(result), "")
        except Exception as exc:
            self.signals.finished.emit(self.path, "", str(exc))


class ColorPreviewSignals(QObject):
    finished = Signal(str, str, str)


class ColorPreviewTask(QRunnable):
    """Render one graded clip preview away from the GUI thread."""

    def __init__(self, clip_id: str, path: str, source_in: float,
                 duration: float, grade: dict[str, float]) -> None:
        super().__init__()
        self.clip_id = clip_id
        self.path = path
        self.source_in = source_in
        self.duration = duration
        self.grade = dict(grade)
        self.signals = ColorPreviewSignals()

    def run(self) -> None:
        try:
            result = create_color_preview(
                self.path, self.source_in, self.duration, self.grade
            )
            self.signals.finished.emit(self.clip_id, str(result), "")
        except Exception as exc:
            self.signals.finished.emit(self.clip_id, "", str(exc))


class WaveformTaskSignals(QObject):
    finished = Signal(str, object, str)


class WaveformTask(QRunnable):
    """Build and load a compact waveform cache away from the GUI thread."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path
        self.signals = WaveformTaskSignals()

    def run(self) -> None:
        try:
            cache_path = create_waveform(self.path)
            values = load_waveform(cache_path)
            self.signals.finished.emit(self.path, values, "")
        except Exception as exc:
            self.signals.finished.emit(self.path, [], str(exc))


class AudioRenderSignals(QObject):
    finished = Signal(str, str)


class AudioRenderTask(QRunnable):
    """Render the current timeline audio mix away from the GUI thread."""

    def __init__(self, project_data: dict[str, Any], output_path: str) -> None:
        super().__init__()
        self.project_data = project_data
        self.output_path = output_path
        self.signals = AudioRenderSignals()

    def run(self) -> None:
        try:
            project = TimelineProject.from_dict(self.project_data)
            result = render_audio_mix(
                project.clips, project.fps, self.output_path,
                timeline_duration_frames=project.duration_frames,
                audio_track_settings=project.audio_track_settings,
                audio_ducking=project.audio_ducking,
            )
            self.signals.finished.emit(str(result), "")
        except Exception as exc:
            self.signals.finished.emit("", str(exc))


class VideoRenderSignals(QObject):
    finished = Signal(str, str)


class VideoRenderTask(QRunnable):
    """Render one immutable project snapshot to MP4 off the GUI thread."""

    def __init__(self, project_data: dict[str, Any], output_path: str) -> None:
        super().__init__()
        self.project_data = project_data
        self.output_path = output_path
        self.signals = VideoRenderSignals()

    def run(self) -> None:
        try:
            project = TimelineProject.from_dict(self.project_data)
            result = render_timeline_mp4(project, self.output_path)
            self.signals.finished.emit(str(result), "")
        except Exception as exc:
            self.signals.finished.emit("", str(exc))


class ZenithEditor(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project_path: Path | None = None
        self.media_items: list[dict[str, Any]] = []
        self._probe_pool = QThreadPool(self)
        self._probe_pool.setMaxThreadCount(2)
        self._probe_tasks: list[MediaProbeTask] = []
        self._proxy_pool = QThreadPool(self)
        self._proxy_pool.setMaxThreadCount(1)
        self._proxy_tasks: list[ProxyTask] = []
        self._waveform_pool = QThreadPool(self)
        self._waveform_pool.setMaxThreadCount(1)
        self._waveform_tasks: list[WaveformTask] = []
        self._audio_render_pool = QThreadPool(self)
        self._audio_render_pool.setMaxThreadCount(1)
        self._audio_render_task: AudioRenderTask | None = None
        self._video_render_pool = QThreadPool(self)
        self._video_render_pool.setMaxThreadCount(1)
        self._video_render_task: VideoRenderTask | None = None
        self._color_preview_pool = QThreadPool(self)
        self._color_preview_pool.setMaxThreadCount(1)
        self._color_preview_tasks: list[ColorPreviewTask] = []
        self._graded_preview_clip_id: str | None = None
        self.waveforms: dict[str, list[float]] = {}
        self._undo_stack: list[dict[str, Any]] = []
        self._redo_stack: list[dict[str, Any]] = []
        self._history_limit = 50
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
            ("بازگشت", "Ctrl+Z", self.undo),
            ("انجام دوباره", "Ctrl+Y", self.redo),
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
        self.proxy_button = QPushButton("ساخت Proxy سبک")
        self.proxy_button.setToolTip("ساخت نسخه کم‌حجم برای پیش‌نمایش؛ فایل اصلی تغییر نمی‌کند")
        self.proxy_button.clicked.connect(self.create_proxy_for_selected_media)
        media_layout.addWidget(self.media_list)
        media_layout.addWidget(import_btn)
        media_layout.addWidget(add_btn)
        media_layout.addWidget(self.proxy_button)

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

        audio_heading = QLabel("کنترل صدای کلیپ انتخاب‌شده")
        audio_heading.setObjectName("panel_title")
        inspector_layout.addWidget(audio_heading)

        self.volume_value_label = QLabel("حجم صدا: 100٪")
        inspector_layout.addWidget(self.volume_value_label)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 200)
        self.volume_slider.setValue(100)
        self.volume_slider.setToolTip("تنظیم حجم کلیپ از صفر تا ۲۰۰ درصد")
        self.volume_slider.sliderPressed.connect(self._push_undo)
        self.volume_slider.valueChanged.connect(self._audio_controls_changed)
        inspector_layout.addWidget(self.volume_slider)

        self.fade_in_label = QLabel("Fade In: 0.0 ثانیه")
        inspector_layout.addWidget(self.fade_in_label)
        self.fade_in_slider = QSlider(Qt.Horizontal)
        self.fade_in_slider.setRange(0, 300)
        self.fade_in_slider.setValue(0)
        self.fade_in_slider.setToolTip("مدت محوشدن تدریجی صدای ابتدا")
        self.fade_in_slider.sliderPressed.connect(self._push_undo)
        self.fade_in_slider.valueChanged.connect(self._audio_controls_changed)
        inspector_layout.addWidget(self.fade_in_slider)

        self.fade_out_label = QLabel("Fade Out: 0.0 ثانیه")
        inspector_layout.addWidget(self.fade_out_label)
        self.fade_out_slider = QSlider(Qt.Horizontal)
        self.fade_out_slider.setRange(0, 300)
        self.fade_out_slider.setValue(0)
        self.fade_out_slider.setToolTip("مدت محوشدن تدریجی صدای انتها")
        self.fade_out_slider.sliderPressed.connect(self._push_undo)
        self.fade_out_slider.valueChanged.connect(self._audio_controls_changed)
        inspector_layout.addWidget(self.fade_out_slider)

        visual_heading = QLabel("Fade تصویری کلیپ")
        visual_heading.setObjectName("panel_title")
        inspector_layout.addWidget(visual_heading)
        self.video_fade_in_label = QLabel("Video Fade In: —")
        inspector_layout.addWidget(self.video_fade_in_label)
        self.video_fade_in_slider = QSlider(Qt.Horizontal)
        self.video_fade_in_slider.setRange(0, 300)
        self.video_fade_in_slider.setToolTip("محوشدن تدریجی تصویر در ابتدای کلیپ؛ لایه زیرین نمایان می‌شود")
        self.video_fade_in_slider.sliderPressed.connect(self._push_undo)
        self.video_fade_in_slider.valueChanged.connect(self._video_fade_controls_changed)
        inspector_layout.addWidget(self.video_fade_in_slider)
        self.video_fade_out_label = QLabel("Video Fade Out: —")
        inspector_layout.addWidget(self.video_fade_out_label)
        self.video_fade_out_slider = QSlider(Qt.Horizontal)
        self.video_fade_out_slider.setRange(0, 300)
        self.video_fade_out_slider.setToolTip("محوشدن تدریجی تصویر در انتهای کلیپ؛ لایه زیرین نمایان می‌شود")
        self.video_fade_out_slider.sliderPressed.connect(self._push_undo)
        self.video_fade_out_slider.valueChanged.connect(self._video_fade_controls_changed)
        inspector_layout.addWidget(self.video_fade_out_slider)
        self.cross_dissolve_label = QLabel("Cross Dissolve In: —")
        inspector_layout.addWidget(self.cross_dissolve_label)
        self.cross_dissolve_slider = QSlider(Qt.Horizontal)
        self.cross_dissolve_slider.setRange(0, 150)
        self.cross_dissolve_slider.setToolTip("ترکیب تدریجی کلیپ انتخاب‌شده با کلیپ قبلی در همان ترک؛ فقط در برش چسبیده")
        self.cross_dissolve_slider.sliderPressed.connect(self._push_undo)
        self.cross_dissolve_slider.valueChanged.connect(self._cross_dissolve_changed)
        inspector_layout.addWidget(self.cross_dissolve_slider)

        color_heading = QLabel("اصلاح رنگ کلیپ")
        color_heading.setObjectName("panel_title")
        inspector_layout.addWidget(color_heading)
        self.color_controls: dict[str, tuple[QSlider, QLabel, float]] = {}
        color_specs = [
            ("exposure", "Exposure", -200, 200, 0.02, 0, "نوردهی برحسب EV"),
            ("contrast", "Contrast", 0, 200, 0.01, 100, "کنتراست"),
            ("saturation", "Saturation", 0, 300, 0.01, 100, "اشباع رنگ"),
            ("temperature", "Temperature", -100, 100, 0.01, 0, "سردی و گرمی رنگ"),
            ("tint", "Tint", -100, 100, 0.01, 0, "اصلاح ته‌رنگ سبز/ارغوانی"),
        ]
        for key, title, low, high, scale, initial, tooltip in color_specs:
            label = QLabel(f"{title}: {initial * scale:.2f}")
            inspector_layout.addWidget(label)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(low, high)
            slider.setValue(initial)
            slider.setToolTip(tooltip)
            slider.sliderPressed.connect(self._push_undo)
            slider.valueChanged.connect(self._color_controls_changed)
            inspector_layout.addWidget(slider)
            self.color_controls[key] = (slider, label, scale)

        self.color_preview_button = QPushButton("ساخت پیش‌نمایش رنگ کلیپ")
        self.color_preview_button.setToolTip(
            "رندر یک پیش‌نمایش کم‌حجم از کلیپ انتخاب‌شده با تنظیمات رنگ فعلی"
        )
        self.color_preview_button.setEnabled(False)
        self.color_preview_button.clicked.connect(self.create_color_preview_for_selected_clip)
        inspector_layout.addWidget(self.color_preview_button)

        mixer_heading = QLabel("میکسر ترک‌ها")
        mixer_heading.setObjectName("panel_title")
        inspector_layout.addWidget(mixer_heading)
        self.track_mixer_controls: dict[str, dict[str, Any]] = {}
        for track in self.timeline_project.audio_tracks:
            row = QHBoxLayout()
            track_label = QLabel(track)
            track_label.setFixedWidth(22)
            gain = QSlider(Qt.Horizontal)
            gain.setRange(0, 200)
            gain.setValue(100)
            gain.setToolTip(f"حجم کلی ترک {track} از صفر تا ۲۰۰ درصد")
            mute = QCheckBox("M")
            mute.setToolTip(f"بی‌صدا کردن ترک {track}")
            solo = QCheckBox("S")
            solo.setToolTip(f"شنیدن فقط ترک {track}")
            gain.sliderPressed.connect(self._push_undo)
            gain.valueChanged.connect(
                lambda value, name=track: self._audio_track_changed(name, volume=value / 100.0)
            )
            mute.pressed.connect(self._push_undo)
            mute.toggled.connect(
                lambda checked, name=track: self._audio_track_changed(name, muted=checked)
            )
            solo.pressed.connect(self._push_undo)
            solo.toggled.connect(
                lambda checked, name=track: self._audio_track_changed(name, solo=checked)
            )
            row.addWidget(track_label)
            row.addWidget(gain, 1)
            row.addWidget(mute)
            row.addWidget(solo)
            inspector_layout.addLayout(row)
            meter_row = QHBoxLayout()
            meter_label = QLabel("-∞ dBFS")
            meter_label.setFixedWidth(66)
            meter = QProgressBar()
            meter.setRange(0, 150)
            meter.setValue(0)
            meter.setTextVisible(False)
            meter.setFixedHeight(9)
            meter.setToolTip("برآورد پیک از شکل موج ذخیره‌شده؛ نشانگر زنده پخش نیست")
            meter_row.addWidget(meter, 1)
            meter_row.addWidget(meter_label)
            inspector_layout.addLayout(meter_row)
            self.track_mixer_controls[track] = {
                "gain": gain, "mute": mute, "solo": solo,
                "meter": meter, "meter_label": meter_label,
            }
        duck_heading = QLabel("Ducking هوشمند گویندگی")
        duck_heading.setObjectName("panel_title")
        inspector_layout.addWidget(duck_heading)
        self.ducking_enabled = QCheckBox("کاهش خودکار موسیقی هنگام صحبت")
        self.ducking_enabled.pressed.connect(self._push_undo)
        self.ducking_enabled.toggled.connect(self._audio_ducking_changed)
        inspector_layout.addWidget(self.ducking_enabled)
        duck_voice_row = QHBoxLayout()
        duck_voice_row.addWidget(QLabel("گویندگی"))
        self.duck_voice_track = QComboBox()
        self.duck_voice_track.addItems(self.timeline_project.audio_tracks)
        self.duck_voice_track.activated.connect(self._push_undo)
        self.duck_voice_track.currentTextChanged.connect(self._audio_ducking_changed)
        duck_voice_row.addWidget(self.duck_voice_track, 1)
        inspector_layout.addLayout(duck_voice_row)
        duck_music_row = QHBoxLayout()
        duck_music_row.addWidget(QLabel("موسیقی"))
        self.duck_music_track = QComboBox()
        self.duck_music_track.addItems(self.timeline_project.audio_tracks)
        self.duck_music_track.setCurrentText("A2")
        self.duck_music_track.activated.connect(self._push_undo)
        self.duck_music_track.currentTextChanged.connect(self._audio_ducking_changed)
        duck_music_row.addWidget(self.duck_music_track, 1)
        inspector_layout.addLayout(duck_music_row)
        self.duck_reduction_label = QLabel("کاهش موسیقی: 12 dB")
        inspector_layout.addWidget(self.duck_reduction_label)
        self.duck_reduction_slider = QSlider(Qt.Horizontal)
        self.duck_reduction_slider.setRange(0, 24)
        self.duck_reduction_slider.setValue(12)
        self.duck_reduction_slider.sliderPressed.connect(self._push_undo)
        self.duck_reduction_slider.valueChanged.connect(self._audio_ducking_changed)
        self.duck_reduction_slider.setToolTip("شدت کاهش خودکار حجم موسیقی هنگام فعال بودن گویندگی")
        inspector_layout.addWidget(self.duck_reduction_slider)
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
        self.video_render_button = QPushButton("خروجی نهایی MP4 (1080p)")
        self.video_render_button.setToolTip("رندر H.264 چندلایه V1 تا V4، عکس ثابت، اصلاح رنگ و میکس صدا")
        self.video_render_button.clicked.connect(self.export_video_mp4)
        self.audio_mix_button = QPushButton("خروجی میکس صدا (WAV)")
        self.audio_mix_button.setToolTip("ترکیب ترک‌های صوتی با Gain و Fade واقعی؛ فایل اصلی تغییر نمی‌کند")
        self.audio_mix_button.clicked.connect(self.export_audio_mix)
        self.undo_button = QPushButton("↶ بازگشت")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QPushButton("↷ انجام دوباره")
        self.redo_button.clicked.connect(self.redo)
        controls.addWidget(self.undo_button)
        controls.addWidget(self.redo_button)
        controls.addWidget(self.split_button)
        controls.addWidget(self.remove_button)
        controls.addWidget(self.audio_mix_button)
        controls.addWidget(self.video_render_button)
        timeline_layout.addLayout(controls)

        self.timeline_widget = TimelineWidget(self.timeline_project)
        self.timeline_widget.clipSelected.connect(self._select_timeline_clip)
        self.timeline_widget.playheadChanged.connect(self._set_playhead)
        self.timeline_widget.clipMoved.connect(self._clip_moved)
        self.timeline_widget.clipTrimmed.connect(self._clip_trimmed)
        self.timeline_widget.editStarted.connect(self._push_undo)
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
        source_path = Path(item["path"])
        if not source_path.exists():
            self.media_info.setText(f"فایل پیدا نشد؛ بعداً امکان اتصال مجدد اضافه می‌شود:\n{source_path}")
            return
        proxy_value = item.get("proxy_path")
        proxy_path = Path(proxy_value) if proxy_value else None
        preview_path = proxy_path if proxy_path and proxy_path.is_file() else source_path
        self._load_preview_source(preview_path, 0)
        mode = "پیش‌نمایش Proxy" if preview_path != source_path else "پیش‌نمایش فایل اصلی"
        self.media_info.setText(f"{item['name']}\n{mode}\n{source_path}")
        self.statusBar().showMessage(f"{mode}: {item['name']}")

    def _select_timeline_clip(self, clip_id: str) -> None:
        try:
            clip = self.timeline_project.get_clip(clip_id)
        except KeyError:
            return
        self.media_info.setText(f"کلیپ انتخاب‌شده: {clip.name}\nمسیر: {clip.track}")
        self._sync_audio_controls()
        self._sync_video_fade_controls()
        self._sync_cross_dissolve_controls()
        self._sync_color_controls()
        if Path(clip.path).exists():
            position_ms = int(clip.source_in * 1000 / self.timeline_project.fps)
            preview_path = Path(clip.path)
            for index, media in enumerate(self.media_items):
                if media.get("path") == clip.path:
                    proxy_value = media.get("proxy_path")
                    candidate = Path(proxy_value) if proxy_value else None
                    if candidate and candidate.is_file():
                        preview_path = candidate
                        self.media_info.setText(
                            f"کلیپ انتخاب‌شده: {clip.name}\nپیش‌نمایش Proxy\nمسیر اصلی: {clip.path}"
                        )
                    # Updating the bin selection must not reload the source and
                    # cancel the clip's source-in seek.
                    blocker = QSignalBlocker(self.media_list)
                    self.media_list.setCurrentRow(index)
                    del blocker
                    break
            self._load_preview_source(preview_path, position_ms)

    def _sync_audio_controls(self) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        clip = None
        if clip_id:
            try:
                clip = self.timeline_project.get_clip(clip_id)
            except KeyError:
                clip = None
        enabled = bool(clip and (clip.media_type == "audio" or (clip.media_type == "video" and clip.has_audio)))
        for control in (self.volume_slider, self.fade_in_slider, self.fade_out_slider):
            control.setEnabled(enabled)
        if not enabled:
            self.volume_value_label.setText("حجم صدا: —")
            self.fade_in_label.setText("Fade In: —")
            self.fade_out_label.setText("Fade Out: —")
            return
        blockers = [QSignalBlocker(control) for control in
                    (self.volume_slider, self.fade_in_slider, self.fade_out_slider)]
        self.volume_slider.setValue(round(clip.volume * 100))
        max_fade = min(clip.duration_frames, self.timeline_project.fps * 10)
        self.fade_in_slider.setRange(0, max_fade)
        self.fade_out_slider.setRange(0, max_fade)
        self.fade_in_slider.setValue(min(clip.fade_in_frames, max_fade))
        self.fade_out_slider.setValue(min(clip.fade_out_frames, max_fade))
        del blockers
        self.volume_value_label.setText(f"حجم صدا: {round(clip.volume * 100)}٪")
        fps = max(1, self.timeline_project.fps)
        self.fade_in_label.setText(f"Fade In: {clip.fade_in_frames / fps:.1f} ثانیه")
        self.fade_out_label.setText(f"Fade Out: {clip.fade_out_frames / fps:.1f} ثانیه")


    def _sync_video_fade_controls(self) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        clip = None
        if clip_id:
            try:
                clip = self.timeline_project.get_clip(clip_id)
            except KeyError:
                pass
        enabled = bool(clip and clip.media_type == "video" and clip.track.startswith("V"))
        for control in (self.video_fade_in_slider, self.video_fade_out_slider):
            control.setEnabled(enabled)
        if not enabled:
            self.video_fade_in_label.setText("Video Fade In: —")
            self.video_fade_out_label.setText("Video Fade Out: —")
            return
        blockers = [QSignalBlocker(self.video_fade_in_slider), QSignalBlocker(self.video_fade_out_slider)]
        max_fade = min(clip.duration_frames, self.timeline_project.fps * 10)
        self.video_fade_in_slider.setRange(0, max_fade)
        self.video_fade_out_slider.setRange(0, max_fade)
        self.video_fade_in_slider.setValue(min(clip.video_fade_in_frames, max_fade))
        self.video_fade_out_slider.setValue(min(clip.video_fade_out_frames, max_fade))
        del blockers
        fps = max(1, self.timeline_project.fps)
        self.video_fade_in_label.setText(f"Video Fade In: {clip.video_fade_in_frames / fps:.1f} ثانیه")
        self.video_fade_out_label.setText(f"Video Fade Out: {clip.video_fade_out_frames / fps:.1f} ثانیه")

    def _video_fade_controls_changed(self, *_: Any) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        try:
            clip = self.timeline_project.get_clip(clip_id)
            self.timeline_project.set_clip_video_fade(
                clip_id,
                fade_in_frames=self.video_fade_in_slider.value(),
                fade_out_frames=self.video_fade_out_slider.value(),
            )
        except (KeyError, ValueError) as exc:
            self.statusBar().showMessage(f"تنظیم Fade تصویری اعمال نشد: {exc}")
            self._sync_video_fade_controls()
            return
        fps = max(1, self.timeline_project.fps)
        self.video_fade_in_label.setText(f"Video Fade In: {clip.video_fade_in_frames / fps:.1f} ثانیه")
        self.video_fade_out_label.setText(f"Video Fade Out: {clip.video_fade_out_frames / fps:.1f} ثانیه")
        self.timeline_widget.refresh()
        self.statusBar().showMessage("Fade تصویری ذخیره شد و در خروجی MP4 اعمال می‌شود.")


    def _sync_cross_dissolve_controls(self) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        clip = None
        if clip_id:
            try:
                clip = self.timeline_project.get_clip(clip_id)
            except KeyError:
                pass
        enabled = bool(clip and clip.media_type == "video" and clip.track.startswith("V"))
        self.cross_dissolve_slider.setEnabled(enabled)
        if not enabled:
            self.cross_dissolve_label.setText("Cross Dissolve In: —")
            return
        blockers = QSignalBlocker(self.cross_dissolve_slider)
        previous = next((item for item in reversed(self.timeline_project.clips_on_track(clip.track))
                         if item.start_frame < clip.start_frame), None)
        adjacent = bool(previous and previous.end_frame == clip.start_frame)
        max_frames = min(clip.duration_frames, previous.duration_frames if adjacent else 0,
                         self.timeline_project.fps * 5)
        self.cross_dissolve_slider.setRange(0, max(max_frames, clip.transition_in_frames))
        self.cross_dissolve_slider.setValue(clip.transition_in_frames)
        self.cross_dissolve_slider.setEnabled(adjacent or clip.transition_in_frames > 0)
        del blockers
        fps = max(1, self.timeline_project.fps)
        if not adjacent and clip.transition_in_frames == 0:
            self.cross_dissolve_label.setText("Cross Dissolve: نیازمند کلیپ قبلی چسبیده")
        else:
            self.cross_dissolve_label.setText(f"Cross Dissolve In: {clip.transition_in_frames / fps:.1f} ثانیه")

    def _cross_dissolve_changed(self, *_: Any) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        try:
            clip = self.timeline_project.get_clip(clip_id)
            self.timeline_project.set_clip_transition(
                clip_id, dissolve_in_frames=self.cross_dissolve_slider.value()
            )
        except (KeyError, ValueError) as exc:
            self.statusBar().showMessage(f"تنظیم Cross Dissolve اعمال نشد: {exc}")
            self._sync_cross_dissolve_controls()
            return
        fps = max(1, self.timeline_project.fps)
        self.cross_dissolve_label.setText(f"Cross Dissolve In: {clip.transition_in_frames / fps:.1f} ثانیه")
        self.timeline_widget.refresh()
        self.statusBar().showMessage("Cross Dissolve ذخیره شد؛ پیش‌نمایش نهایی در رندر MP4 اعمال می‌شود.")

    def _sync_color_controls(self) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        clip = None
        if clip_id:
            try:
                clip = self.timeline_project.get_clip(clip_id)
            except KeyError:
                pass
        enabled = bool(clip and clip.media_type == "video")
        self.color_preview_button.setEnabled(enabled)
        for slider, label, scale in self.color_controls.values():
            slider.setEnabled(enabled)
            if not enabled:
                label.setText(label.text().split(":")[0] + ": —")
        if not enabled:
            return
        blockers = [QSignalBlocker(slider) for slider, _, _ in self.color_controls.values()]
        for key, (slider, label, scale) in self.color_controls.items():
            value = float(clip.color_grade.get(key, 0.0 if key in {"exposure", "temperature", "tint"} else 1.0))
            slider.setValue(round(value / scale))
            label.setText(f"{key.title()}: {value:.2f}")
        del blockers

    def _color_controls_changed(self, *_: Any) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        try:
            clip = self.timeline_project.get_clip(clip_id)
            if clip.media_type != "video":
                return
            values = {
                key: slider.value() * scale
                for key, (slider, _, scale) in self.color_controls.items()
            }
            self.timeline_project.set_clip_color(clip_id, **values)
        except (KeyError, ValueError) as exc:
            self.statusBar().showMessage(f"اصلاح رنگ اعمال نشد: {exc}")
            self._sync_color_controls()
            return
        for key, (_, label, _) in self.color_controls.items():
            label.setText(f"{key.title()}: {clip.color_grade[key]:.2f}")
        self.timeline_widget.refresh()
        self.color_preview_button.setText("به‌روزرسانی پیش‌نمایش رنگ")
        self.statusBar().showMessage("تنظیمات رنگ ذخیره شد؛ برای مشاهده تصویر اصلاح‌شده، پیش‌نمایش رنگ را به‌روزرسانی کن.")

    def create_color_preview_for_selected_clip(self) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            self.statusBar().showMessage("ابتدا یک کلیپ ویدیویی را انتخاب کن")
            return
        try:
            clip = self.timeline_project.get_clip(clip_id)
        except KeyError:
            return
        if clip.media_type != "video":
            self.statusBar().showMessage("پیش‌نمایش اصلاح رنگ فقط برای کلیپ ویدیویی است")
            return
        if not Path(clip.path).is_file():
            self.statusBar().showMessage("فایل اصلی کلیپ پیدا نشد")
            return
        if any(task.clip_id == clip_id for task in self._color_preview_tasks):
            self.statusBar().showMessage("ساخت پیش‌نمایش رنگ این کلیپ در حال انجام است")
            return
        task = ColorPreviewTask(
            clip.clip_id, clip.path,
            clip.source_in / max(1, self.timeline_project.fps),
            clip.duration_frames / max(1, self.timeline_project.fps),
            dict(clip.color_grade),
        )
        task.signals.finished.connect(self._color_preview_finished)
        self._color_preview_tasks.append(task)
        self.color_preview_button.setEnabled(False)
        self.statusBar().showMessage(
            "در حال ساخت پیش‌نمایش رنگ ۹۶۰ پیکسلی در پس‌زمینه؛ فایل اصلی تغییر نمی‌کند..."
        )
        self._color_preview_pool.start(task)

    def _color_preview_finished(self, clip_id: str, preview_path: str, error: str) -> None:
        self._color_preview_tasks = [
            task for task in self._color_preview_tasks if task.clip_id != clip_id
        ]
        selected_id = self.timeline_widget.canvas.selected_clip_id
        if preview_path and Path(preview_path).is_file():
            if selected_id == clip_id:
                self._graded_preview_clip_id = clip_id
                self._load_preview_source(Path(preview_path), 0)
                self.statusBar().showMessage(
                    "پیش‌نمایش اصلاح رنگ آماده شد؛ نسخه اصلی دست‌نخورده باقی ماند."
                )
            else:
                self.statusBar().showMessage("پیش‌نمایش رنگ در Cache ذخیره شد.")
        else:
            self.statusBar().showMessage(f"ساخت پیش‌نمایش رنگ ناموفق بود: {error}")
        if selected_id == clip_id:
            self.color_preview_button.setEnabled(True)

    def _audio_controls_changed(self, *_: Any) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        try:
            clip = self.timeline_project.get_clip(clip_id)
            if not (clip.media_type == "audio" or (clip.media_type == "video" and clip.has_audio)):
                return
            self.timeline_project.set_clip_audio(
                clip_id,
                volume=self.volume_slider.value() / 100.0,
                fade_in_frames=self.fade_in_slider.value(),
                fade_out_frames=self.fade_out_slider.value(),
            )
        except (KeyError, ValueError) as exc:
            self.statusBar().showMessage(f"تنظیم صدای کلیپ اعمال نشد: {exc}")
            self._sync_audio_controls()
            return
        self.volume_value_label.setText(f"حجم صدا: {round(clip.volume * 100)}٪")
        fps = max(1, self.timeline_project.fps)
        self.fade_in_label.setText(f"Fade In: {clip.fade_in_frames / fps:.1f} ثانیه")
        self.fade_out_label.setText(f"Fade Out: {clip.fade_out_frames / fps:.1f} ثانیه")
        self.timeline_widget.refresh()

    def create_proxy_for_selected_media(self) -> None:
        row = self.media_list.currentRow()
        if row < 0 or row >= len(self.media_items):
            self.statusBar().showMessage("ابتدا یک فایل ویدیویی را انتخاب کنید")
            return
        item = self.media_items[row]
        source = Path(item["path"])
        if item.get("probe_state") == "pending":
            self.statusBar().showMessage("ابتدا باید بررسی مشخصات رسانه تمام شود")
            return
        metadata = item.get("metadata") or {}
        if source.suffix.lower() in {".png", ".jpg", ".jpeg"} or not metadata.get("has_video"):
            self.statusBar().showMessage("برای این فایل ویدیویی، ساخت Proxy لازم یا پشتیبانی‌شده نیست")
            return
        existing = item.get("proxy_path")
        if existing and Path(existing).is_file():
            self.statusBar().showMessage("Proxy این فایل از قبل آماده است")
            return
        if any(task.path == str(source) for task in self._proxy_tasks):
            self.statusBar().showMessage("ساخت Proxy این فایل در حال انجام است")
            return
        task = ProxyTask(str(source))
        task.signals.finished.connect(self._proxy_finished)
        self._proxy_tasks.append(task)
        self.proxy_button.setEnabled(False)
        self.statusBar().showMessage("در حال ساخت Proxy سبک در پس‌زمینه؛ فایل اصلی دست‌نخورده می‌ماند...")
        self._proxy_pool.start(task)

    def _proxy_finished(self, path: str, proxy_path: str, error: str) -> None:
        self._proxy_tasks = [task for task in self._proxy_tasks if task.path != path]
        for index, item in enumerate(self.media_items):
            if item.get("path") != path:
                continue
            if proxy_path and Path(proxy_path).is_file():
                item["proxy_path"] = proxy_path
                self.media_list.item(index).setText(
                    self.media_list.item(index).text().split("  •  Proxy آماده")[0] + "  •  Proxy آماده"
                )
                self.statusBar().showMessage(f"Proxy آماده شد: {item['name']} | فایل اصلی حفظ شد")
                if self.media_list.currentRow() == index:
                    self._preview_media_row(index)
            else:
                self.statusBar().showMessage(f"ساخت Proxy ناموفق بود: {error}")
            break
        self.proxy_button.setEnabled(True)

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

    def _push_undo(self) -> None:
        self._undo_stack.append(self.timeline_project.to_dict())
        if len(self._undo_stack) > self._history_limit:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_history_buttons()

    def _update_history_buttons(self) -> None:
        if hasattr(self, "undo_button"):
            self.undo_button.setEnabled(bool(self._undo_stack))
            self.redo_button.setEnabled(bool(self._redo_stack))

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(self.timeline_project.to_dict())
        self.timeline_project = TimelineProject.from_dict(self._undo_stack.pop())
        self._refresh_timeline()
        self._update_history_buttons()
        self.statusBar().showMessage("آخرین تغییر برگشت داده شد")

    def redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(self.timeline_project.to_dict())
        self.timeline_project = TimelineProject.from_dict(self._redo_stack.pop())
        self._refresh_timeline()
        self._update_history_buttons()
        self.statusBar().showMessage("تغییر دوباره اعمال شد")

    def _clip_trimmed(self, clip_id: str, start_frame: int, end_frame: int) -> None:
        try:
            self.timeline_project.trim_clip(clip_id, new_start_frame=start_frame, new_end_frame=end_frame)
        except (KeyError, ValueError) as exc:
            self.statusBar().showMessage(f"کوتاه‌کردن کلیپ انجام نشد: {exc}")
        self._refresh_timeline()
        self.statusBar().showMessage("لبه کلیپ تنظیم شد؛ فایل اصلی تغییری نکرد")

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
        self.timeline_widget.set_waveforms(self.waveforms)
        self._sync_audio_controls()
        self._sync_audio_track_controls()
        self._sync_audio_peak_meters()
        self._sync_audio_ducking_controls()

    def _start_waveform(self, path: str) -> None:
        if path in self.waveforms or any(task.path == path for task in self._waveform_tasks):
            return
        task = WaveformTask(path)
        task.signals.finished.connect(self._waveform_finished)
        self._waveform_tasks.append(task)
        self._waveform_pool.start(task)

    def _waveform_finished(self, path: str, values: object, error: str) -> None:
        self._waveform_tasks = [task for task in self._waveform_tasks if task.path != path]
        if values:
            self.waveforms[path] = list(values)
            self.timeline_widget.set_waveforms(self.waveforms)
            self._sync_audio_peak_meters()
            self.statusBar().showMessage(
                f"شکل موج صوتی آماده شد: {Path(path).name}"
            )
        elif error:
            self.statusBar().showMessage(
                f"ساخت شکل موج برای {Path(path).name} ناموفق بود: {error}"
            )

    def new_project(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
        self.project_path = None
        self.media_items = []
        self.waveforms = {}
        self.timeline_widget.set_waveforms(self.waveforms)
        self.timeline_project = TimelineProject()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._update_history_buttons()
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
                "proxy_path": None,
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
                if metadata.get("has_audio"):
                    self._start_waveform(path)
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
        self._push_undo()
        try:
            self.timeline_project.add_clip(
                path=source["path"], name=source["name"], track=track,
                start_frame=start, duration_frames=duration_frames,
                media_type="audio" if track.startswith("A") else "video",
                has_audio=bool((metadata or {}).get("has_audio")) if track.startswith("V") else True,
                audio_track="A1" if track.startswith("V") else track,
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
        self._push_undo()
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
        self._push_undo()
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

    def _sync_audio_track_controls(self) -> None:
        for track, controls in self.track_mixer_controls.items():
            settings = self.timeline_project.audio_track_settings.get(
                track, {"volume": 1.0, "muted": False, "solo": False}
            )
            blockers = [
                QSignalBlocker(controls["gain"]),
                QSignalBlocker(controls["mute"]),
                QSignalBlocker(controls["solo"]),
            ]
            controls["gain"].setValue(round(float(settings.get("volume", 1.0)) * 100))
            controls["mute"].setChecked(bool(settings.get("muted", False)))
            controls["solo"].setChecked(bool(settings.get("solo", False)))
            del blockers

    def _sync_audio_peak_meters(self) -> None:
        """Show cached waveform peak estimates, not live playback levels."""
        try:
            peaks = estimate_track_peaks(
                self.timeline_project.clips,
                self.waveforms,
                self.timeline_project.fps,
                self.timeline_project.audio_track_settings,
                self.timeline_project.audio_tracks,
            )
        except (TypeError, ValueError):
            return
        for track, controls in self.track_mixer_controls.items():
            peak = peaks.get(track, 0.0)
            controls["meter"].setValue(round(peak * 100))
            controls["meter_label"].setText(peak_to_dbfs(peak))

    def _sync_audio_ducking_controls(self) -> None:
        settings = self.timeline_project.audio_ducking
        blockers = [
            QSignalBlocker(self.ducking_enabled),
            QSignalBlocker(self.duck_voice_track),
            QSignalBlocker(self.duck_music_track),
            QSignalBlocker(self.duck_reduction_slider),
        ]
        self.ducking_enabled.setChecked(bool(settings.get("enabled", False)))
        self.duck_voice_track.setCurrentText(settings.get("voice_track", "A1"))
        self.duck_music_track.setCurrentText(settings.get("music_track", "A2"))
        reduction = round(float(settings.get("reduction_db", 12.0)))
        self.duck_reduction_slider.setValue(reduction)
        self.duck_reduction_label.setText(f"کاهش موسیقی: {reduction} dB")
        del blockers

    def _audio_ducking_changed(self, *_args: Any) -> None:
        try:
            self.timeline_project.set_audio_ducking(
                enabled=self.ducking_enabled.isChecked(),
                voice_track=self.duck_voice_track.currentText(),
                music_track=self.duck_music_track.currentText(),
                reduction_db=float(self.duck_reduction_slider.value()),
            )
        except (KeyError, ValueError) as exc:
            self.statusBar().showMessage(f"تنظیم Ducking اعمال نشد: {exc}")
            self._sync_audio_ducking_controls()
            return
        self.duck_reduction_label.setText(
            f"کاهش موسیقی: {self.duck_reduction_slider.value()} dB"
        )
        self.statusBar().showMessage("تنظیمات Ducking ذخیره شد؛ در خروجی میکس اعمال می‌شود")

    def _audio_track_changed(self, track: str, **changes: Any) -> None:
        try:
            self.timeline_project.set_audio_track(track, **changes)
        except (KeyError, ValueError) as exc:
            self.statusBar().showMessage(f"تنظیم میکسر اعمال نشد: {exc}")
            self._sync_audio_track_controls()
            return
        self.statusBar().showMessage(f"تنظیمات میکسر {track} تغییر کرد")
        self._sync_audio_peak_meters()
        self.timeline_widget.refresh()

    def export_audio_mix(self) -> None:
        if self._audio_render_task is not None:
            self.statusBar().showMessage("خروجی میکس صوتی در حال انجام است")
            return
        audio_clips = [
            clip for clip in self.timeline_project.clips
            if clip.media_type == "audio" or (clip.media_type == "video" and clip.has_audio)
        ]
        if not audio_clips:
            QMessageBox.information(self, "خروجی صدا", "ابتدا یک کلیپ صوتی یا ویدیوی دارای صدا به تایم‌لاین اضافه کنید.")
            return
        filename, _ = QFileDialog.getSaveFileName(self, "ذخیره میکس صوتی", "ZENITH_Audio_Mix.wav", "WAV Audio (*.wav)")
        if not filename:
            return
        output = Path(filename)
        if output.suffix.lower() != ".wav":
            output = output.with_suffix(".wav")
        task = AudioRenderTask(self.timeline_project.to_dict(), str(output))
        task.signals.finished.connect(self._audio_mix_finished)
        self._audio_render_task = task
        self.audio_mix_button.setEnabled(False)
        self.statusBar().showMessage("در حال میکس ترک‌های صوتی در پس‌زمینه؛ رابط برنامه آزاد می‌ماند...")
        self._audio_render_pool.start(task)

    def export_video_mp4(self) -> None:
        if self._video_render_task is not None:
            self.statusBar().showMessage("خروجی ویدیویی در حال انجام است")
            return
        if not any(clip.track.startswith("V") and clip.media_type == "video"
                   for clip in self.timeline_project.clips):
            QMessageBox.information(self, "خروجی MP4", "ابتدا یک کلیپ تصویری روی یکی از ترک‌های V1 تا V4 قرار دهید.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "ذخیره ویدیوی نهایی", "ZENITH_Final_1080p.mp4",
            "MP4 Video (*.mp4)"
        )
        if not filename:
            return
        output = Path(filename)
        if output.suffix.lower() != ".mp4":
            output = output.with_suffix(".mp4")
        task = VideoRenderTask(self.timeline_project.to_dict(), str(output))
        task.signals.finished.connect(self._video_render_finished)
        self._video_render_task = task
        self.video_render_button.setEnabled(False)
        self.statusBar().showMessage(
            "رندر MP4 در پس‌زمینه آغاز شد؛ رابط آزاد می‌ماند. لطفاً تا پایان رندر برنامه را نبندید."
        )
        self._video_render_pool.start(task)

    def _video_render_finished(self, output_path: str, error: str) -> None:
        self._video_render_task = None
        self.video_render_button.setEnabled(True)
        if error:
            QMessageBox.critical(self, "خطای خروجی MP4", error)
            self.statusBar().showMessage("ساخت خروجی MP4 ناموفق بود")
            return
        self.statusBar().showMessage(f"ویدیوی نهایی آماده شد: {Path(output_path).name}")
        QMessageBox.information(
            self, "خروجی MP4 آماده شد",
            f"ویدیوی H.264 با موفقیت ساخته شد.\n\n{output_path}"
        )

    def _audio_mix_finished(self, output_path: str, error: str) -> None:
        self._audio_render_task = None
        self.audio_mix_button.setEnabled(True)
        if error:
            QMessageBox.critical(self, "خطای خروجی صدا", error)
            self.statusBar().showMessage("ساخت میکس صوتی ناموفق بود")
            return
        self.statusBar().showMessage(f"میکس صوتی آماده شد: {Path(output_path).name}")
        QMessageBox.information(self, "خروجی صدا آماده شد", f"میکس صوتی WAV با موفقیت ساخته شد.\n\n{output_path}")

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
                    "proxy_path": str(item.get("proxy_path")) if item.get("proxy_path") and Path(str(item.get("proxy_path"))).is_file() else None,
                })
        except (OSError, ValueError, TypeError, KeyError) as exc:
            QMessageBox.critical(self, "خطای باز کردن", f"پروژه بارگذاری نشد؛ پروژه فعلی حفظ شد.\n{exc}")
            return

        self.player.stop()
        self.player.setSource(QUrl())
        self.timeline_project = loaded_timeline
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._update_history_buttons()
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
        for item in self.media_items:
            metadata = item.get("metadata") or {}
            if metadata.get("has_audio") and Path(item["path"]).is_file():
                self._start_waveform(item["path"])
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
