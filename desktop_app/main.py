from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl, QSignalBlocker, QObject, Signal, QRunnable, QThreadPool, QEvent, QTimer
from PySide6.QtGui import QAction, QFont
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QMessageBox,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QSplitter, QFrame, QStatusBar, QSlider, QCheckBox, QComboBox,
    QProgressBar, QDoubleSpinBox, QLineEdit, QSpinBox, QPlainTextEdit, QGroupBox,
)

from timeline_model import TimelineProject, mask_values_at, mask_points_at, transform_eased_progress
from timeline_widget import TimelineWidget
from media_probe import probe_media, duration_to_frames
from proxy_manager import create_proxy
from waveform_manager import create_waveform, load_waveform
from audio_render import render_audio_mix
from audio_meter import estimate_track_peaks, peak_to_dbfs
from color_preview import create_color_preview
from color_scopes import extract_rgb_frame, extract_rgb_histogram
from color_scope_widget import RGBHistogramWidget
from advanced_scopes import calculate_luma_waveform, calculate_rgb_parade, calculate_vectorscope
from advanced_scope_widget import ScopeMatrixWidget, VectorScopeWidget
from color_wheel_widget import ColorWheelWidget
from color_wheel_math import rgb_to_wheel, wheel_to_rgb
from bezier_curve_widget import BezierCurveWidget
from speed_ramp_preview import create_speed_ramp_preview
from video_render import render_timeline_mp4
from polygon_mask_overlay import PolygonMaskOverlay
from project_recovery import default_recovery_path, write_recovery, read_recovery, clear_recovery
from ai_editor.project_context import build_project_context, media_inventory_fingerprint
from ai_editor.media_analysis import analyze_project_media
from ai_editor.narrative import story_blueprint_from_dict
from ai_editor.shot_selection import select_shots_for_story
from ai_editor.music_sync_workflow import build_music_aware_edit_draft
from ai_editor.executor import preview_edit_plan, apply_edit_plan

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


class RGBHistogramSignals(QObject):
    finished = Signal(str, object, str)


class RGBHistogramTask(QRunnable):
    """Sample one tiny RGB frame off the GUI thread for the Color scope."""

    def __init__(self, clip_id: str, path: str, timestamp: float, grade: dict[str, float], scope_kind: str = "histogram") -> None:
        super().__init__()
        self.clip_id = clip_id
        self.path = path
        self.timestamp = timestamp
        self.grade = dict(grade)
        self.scope_kind = scope_kind
        self.signals = RGBHistogramSignals()

    def run(self) -> None:
        try:
            if self.scope_kind == "histogram":
                result = extract_rgb_histogram(self.path, self.timestamp, self.grade)
            else:
                frame = extract_rgb_frame(self.path, self.timestamp, self.grade)
                result = (calculate_luma_waveform(frame) if self.scope_kind == "waveform" else calculate_rgb_parade(frame) if self.scope_kind == "parade" else calculate_vectorscope(frame))
            self.signals.finished.emit(self.clip_id, result, "")
        except Exception as exc:
            self.signals.finished.emit(self.clip_id, None, str(exc))


class SpeedRampPreviewSignals(QObject):
    finished = Signal(str, str, str)


class SpeedRampPreviewTask(QRunnable):
    """Build a short 480px/15fps Speed Ramp preview off the GUI thread."""

    def __init__(self, clip_id: str, path: str, source_in_frame: int,
                 duration_frames: int, fps: int, points: list[dict],
                 preview_start_frame: int, preview_duration_frames: int) -> None:
        super().__init__()
        self.clip_id = clip_id
        self.path = path
        self.source_in_frame = source_in_frame
        self.duration_frames = duration_frames
        self.fps = fps
        self.points = [dict(point) for point in points]
        self.preview_start_frame = preview_start_frame
        self.preview_duration_frames = preview_duration_frames
        self.signals = SpeedRampPreviewSignals()

    def run(self) -> None:
        try:
            result = create_speed_ramp_preview(
                self.path, self.source_in_frame, self.duration_frames,
                self.fps, self.points, self.preview_start_frame,
                self.preview_duration_frames,
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


class LocalMediaAnalysisSignals(QObject):
    finished = Signal(object, object, str)


class LocalMediaAnalysisTask(QRunnable):
    """Run bounded, local-only AI-editor diagnostics away from the GUI thread."""

    def __init__(self, project_data: dict[str, Any], media_paths: list[str]) -> None:
        super().__init__()
        self.project_data = project_data
        self.media_paths = list(media_paths)
        self.signals = LocalMediaAnalysisSignals()

    def run(self) -> None:
        try:
            project = TimelineProject.from_dict(self.project_data)
            context = build_project_context(project, self.media_paths)
            report = analyze_project_media(context)
            self.signals.finished.emit(context, report, "")
        except Exception as exc:
            self.signals.finished.emit(None, None, str(exc))


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
        self._scope_pool = QThreadPool(self)
        self._scope_pool.setMaxThreadCount(1)
        self._scope_tasks: list[RGBHistogramTask] = []
        self._scope_clip_id: str | None = None
        self._ai_analysis_pool = QThreadPool(self)
        self._ai_analysis_pool.setMaxThreadCount(1)
        self._ai_analysis_task: LocalMediaAnalysisTask | None = None
        self._ai_project_context = None
        self._ai_media_analysis = None
        self._ai_analysis_project_data: dict[str, Any] | None = None
        self._ai_analysis_media_fingerprint = None
        self._ai_story_blueprint = None
        self._ai_shot_selection_report = None
        self._ai_edit_draft = None
        self._ai_preview_base_project_data: dict[str, Any] | None = None
        self._ai_execution_preview = None
        self._graded_preview_clip_id: str | None = None
        self._speed_ramp_preview_pool = QThreadPool(self)
        self._speed_ramp_preview_pool.setMaxThreadCount(1)
        self._speed_ramp_preview_tasks: list[SpeedRampPreviewTask] = []
        self._speed_ramp_preview_pending: set[str] = set()
        self.waveforms: dict[str, list[float]] = {}
        self._undo_stack: list[dict[str, Any]] = []
        self._redo_stack: list[dict[str, Any]] = []
        self._history_limit = 50
        self.timeline_project = TimelineProject()
        self._saved_project_snapshot = self._project_snapshot()
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
        self._recovery_path = default_recovery_path()
        self._recovery_timer = QTimer(self)
        self._recovery_timer.setInterval(60_000)
        self._recovery_timer.timeout.connect(self._autosave_recovery)
        self._recovery_timer.start()
        self.statusBar().showMessage("آماده | فایل‌های رسانه‌ای را وارد کنید")
        QTimer.singleShot(0, self._check_recovery)

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
        brand = QLabel("ZENITH <span style='color:#D6AE55'>DESKTOP</span>")
        brand.setObjectName("brand")
        subtitle = QLabel("DESKTOP VIDEO STUDIO  •  PERFORMANCE FIRST")
        subtitle.setObjectName("subtitle")
        header.addWidget(brand)
        header.addStretch(1)
        header.addWidget(subtitle)
        outer.addLayout(header)

        ai_panel = self._panel("AI EDITING  |  تحلیل هوشمند رسانه — محلی و خصوصی")
        ai_layout = ai_panel.layout()
        ai_controls = QHBoxLayout()
        self.ai_analyze_button = QPushButton("تحلیل رسانه‌های پروژه")
        self.ai_analyze_button.setToolTip("تحلیل محلی صحنه‌ها، نمونه‌های تصویری و ویژگی‌های صوتی؛ بدون ارسال فایل به اینترنت")
        self.ai_analyze_button.clicked.connect(self.run_ai_media_analysis)
        self.ai_music_combo = QComboBox()
        self.ai_music_combo.setMinimumWidth(240)
        self.ai_music_combo.addItem("پس از تحلیل، موسیقی را انتخاب کنید", None)
        self.ai_music_combo.currentIndexChanged.connect(self._ai_approval_changed)
        self.ai_pace_combo = QComboBox()
        for label, value in (("متعادل", "balanced"), ("آرام", "calm"), ("پرانرژی", "energetic"), ("تریلر", "trailer")):
            self.ai_pace_combo.addItem(label, value)
        self.ai_pace_combo.currentIndexChanged.connect(self._ai_approval_changed)
        ai_controls.addWidget(self.ai_analyze_button)
        ai_controls.addWidget(QLabel("موسیقی مرجع:"))
        ai_controls.addWidget(self.ai_music_combo, 2)
        ai_controls.addWidget(QLabel("ریتم تدوین:"))
        ai_controls.addWidget(self.ai_pace_combo)
        ai_layout.addLayout(ai_controls)
        self.ai_analysis_output = QPlainTextEdit()
        self.ai_analysis_output.setReadOnly(True)
        self.ai_analysis_output.setMaximumHeight(112)
        self.ai_analysis_output.setPlainText("هنوز تحلیلی انجام نشده است. تحلیل فقط روی همین رایانه اجرا می‌شود؛ هیچ فایل یا مسیر محلی به سرویس ابری ارسال نمی‌شود. انتخاب موسیقی و ریتم برای مرحله ساخت پیش‌نویس نگه‌داری می‌شود.")
        ai_layout.addWidget(self.ai_analysis_output)

        self.ai_workflow_group = QGroupBox("مرحله دوم: داستان، انتخاب نما و اجرای تدوین تأییدشده")
        self.ai_workflow_group.setCheckable(True)
        self.ai_workflow_group.setChecked(False)
        workflow_layout = QVBoxLayout(self.ai_workflow_group)
        ai_layout.addWidget(self.ai_workflow_group)
        story_heading = QLabel("STORY & EDIT PLAN  |  طرح داستان، انتخاب نما و تأیید انسانی")
        story_heading.setObjectName("panel_title")
        workflow_layout.addWidget(story_heading)
        self.ai_story_json = QPlainTextEdit()
        self.ai_story_json.setPlaceholderText("JSON طرح داستانِ تولیدشده توسط سرویس هوش مصنوعیِ مورداعتماد خودت را اینجا وارد یا بارگذاری کن…\nفعلاً هیچ ارائه‌دهنده ابری به برنامه متصل نیست.")
        self.ai_story_json.setMaximumHeight(96)
        self.ai_story_json.textChanged.connect(self._invalidate_ai_story)
        workflow_layout.addWidget(self.ai_story_json)
        story_actions = QHBoxLayout()
        self.ai_load_story_button = QPushButton("بارگذاری طرح JSON")
        self.ai_load_story_button.clicked.connect(self.load_ai_story_json)
        self.ai_validate_story_button = QPushButton("اعتبارسنجی داستان")
        self.ai_validate_story_button.clicked.connect(self.validate_ai_story)
        self.ai_select_shots_button = QPushButton("پیشنهاد انتخاب نماها")
        self.ai_select_shots_button.setEnabled(False)
        self.ai_select_shots_button.clicked.connect(self.run_ai_shot_selection)
        story_actions.addWidget(self.ai_load_story_button)
        story_actions.addWidget(self.ai_validate_story_button)
        story_actions.addWidget(self.ai_select_shots_button)
        workflow_layout.addLayout(story_actions)
        approvals = QHBoxLayout()
        self.ai_story_approval = QCheckBox("داستان را بررسی و تأیید کردم")
        self.ai_shot_approval = QCheckBox("انتخاب نماها را بررسی و تأیید کردم")
        self.ai_story_approval.setEnabled(False)
        self.ai_shot_approval.setEnabled(False)
        self.ai_story_approval.toggled.connect(self._ai_approval_changed)
        self.ai_shot_approval.toggled.connect(self._ai_approval_changed)
        approvals.addWidget(self.ai_story_approval)
        approvals.addWidget(self.ai_shot_approval)
        workflow_layout.addLayout(approvals)
        plan_actions = QHBoxLayout()
        self.ai_build_plan_button = QPushButton("ساخت پیش‌نویس تدوین موسیقی‌محور")
        self.ai_build_plan_button.setEnabled(False)
        self.ai_build_plan_button.clicked.connect(self.build_ai_edit_draft)
        self.ai_preview_plan_button = QPushButton("پیش‌نمایش ایمن روی نسخه جداگانه")
        self.ai_preview_plan_button.setEnabled(False)
        self.ai_preview_plan_button.clicked.connect(self.preview_ai_edit_draft)
        self.ai_apply_plan_button = QPushButton("اعمال نهایی طرح تأییدشده")
        self.ai_apply_plan_button.setEnabled(False)
        self.ai_apply_plan_button.clicked.connect(self.apply_ai_edit_draft)
        plan_actions.addWidget(self.ai_build_plan_button)
        plan_actions.addWidget(self.ai_preview_plan_button)
        plan_actions.addWidget(self.ai_apply_plan_button)
        workflow_layout.addLayout(plan_actions)
        outer.addWidget(ai_panel)

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
        self.relink_button = QPushButton("اتصال مجدد فایل گمشده")
        self.relink_button.setToolTip("فایل جایگزین را انتخاب کنید تا مسیر رسانه در پروژه و تایم‌لاین اصلاح شود")
        self.relink_button.clicked.connect(self.relink_selected_media)
        media_layout.addWidget(self.relink_button)

        preview_panel = self._panel("پیش‌نمایش")
        preview_layout = preview_panel.layout()
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(300)
        self.video_widget.setStyleSheet("background:#050506;")
        self.player.setVideoOutput(self.video_widget)
        self.mask_overlay = PolygonMaskOverlay(self.video_widget)
        self.mask_overlay.setGeometry(self.video_widget.rect())
        self.video_widget.installEventFilter(self)
        self.mask_overlay.editingStarted.connect(self._mask_overlay_edit_started)
        self.mask_overlay.pointsChanged.connect(self._polygon_mask_points_changed)
        self.mask_overlay.geometryChanged.connect(self._mask_geometry_changed)
        self.mask_overlay.rotationChanged.connect(self._mask_rotation_changed)
        self.mask_overlay.featherChanged.connect(self._mask_feather_changed)
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
        self.transition_type_label = QLabel('نوع گذار')
        inspector_layout.addWidget(self.transition_type_label)
        self.transition_type_combo = QComboBox()
        self.transition_type_combo.addItem('Cross Dissolve', 'dissolve')
        self.transition_type_combo.addItem('Wipe از چپ', 'wipe_left')
        self.transition_type_combo.addItem('Push از چپ', 'push_left')
        self.transition_type_combo.currentIndexChanged.connect(self._cross_dissolve_changed)
        inspector_layout.addWidget(self.transition_type_combo)
        inspector_layout.addWidget(QLabel("Blend Mode — ترکیب لایه"))
        self.blend_mode_combo = QComboBox()
        self.blend_mode_combo.addItem("Normal", "normal")
        self.blend_mode_combo.addItem("Multiply", "multiply")
        self.blend_mode_combo.addItem("Screen", "screen")
        self.blend_mode_combo.addItem("Addition", "addition")
        self.blend_mode_combo.addItem("Overlay", "overlay")
        self.blend_mode_combo.currentIndexChanged.connect(self._blend_mode_changed)
        inspector_layout.addWidget(self.blend_mode_combo)

        inspector_layout.addWidget(QLabel("Chroma Key — حذف پرده سبز"))
        self.chroma_key_checkbox = QCheckBox("فعال‌سازی Chroma Key")
        self.chroma_key_checkbox.toggled.connect(self._clip_effects_changed)
        inspector_layout.addWidget(self.chroma_key_checkbox)
        self.chroma_key_color_edit = QLineEdit("#00FF00")
        self.chroma_key_color_edit.setMaximumWidth(130)
        self.chroma_key_color_edit.editingFinished.connect(self._clip_effects_changed)
        inspector_layout.addWidget(QLabel("رنگ کلید (#RRGGBB)"))
        inspector_layout.addWidget(self.chroma_key_color_edit)
        self.chroma_key_similarity_spin = QDoubleSpinBox()
        self.chroma_key_similarity_spin.setRange(0.0, 1.0)
        self.chroma_key_similarity_spin.setSingleStep(0.02)
        self.chroma_key_similarity_spin.setValue(0.25)
        self.chroma_key_similarity_spin.valueChanged.connect(self._clip_effects_changed)
        inspector_layout.addWidget(QLabel("Chroma Similarity"))
        inspector_layout.addWidget(self.chroma_key_similarity_spin)
        self.chroma_key_blend_spin = QDoubleSpinBox()
        self.chroma_key_blend_spin.setRange(0.0, 1.0)
        self.chroma_key_blend_spin.setSingleStep(0.02)
        self.chroma_key_blend_spin.setValue(0.08)
        self.chroma_key_blend_spin.valueChanged.connect(self._clip_effects_changed)
        inspector_layout.addWidget(QLabel("Chroma Edge Blend"))
        inspector_layout.addWidget(self.chroma_key_blend_spin)

        inspector_layout.addWidget(QLabel("Rectangular Mask — ماسک مستطیلی"))
        self.mask_checkbox = QCheckBox("فعال‌سازی ماسک")
        self.mask_checkbox.toggled.connect(self._clip_effects_changed)
        inspector_layout.addWidget(self.mask_checkbox)
        self.mask_invert_checkbox = QCheckBox("معکوس کردن ناحیه ماسک (Invert)")
        self.mask_invert_checkbox.toggled.connect(self._clip_effects_changed)
        inspector_layout.addWidget(self.mask_invert_checkbox)
        self.mask_controls: dict[str, QDoubleSpinBox] = {}
        for key, label, default in (
            ("mask_x", "Mask X", 0.0), ("mask_y", "Mask Y", 0.0),
            ("mask_width", "Mask Width", 1.0), ("mask_height", "Mask Height", 1.0),
        ):
            inspector_layout.addWidget(QLabel(label + " (0–1)"))
            spin = QDoubleSpinBox()
            spin.setRange(0.01 if key in ("mask_width", "mask_height") else 0.0, 1.0)
            spin.setSingleStep(0.05)
            spin.setDecimals(2)
            spin.setValue(default)
            spin.valueChanged.connect(self._clip_effects_changed)
            self.mask_controls[key] = spin
            inspector_layout.addWidget(spin)
        inspector_layout.addWidget(QLabel("Mask Shape"))
        self.mask_shape_combo = QComboBox()
        self.mask_shape_combo.addItem("Rectangle", "rectangle")
        self.mask_shape_combo.addItem("Ellipse / Circle", "ellipse")
        self.mask_shape_combo.addItem("Polygon (3–8 points)", "polygon")
        self.mask_shape_combo.currentIndexChanged.connect(self._clip_effects_changed)
        inspector_layout.addWidget(self.mask_shape_combo)
        inspector_layout.addWidget(QLabel("Mask Rotation (degrees)"))
        self.mask_rotation_spin = QDoubleSpinBox()
        self.mask_rotation_spin.setRange(-3600.0, 3600.0)
        self.mask_rotation_spin.setSingleStep(1.0)
        self.mask_rotation_spin.setDecimals(1)
        self.mask_rotation_spin.valueChanged.connect(self._mask_rotation_control_changed)
        inspector_layout.addWidget(self.mask_rotation_spin)
        inspector_layout.addWidget(QLabel("Mask Feather (pixels)"))
        self.mask_feather_spin = QDoubleSpinBox()
        self.mask_feather_spin.setRange(0.0, 40.0)
        self.mask_feather_spin.setSingleStep(1.0)
        self.mask_feather_spin.setDecimals(1)
        self.mask_feather_spin.valueChanged.connect(self._clip_effects_changed)
        inspector_layout.addWidget(self.mask_feather_spin)
        inspector_layout.addWidget(QLabel("Polygon Points — x,y; x,y; ... (0–1)"))
        self.mask_points_edit = QLineEdit("0.5,0.1; 0.9,0.9; 0.1,0.9")
        self.mask_points_edit.setToolTip("۳ تا ۸ نقطه با مختصات نسبی تصویر؛ نمونه: 0.5,0.1; 0.9,0.9; 0.1,0.9")
        self.mask_points_edit.editingFinished.connect(self._clip_effects_changed)
        inspector_layout.addWidget(self.mask_points_edit)
        inspector_layout.addWidget(QLabel("Mask Animation — frame داخل کلیپ"))
        self.mask_keyframe_frame_spin = QSpinBox()
        self.mask_keyframe_frame_spin.setRange(0, 1000000)
        self.mask_keyframe_frame_spin.setToolTip("شماره فریم نسبت به ابتدای کلیپ انتخاب‌شده")
        inspector_layout.addWidget(self.mask_keyframe_frame_spin)
        self.add_mask_keyframe_button = QPushButton("ثبت وضعیت ماسک در این فریم")
        self.add_mask_keyframe_button.setEnabled(False)
        self.add_mask_keyframe_button.clicked.connect(self._add_mask_keyframe)
        inspector_layout.addWidget(self.add_mask_keyframe_button)
        self.delete_mask_keyframe_button = QPushButton("حذف Keyframe ماسک در این فریم")
        self.delete_mask_keyframe_button.setEnabled(False)
        self.delete_mask_keyframe_button.clicked.connect(self._delete_mask_keyframe)
        inspector_layout.addWidget(self.delete_mask_keyframe_button)
        self.mask_keyframes_label = QLabel("Mask Keyframes: —")
        self.mask_keyframes_label.setWordWrap(True)
        inspector_layout.addWidget(self.mask_keyframes_label)


        transform_heading = QLabel("حرکت و Transform با Keyframe")
        transform_heading.setObjectName("panel_title")
        inspector_layout.addWidget(transform_heading)
        self.transform_controls: dict[str, QDoubleSpinBox] = {}
        for key, title, low, high, step, value in (
            ("x", "Position X", -2.0, 2.0, 0.05, 0.0),
            ("y", "Position Y", -2.0, 2.0, 0.05, 0.0),
            ("scale", "Scale", 0.1, 4.0, 0.05, 1.0),
            ("rotation", "Rotation", -3600.0, 3600.0, 1.0, 0.0),
            ("opacity", "Opacity (0–1)", 0.0, 1.0, 0.05, 1.0),
        ):
            inspector_layout.addWidget(QLabel(title))
            spin = QDoubleSpinBox()
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.setDecimals(2)
            spin.setValue(value)
            self.transform_controls[key] = spin
            inspector_layout.addWidget(spin)
        self.anchor_controls: dict[str, QDoubleSpinBox] = {}
        for key, title in (("anchor_x", "Anchor X (0 تا 1)"), ("anchor_y", "Anchor Y (0 تا 1)")):
            inspector_layout.addWidget(QLabel(title))
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1.0)
            spin.setSingleStep(0.05)
            spin.setDecimals(2)
            spin.setValue(0.5)
            self.anchor_controls[key] = spin
            inspector_layout.addWidget(spin)
        inspector_layout.addWidget(QLabel("نوع حرکت تا Keyframe بعدی"))
        self.transform_easing_combo = QComboBox()
        self.transform_easing_combo.addItem("Linear", "linear")
        self.transform_easing_combo.addItem("Ease In", "ease_in")
        self.transform_easing_combo.addItem("Ease Out", "ease_out")
        self.transform_easing_combo.addItem("Ease In-Out", "ease_in_out")
        self.transform_easing_combo.addItem("Cubic Bezier", "bezier")
        inspector_layout.addWidget(self.transform_easing_combo)
        self.bezier_controls: dict[str, QDoubleSpinBox] = {}
        self.bezier_curve_widget = BezierCurveWidget()
        self.bezier_curve_widget.setVisible(False)
        self.bezier_curve_widget.valuesChanged.connect(self._bezier_graph_changed)
        self.bezier_curve_widget.editingStarted.connect(self._bezier_graph_edit_started)
        self.bezier_curve_widget.editingFinished.connect(self._bezier_graph_edit_finished)
        for key, title, default in (("bezier_y1", "Bezier Handle 1 (Y)", 0.0),
                                    ("bezier_y2", "Bezier Handle 2 (Y)", 1.0)):
            inspector_layout.addWidget(QLabel(title))
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1.0)
            spin.setSingleStep(0.05)
            spin.setDecimals(2)
            spin.setValue(default)
            self.bezier_controls[key] = spin
            inspector_layout.addWidget(spin)
        inspector_layout.addWidget(QLabel("نمودار منحنی Bezier — دستگیره‌ها را بکشید"))
        inspector_layout.addWidget(self.bezier_curve_widget)
        self.transform_easing_combo.currentIndexChanged.connect(self._sync_bezier_graph_visibility)
        self._bezier_edit_snapshot_active = False
        self.add_transform_keyframe_button = QPushButton("ثبت Keyframe در محل Playhead")
        self.add_transform_keyframe_button.setEnabled(False)
        self.add_transform_keyframe_button.clicked.connect(self._add_transform_keyframe)
        inspector_layout.addWidget(self.add_transform_keyframe_button)
        self.delete_transform_keyframe_button = QPushButton("حذف Keyframe انتخاب‌شده")
        self.delete_transform_keyframe_button.setEnabled(False)
        self.delete_transform_keyframe_button.clicked.connect(self._delete_transform_keyframe)
        inspector_layout.addWidget(self.delete_transform_keyframe_button)
        self.transform_keyframes_label = QLabel("Keyframe: —")
        inspector_layout.addWidget(self.transform_keyframes_label)
        inspector_layout.addWidget(QLabel("Playback speed"))
        self.playback_speed_combo = QComboBox()
        for label, rate in (("0.25x — Slow", 0.25), ("0.5x — Half", 0.5), ("0.75x", 0.75), ("1x — Normal", 1.0), ("1.25x", 1.25), ("1.5x", 1.5), ("2x — Fast", 2.0), ("3x", 3.0), ("4x", 4.0)):
            self.playback_speed_combo.addItem(label, rate)
        inspector_layout.addWidget(self.playback_speed_combo)
        self.apply_speed_button = QPushButton("Apply speed and resize clip")
        self.apply_speed_button.setEnabled(False)
        self.apply_speed_button.clicked.connect(self._apply_clip_speed)
        inspector_layout.addWidget(self.apply_speed_button)
        self.motion_blur_checkbox = QCheckBox("Motion Blur سبک (۳ فریم)")
        self.motion_blur_checkbox.setEnabled(False)
        self.motion_blur_checkbox.toggled.connect(self._toggle_clip_motion_blur)
        inspector_layout.addWidget(self.motion_blur_checkbox)
        self.reverse_checkbox = QCheckBox("Reverse — پخش معکوس")
        self.reverse_checkbox.setEnabled(False)
        self.reverse_checkbox.toggled.connect(self._toggle_clip_reverse)
        inspector_layout.addWidget(self.reverse_checkbox)
        inspector_layout.addWidget(QLabel("Speed Ramp — تنظیم سرعت در فریم کلیپ"))
        self.speed_ramp_frame_spin = QDoubleSpinBox()
        self.speed_ramp_frame_spin.setDecimals(0)
        self.speed_ramp_frame_spin.setRange(0, 1000000)
        self.speed_ramp_frame_spin.setPrefix("Frame ")
        self.speed_ramp_frame_spin.setEnabled(False)
        inspector_layout.addWidget(self.speed_ramp_frame_spin)
        self.speed_ramp_rate_spin = QDoubleSpinBox()
        self.speed_ramp_rate_spin.setRange(0.25, 4.0)
        self.speed_ramp_rate_spin.setSingleStep(0.25)
        self.speed_ramp_rate_spin.setDecimals(2)
        self.speed_ramp_rate_spin.setSuffix("x")
        self.speed_ramp_rate_spin.setEnabled(False)
        inspector_layout.addWidget(self.speed_ramp_rate_spin)
        self.add_speed_ramp_button = QPushButton("ثبت نقطه سرعت")
        self.add_speed_ramp_button.setEnabled(False)
        self.add_speed_ramp_button.clicked.connect(self._add_speed_ramp_point)
        inspector_layout.addWidget(self.add_speed_ramp_button)
        self.clear_speed_ramp_button = QPushButton("پاک‌کردن منحنی سرعت")
        self.clear_speed_ramp_button.setEnabled(False)
        self.clear_speed_ramp_button.clicked.connect(self._clear_speed_ramp)
        inspector_layout.addWidget(self.clear_speed_ramp_button)
        self.speed_ramp_label = QLabel("Speed Ramp: هنوز نقطه‌ای ثبت نشده")
        self.speed_ramp_label.setWordWrap(True)
        inspector_layout.addWidget(self.speed_ramp_label)
        self.speed_ramp_status_label = QLabel("منحنی سرعت در تایم‌لاین نمایش داده می‌شود؛ پیش‌نمایش کوتاه با کیفیت سبک ساخته می‌شود.")
        self.speed_ramp_status_label.setWordWrap(True)
        inspector_layout.addWidget(self.speed_ramp_status_label)
        self.speed_ramp_preview_button = QPushButton("پیش‌نمایش Speed Ramp (۵ ثانیه)")
        self.speed_ramp_preview_button.setEnabled(False)
        self.speed_ramp_preview_button.clicked.connect(self.preview_speed_ramp)
        inspector_layout.addWidget(self.speed_ramp_preview_button)

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
            ("highlights", "Highlights", -100, 100, 0.01, 0, "روشنایی نواحی روشن تصویر"),
            ("shadows", "Shadows", -100, 100, 0.01, 0, "جزئیات نواحی سایه"),
            ("whites", "Whites", -100, 100, 0.01, 0, "سطح سفید و روشن‌ترین نقاط"),
            ("blacks", "Blacks", -100, 100, 0.01, 0, "سطح سیاه و عمیق‌ترین سایه‌ها"),
            ("wheel_shadows_r", "Shadows Wheel · Red", -100, 100, 0.01, 0, "افزودن یا کاهش قرمز در سایه‌ها"),
            ("wheel_shadows_g", "Shadows Wheel · Green", -100, 100, 0.01, 0, "افزودن یا کاهش سبز در سایه‌ها"),
            ("wheel_shadows_b", "Shadows Wheel · Blue", -100, 100, 0.01, 0, "افزودن یا کاهش آبی در سایه‌ها"),
            ("wheel_midtones_r", "Midtones Wheel · Red", -100, 100, 0.01, 0, "افزودن یا کاهش قرمز در تون‌های میانی"),
            ("wheel_midtones_g", "Midtones Wheel · Green", -100, 100, 0.01, 0, "افزودن یا کاهش سبز در تون‌های میانی"),
            ("wheel_midtones_b", "Midtones Wheel · Blue", -100, 100, 0.01, 0, "افزودن یا کاهش آبی در تون‌های میانی"),
            ("wheel_highlights_r", "Highlights Wheel · Red", -100, 100, 0.01, 0, "افزودن یا کاهش قرمز در روشنایی‌ها"),
            ("wheel_highlights_g", "Highlights Wheel · Green", -100, 100, 0.01, 0, "افزودن یا کاهش سبز در روشنایی‌ها"),
            ("wheel_highlights_b", "Highlights Wheel · Blue", -100, 100, 0.01, 0, "افزودن یا کاهش آبی در روشنایی‌ها"),
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

        # Keep the existing RGB sliders as the canonical persisted controls,
        # but present their three-way groups through compact circular widgets.
        self.color_wheels: dict[str, ColorWheelWidget] = {}
        wheel_row = QHBoxLayout()
        for zone, title in (("shadows", "Shadows"), ("midtones", "Midtones"), ("highlights", "Highlights")):
            wheel = ColorWheelWidget(title)
            wheel.valuesChanged.connect(lambda x, y, z=zone: self._color_wheel_changed(z, x, y))
            wheel.editingStarted.connect(self._push_undo)
            wheel_row.addWidget(wheel, 1)
            self.color_wheels[zone] = wheel
            for channel in ("r", "g", "b"):
                slider, label, _ = self.color_controls[f"wheel_{zone}_{channel}"]
                slider.hide()
                label.hide()
        inspector_layout.addLayout(wheel_row)
        self.color_wheel_reset_button = QPushButton("بازنشانی چرخ‌های رنگ")
        self.color_wheel_reset_button.clicked.connect(self._reset_color_wheels)
        inspector_layout.addWidget(self.color_wheel_reset_button)

        self.color_preview_button = QPushButton("ساخت پیش‌نمایش رنگ کلیپ")
        self.color_preview_button.setToolTip(
            "رندر یک پیش‌نمایش کم‌حجم از کلیپ انتخاب‌شده با تنظیمات رنگ فعلی"
        )
        self.color_preview_button.setEnabled(False)
        self.color_preview_button.clicked.connect(self.create_color_preview_for_selected_clip)
        inspector_layout.addWidget(self.color_preview_button)

        scopes_heading = QLabel("Scopes — تحلیل رنگ")
        scopes_heading.setObjectName("panel_title")
        inspector_layout.addWidget(scopes_heading)
        self.rgb_histogram_widget = RGBHistogramWidget()
        inspector_layout.addWidget(self.rgb_histogram_widget)
        self.rgb_histogram_button = QPushButton("تحلیل هیستوگرام RGB")
        self.rgb_histogram_button.setToolTip("فقط یک فریم کوچک ۲۵۶×۱۴۴ را در پس‌زمینه نمونه‌برداری می‌کند")
        self.rgb_histogram_button.setEnabled(False)
        self.rgb_histogram_button.clicked.connect(self.analyze_rgb_histogram)
        inspector_layout.addWidget(self.rgb_histogram_button)

        self.waveform_widget = ScopeMatrixWidget("waveform")
        inspector_layout.addWidget(self.waveform_widget)
        self.waveform_button = QPushButton("تحلیل Waveform")
        self.waveform_button.setEnabled(False)
        self.waveform_button.clicked.connect(lambda: self.analyze_video_scope("waveform"))
        inspector_layout.addWidget(self.waveform_button)

        self.rgb_parade_widget = ScopeMatrixWidget("parade")
        inspector_layout.addWidget(self.rgb_parade_widget)
        self.rgb_parade_button = QPushButton("تحلیل RGB Parade")
        self.rgb_parade_button.setEnabled(False)
        self.rgb_parade_button.clicked.connect(lambda: self.analyze_video_scope("parade"))
        inspector_layout.addWidget(self.rgb_parade_button)

        self.vectorscope_widget = VectorScopeWidget()
        inspector_layout.addWidget(self.vectorscope_widget)
        self.vectorscope_button = QPushButton("تحلیل Vectorscope")
        self.vectorscope_button.setEnabled(False)
        self.vectorscope_button.clicked.connect(lambda: self.analyze_video_scope("vectorscope"))
        inspector_layout.addWidget(self.vectorscope_button)

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
        self.timeline_widget.speedRampChanged.connect(self._speed_ramp_changed)
        self.timeline_widget.transformKeyframeMoved.connect(self._transform_keyframe_moved)
        self.timeline_widget.transformKeyframeSelected.connect(self._transform_keyframe_selected)
        self.timeline_widget.maskKeyframeMoved.connect(self._mask_keyframe_moved)
        self.timeline_widget.maskKeyframeSelected.connect(self._mask_keyframe_selected)
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

    def run_ai_media_analysis(self) -> None:
        if self._ai_analysis_task is not None or self._ai_analysis_pool.activeThreadCount():
            self.statusBar().showMessage("تحلیل رسانه‌ها در حال اجراست؛ لطفاً منتظر بمانید.")
            return
        paths = [str(item.get("path", "")) for item in self.media_items if item.get("path")]
        if not paths and not self.timeline_project.clips:
            QMessageBox.information(self, "تحلیل هوشمند", "ابتدا فایل‌های رسانه‌ای را وارد پروژه کنید.")
            return
        self.ai_analyze_button.setEnabled(False)
        self.ai_analysis_output.setPlainText("تحلیل محلی آغاز شد…\nتشخیص مرز صحنه، نمونه‌برداری تصویری و بررسی صوت در پس‌زمینه انجام می‌شود.")
        self._ai_analysis_project_data = self.timeline_project.to_dict()
        self._ai_analysis_media_fingerprint = media_inventory_fingerprint(
            self.timeline_project, paths
        )
        self._ai_story_blueprint = None
        self._ai_shot_selection_report = None
        self._ai_edit_draft = None
        self._ai_execution_preview = None
        self._ai_story_approval.setChecked(False)
        self._ai_shot_approval.setChecked(False)
        self.ai_select_shots_button.setEnabled(False)
        self.ai_build_plan_button.setEnabled(False)
        self.ai_preview_plan_button.setEnabled(False)
        self.ai_apply_plan_button.setEnabled(False)
        task = LocalMediaAnalysisTask(self._ai_analysis_project_data, paths)
        self._ai_analysis_task = task
        task.signals.finished.connect(self._ai_media_analysis_finished)
        self._ai_analysis_pool.start(task)
        self.statusBar().showMessage("تحلیل محلی رسانه‌ها آغاز شد؛ رابط کاربری آزاد می‌ماند.")

    def _ai_media_analysis_finished(self, context: object, report: object, error: str) -> None:
        self._ai_analysis_task = None
        self.ai_analyze_button.setEnabled(True)
        if error or context is None or report is None:
            self.ai_analysis_output.setPlainText(f"تحلیل کامل نشد: {error or 'نتیجه معتبر دریافت نشد.'}")
            self.statusBar().showMessage("تحلیل رسانه‌ها ناموفق بود.")
            return
        self._ai_project_context = context
        self._ai_media_analysis = report
        self.ai_music_combo.clear()
        self.ai_music_combo.addItem("انتخاب موسیقی مرجع…", None)
        for item in context.assets:
            asset = item.asset
            if item.exists and (asset.media_type == "audio" or (asset.media_type == "video" and asset.has_audio)):
                self.ai_music_combo.addItem(Path(asset.path).name, asset.asset_id)
        lines = [
            f"تحلیل تمام شد | {len(context.assets)} رسانه بررسی‌شده | {len(report.assets)} گزارش تحلیلی",
            "پردازش محلی بود؛ هیچ فایل رسانه‌ای به فضای ابری ارسال نشد.",
        ]
        for result in report.assets:
            name = next((Path(item.asset.path).name for item in context.assets if item.asset.asset_id == result.asset_id), result.asset_id)
            details = [f"صحنه‌ها: {len(result.scene_boundaries_seconds)}"]
            if result.visual_samples:
                details.append(f"نمونه‌های تصویر: {len(result.visual_samples)}")
            if result.spectral_audio and result.spectral_audio.estimated_bpm is not None:
                details.append(f"BPM تخمینی: {result.spectral_audio.estimated_bpm:.1f} (اعتماد {result.spectral_audio.tempo_confidence:.2f})")
            if result.audio:
                details.append(f"پیک صدا: {result.audio.peak_db if result.audio.peak_db is not None else 'نامشخص'} dB")
            lines.append(f"• {name}: " + " | ".join(details))
            for warning in result.warnings[:2]:
                lines.append(f"  هشدار: {warning}")
        if report.warnings:
            lines.append(f"هشدارهای پروژه: {len(report.warnings)}")
        lines.append("نکته: BPM و نقاط ضرب فقط تخمین فنی‌اند؛ تأیید شنیداری لازم است. هنوز هیچ کلیپی جابه‌جا یا تدوین نشده است.")
        self.ai_analysis_output.setPlainText("\n".join(lines))
        self.statusBar().showMessage("تحلیل محلی آماده است؛ هیچ تغییری در تایم‌لاین اعمال نشد.")

    def _ai_context_is_current(self) -> bool:
        if self._ai_project_context is None or self._ai_analysis_project_data is None:
            QMessageBox.information(self, "AI Editing", "ابتدا تحلیل رسانه‌های پروژه را اجرا کنید.")
            return False
        if self.timeline_project.to_dict() != self._ai_analysis_project_data:
            QMessageBox.warning(self, "AI Editing", "تایم‌لاین پس از تحلیل تغییر کرده است. برای جلوگیری از استفاده از داده قدیمی، تحلیل را دوباره اجرا کنید.")
            return False
        current_paths = [str(item.get("path", "")) for item in self.media_items if item.get("path")]
        current_fingerprint = media_inventory_fingerprint(self.timeline_project, current_paths)
        if current_fingerprint != self._ai_analysis_media_fingerprint:
            QMessageBox.warning(
                self, "AI Editing",
                "فهرست رسانه‌ها یا فایل منبع پس از تحلیل تغییر کرده است. "
                "برای جلوگیری از تدوین با اطلاعات قدیمی، تحلیل رسانه‌ها را دوباره اجرا کنید."
            )
            return False
        return True

    def load_ai_story_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "بارگذاری طرح داستان", "", "JSON files (*.json);;All files (*.*)")
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8")
            self.ai_story_json.setPlainText(content)
            self.statusBar().showMessage("طرح داستان بارگذاری شد؛ برای بررسی ساختار، اعتبارسنجی را اجرا کنید.")
        except (OSError, UnicodeError) as exc:
            QMessageBox.warning(self, "بارگذاری طرح", f"خواندن فایل ناموفق بود: {exc}")

    def _invalidate_ai_story(self) -> None:
        self._ai_story_blueprint = None
        self._ai_shot_selection_report = None
        self._ai_edit_draft = None
        self._ai_execution_preview = None
        self.ai_story_approval.setChecked(False)
        self.ai_shot_approval.setChecked(False)
        self.ai_story_approval.setEnabled(False)
        self.ai_shot_approval.setEnabled(False)
        self.ai_select_shots_button.setEnabled(False)
        self.ai_build_plan_button.setEnabled(False)
        self.ai_preview_plan_button.setEnabled(False)
        self.ai_apply_plan_button.setEnabled(False)

    def validate_ai_story(self) -> None:
        if not self._ai_context_is_current():
            return
        try:
            raw = json.loads(self.ai_story_json.toPlainText())
            story = story_blueprint_from_dict(raw)
            story.validate(self._ai_project_context)
        except Exception as exc:
            self._ai_story_blueprint = None
            self._ai_shot_selection_report = None
            self.ai_select_shots_button.setEnabled(False)
            self.ai_story_approval.setChecked(False)
            self.ai_story_approval.setEnabled(False)
            QMessageBox.warning(self, "اعتبارسنجی داستان", str(exc))
            return
        self._ai_story_blueprint = story
        self._ai_shot_selection_report = None
        self._ai_edit_draft = None
        self._ai_execution_preview = None
        self.ai_story_approval.setChecked(False)
        self.ai_shot_approval.setChecked(False)
        self.ai_story_approval.setEnabled(True)
        self.ai_shot_approval.setEnabled(False)
        self.ai_select_shots_button.setEnabled(True)
        self.ai_build_plan_button.setEnabled(False)
        self.ai_preview_plan_button.setEnabled(False)
        self.ai_apply_plan_button.setEnabled(False)
        beat_lines = [f"{beat.sequence + 1}. {beat.title} — {beat.target_duration_seconds:.1f}s" for beat in story.beats]
        self.ai_analysis_output.appendPlainText(
            "\nطرح داستان معتبر است اما هنوز تأیید نشده است.\n"
            f"خلاصه: {story.logline}\nمدت تخمینی: {story.estimated_duration_seconds:.1f}s | Acts: {len(story.acts)} | Beats: {len(story.beats)}\n"
            + "\n".join(beat_lines)
        )
        self.statusBar().showMessage("طرح داستان معتبر شد؛ تأیید انسانی و انتخاب نماها هنوز لازم است.")

    def run_ai_shot_selection(self) -> None:
        if not self._ai_context_is_current() or self._ai_story_blueprint is None:
            return
        try:
            report = select_shots_for_story(
                self._ai_story_blueprint, self._ai_project_context, self._ai_media_analysis
            )
        except Exception as exc:
            QMessageBox.warning(self, "انتخاب نماها", str(exc))
            return
        self._ai_shot_selection_report = report
        self._ai_story_blueprint = report.blueprint
        self._ai_shot_approval.setChecked(False)
        self._ai_shot_approval.setEnabled(True)
        self.ai_build_plan_button.setEnabled(False)
        self.ai_preview_plan_button.setEnabled(False)
        self.ai_apply_plan_button.setEnabled(False)
        lines = [
            f"\nگزارش انتخاب نما: {len(report.decisions)} ضرب داستانی | {report.candidates_considered} بازه بررسی‌شده",
        ]
        for decision in report.decisions:
            lines.append(f"• {decision.beat_id}: {decision.confidence} | امتیاز {decision.score if decision.score is not None else '—'}")
            lines.extend(f"  - {reason}" for reason in decision.reasons[:2])
        lines.extend(f"هشدار: {warning}" for warning in report.warnings)
        lines.append("انتخاب‌ها فقط پیشنهاد فنی‌اند؛ در نبود توصیف معنایی واقعی، ارتباط محتوایی نما با داستان تأیید نشده است.")
        self.ai_analysis_output.appendPlainText("\n".join(lines))
        self.statusBar().showMessage("پیشنهاد نماها آماده بررسی است؛ هنوز هیچ تغییری در تایم‌لاین انجام نشده.")

    def _ai_approval_changed(self, *_: Any) -> None:
        # Any approval or soundtrack change invalidates downstream drafts/previews.
        self._ai_edit_draft = None
        self._ai_execution_preview = None
        self.ai_preview_plan_button.setEnabled(False)
        self.ai_apply_plan_button.setEnabled(False)
        ready = bool(
            self._ai_story_blueprint is not None
            and self._ai_shot_selection_report is not None
            and self.ai_story_approval.isChecked()
            and self.ai_shot_approval.isChecked()
            and self.ai_music_combo.currentData()
        )
        self.ai_build_plan_button.setEnabled(ready)

    def build_ai_edit_draft(self) -> None:
        if not self._ai_context_is_current():
            return
        if not self.ai_story_approval.isChecked() or not self.ai_shot_approval.isChecked():
            QMessageBox.information(self, "تأییدهای لازم", "ابتدا داستان و انتخاب نماها را جداگانه بررسی و تأیید کنید.")
            return
        audio_asset_id = self.ai_music_combo.currentData()
        if not audio_asset_id:
            QMessageBox.information(self, "موسیقی مرجع", "یک فایل صوتی یا ویدیوی دارای صدا انتخاب کنید.")
            return
        try:
            self._ai_edit_draft = build_music_aware_edit_draft(
                self._ai_story_blueprint, self._ai_project_context, self._ai_media_analysis,
                audio_asset_id=audio_asset_id,
                story_approved=self.ai_story_approval.isChecked(),
                shot_selection_approved=self.ai_shot_approval.isChecked(),
                pace_profile=self.ai_pace_combo.currentData() or "balanced",
            )
        except Exception as exc:
            self._ai_edit_draft = None
            QMessageBox.warning(self, "ساخت پیش‌نویس تدوین", str(exc))
            return
        self._ai_execution_preview = None
        self.ai_preview_plan_button.setEnabled(True)
        self.ai_apply_plan_button.setEnabled(False)
        plan = self._ai_edit_draft.edit_plan
        operation_counts = {}
        for operation in plan.operations:
            operation_counts[operation.kind] = operation_counts.get(operation.kind, 0) + 1
        lines = [
            "\nپیش‌نویس تدوین ساخته شد — هنوز روی پروژه اصلی اعمال نشده است.\nموسیقی انتخابی فقط مرجع تحلیل ریتم است و به‌عنوان ترک صوتی به تایم‌لاین اضافه نمی‌شود.",
            plan.summary,
            f"عملیات: {len(plan.operations)} | کلیپ‌ها: {operation_counts.get('add_clip', 0)} | انتقال‌ها: {operation_counts.get('set_transition', 0)}",
            *[f"هشدار: {warning}" for warning in self._ai_edit_draft.warnings],
        ]
        self.ai_analysis_output.appendPlainText("\n".join(lines))
        self.statusBar().showMessage("پیش‌نویس آماده پیش‌نمایش ایمن است؛ برای اعمال نهایی تأیید جداگانه لازم است.")

    def preview_ai_edit_draft(self) -> None:
        if not self._ai_context_is_current() or self._ai_edit_draft is None:
            return
        try:
            assets = [item.asset for item in self._ai_project_context.assets if item.exists]
            preview = preview_edit_plan(self.timeline_project, self._ai_edit_draft.edit_plan, assets)
        except Exception as exc:
            QMessageBox.warning(self, "پیش‌نمایش تدوین", str(exc))
            return
        self._ai_execution_preview = preview
        self._ai_preview_base_project_data = self.timeline_project.to_dict()
        created_ids = set(preview.created_clip_ids)
        existing_clips = list(self.timeline_project.clips)
        conflicts = []
        for created in preview.project.clips:
            if created.clip_id not in created_ids:
                continue
            for existing in existing_clips:
                if (created.track == existing.track
                        and created.start_frame < existing.end_frame
                        and existing.start_frame < created.end_frame):
                    conflicts.append(
                        f"{created.name} با کلیپ {existing.name} در ترک {created.track} هم‌پوشانی دارد"
                    )
        self.ai_apply_plan_button.setEnabled(not conflicts)
        conflict_note = (
            "\n" + "\n".join(f"تداخل تایم‌لاین: {item}" for item in conflicts)
            + "\nبرای جلوگیری از روی‌هم‌افتادن ناخواسته، اعمال نهایی غیرفعال شد؛ ابتدا باید تخصیص ترک‌ها طراحی شود."
            if conflicts else ""
        )
        self.ai_analysis_output.appendPlainText(
            f"\nپیش‌نمایش ایمن موفق: {preview.operation_count} عملیات، {len(preview.created_clip_ids)} کلیپ جدید. "
            f"مدت نسخه پیش‌نمایش: {preview.project.duration_frames / preview.project.fps:.2f}s. "
            "این پیش‌نمایش روی نسخه جداگانه اجرا شد؛ پروژه اصلی هنوز تغییر نکرده است."
            + conflict_note
        )
        self.statusBar().showMessage("پیش‌نمایش روی نسخه جداگانه موفق شد؛ اعمال نهایی همچنان منتظر تأیید است.")

    def apply_ai_edit_draft(self) -> None:
        if self._ai_execution_preview is None or self._ai_edit_draft is None:
            QMessageBox.information(self, "اعمال تدوین", "ابتدا پیش‌نمایش ایمن را با موفقیت اجرا کنید.")
            return
        if self.timeline_project.to_dict() != self._ai_preview_base_project_data:
            QMessageBox.warning(self, "طرح قدیمی", "تایم‌لاین پس از پیش‌نمایش تغییر کرده است؛ پیش‌نمایش را دوباره اجرا کنید.")
            self.ai_apply_plan_button.setEnabled(False)
            return
        answer = QMessageBox.question(
            self, "تأیید نهایی تدوین",
            "آیا می‌خواهید عملیات پیش‌نمایش‌شده به تایم‌لاین اصلی اعمال شود؟\nفایل‌های اصلی رسانه تغییر نمی‌کنند و عملیات با Undo قابل بازگشت است.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            assets = [item.asset for item in self._ai_project_context.assets if item.exists]
            self._push_undo()
            apply_edit_plan(self.timeline_project, self._ai_edit_draft.edit_plan, assets, approved=True)
        except Exception as exc:
            QMessageBox.warning(self, "اعمال تدوین", str(exc))
            return
        self._refresh_timeline()
        self._ai_execution_preview = None
        self.ai_apply_plan_button.setEnabled(False)
        self.ai_analysis_output.appendPlainText("\nطرح تأییدشده با موفقیت به تایم‌لاین اصلی اعمال شد. با Undo می‌توان آن را بازگرداند.")
        self.statusBar().showMessage("تدوین هوشمند اعمال شد؛ فایل‌های منبع دست‌نخورده باقی ماندند.")

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
        self._sync_transform_controls()
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
        self.transition_type_combo.setEnabled(enabled)
        if not enabled:
            self.cross_dissolve_label.setText("Cross Dissolve In: —")
            return
        blockers = [QSignalBlocker(self.cross_dissolve_slider), QSignalBlocker(self.transition_type_combo)]
        previous = next((item for item in reversed(self.timeline_project.clips_on_track(clip.track))
                         if item.start_frame < clip.start_frame), None)
        adjacent = bool(previous and previous.end_frame == clip.start_frame)
        still_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
        source_handles = clip.duration_frames if Path(clip.path).suffix.lower() in still_extensions else clip.source_in
        max_frames = min(clip.duration_frames, previous.duration_frames if adjacent else 0,
                         source_handles, self.timeline_project.fps * 5)
        self.cross_dissolve_slider.setRange(0, max(max_frames, clip.transition_in_frames))
        self.cross_dissolve_slider.setValue(clip.transition_in_frames)
        self.cross_dissolve_slider.setEnabled((adjacent and max_frames > 0) or clip.transition_in_frames > 0)
        self.transition_type_combo.setCurrentIndex(max(0, self.transition_type_combo.findData(clip.transition_in_type)))
        self.transition_type_combo.setEnabled((adjacent and max_frames > 0) or clip.transition_in_frames > 0)
        del blockers
        fps = max(1, self.timeline_project.fps)
        if not adjacent and clip.transition_in_frames == 0:
            self.cross_dissolve_label.setText("Transition: نیازمند کلیپ قبلی چسبیده")
        elif adjacent and max_frames == 0 and clip.transition_in_frames == 0:
            self.cross_dissolve_label.setText("Transition: نیازمند فریم قبل از In")
        else:
            transition_names = {"dissolve": "Cross Dissolve", "wipe_left": "Wipe از چپ", "push_left": "Push از چپ"}
            self.cross_dissolve_label.setText("{}: {:.1f} ثانیه".format(transition_names.get(clip.transition_in_type, "Transition"), clip.transition_in_frames / fps))

    def _cross_dissolve_changed(self, *_: Any) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        try:
            clip = self.timeline_project.get_clip(clip_id)
            self.timeline_project.set_clip_transition(
                clip_id,
                dissolve_in_frames=self.cross_dissolve_slider.value(),
                transition_type=str(self.transition_type_combo.currentData() or 'dissolve'),
            )
        except (KeyError, ValueError) as exc:
            self.statusBar().showMessage(f"تنظیم Cross Dissolve اعمال نشد: {exc}")
            self._sync_cross_dissolve_controls()
            return
        fps = max(1, self.timeline_project.fps)
        transition_names = {"dissolve": "Cross Dissolve", "wipe_left": "Wipe از چپ", "push_left": "Push از چپ"}
        self.cross_dissolve_label.setText("{}: {:.1f} ثانیه".format(transition_names.get(clip.transition_in_type, "Transition"), clip.transition_in_frames / fps))
        self.timeline_widget.refresh()
        self.statusBar().showMessage("Cross Dissolve ذخیره شد؛ پیش‌نمایش نهایی در رندر MP4 اعمال می‌شود.")


    def _blend_mode_changed(self, *_args) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        mode = str(self.blend_mode_combo.currentData() or "normal")
        try:
            self._push_undo()
            clip = self.timeline_project.get_clip(clip_id)
            clip.blend_mode = mode
            clip.validate()
        except (KeyError, ValueError) as exc:
            if self._undo_stack:
                self._undo_stack.pop()
            self._update_history_buttons()
            self.statusBar().showMessage(f"Blend Mode اعمال نشد: {exc}")
            return
        self.timeline_widget.refresh()
        self.statusBar().showMessage(
            f"Blend Mode: {mode} — هنگام رندر نهایی اعمال می‌شود؛ پیش‌نمایش زنده نیست."
        )

    def _clip_effects_changed(self, *_args) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        try:
            self._push_undo()
            clip = self.timeline_project.get_clip(clip_id)
            clip.chroma_key_enabled = self.chroma_key_checkbox.isChecked()
            clip.chroma_key_color = self.chroma_key_color_edit.text().strip()
            clip.chroma_key_similarity = self.chroma_key_similarity_spin.value()
            clip.chroma_key_blend = self.chroma_key_blend_spin.value()
            clip.mask_enabled = self.mask_checkbox.isChecked()
            clip.mask_invert = self.mask_invert_checkbox.isChecked()
            for key, control in self.mask_controls.items():
                setattr(clip, key, control.value())
            clip.mask_shape = str(self.mask_shape_combo.currentData() or "rectangle")
            local_frame = max(0, min(clip.duration_frames - 1,
                                     self.timeline_project.playhead_frame - clip.start_frame))
            active_mask_key = next((item for item in clip.mask_keyframes
                                    if int(item["frame"]) == local_frame), None)
            if active_mask_key is not None:
                active_mask_key["rotation"] = self.mask_rotation_spin.value()
            else:
                clip.mask_rotation = self.mask_rotation_spin.value()
            clip.mask_feather_px = self.mask_feather_spin.value()
            points = []
            for raw_point in self.mask_points_edit.text().split(";"):
                if raw_point.strip():
                    coords = [float(value.strip()) for value in raw_point.split(",")]
                    if len(coords) != 2:
                        raise ValueError("هر نقطه ماسک باید دقیقاً دو مختصات x,y داشته باشد")
                    points.append(coords)
            clip.mask_points = points
            clip.validate()
        except (KeyError, ValueError) as exc:
            if self._undo_stack:
                self._undo_stack.pop()
            self._update_history_buttons()
            self.statusBar().showMessage(str(exc))
            return
        self.timeline_widget.refresh()
        self._sync_transform_controls()
        self.statusBar().showMessage(
            "Chroma Key / Mask ذخیره شد؛ در رندر نهایی اعمال می‌شود، نه پیش‌نمایش زنده."
        )

    def _parse_mask_points(self) -> list[list[float]]:
        points = []
        for raw_point in self.mask_points_edit.text().split(";"):
            if raw_point.strip():
                coords = [float(value.strip()) for value in raw_point.split(",")]
                if len(coords) != 2:
                    raise ValueError("هر نقطه ماسک باید دقیقاً دو مختصات x,y داشته باشد")
                points.append(coords)
        if not 3 <= len(points) <= 8:
            raise ValueError("ماسک چندضلعی باید ۳ تا ۸ رأس داشته باشد")
        return points

    def _add_mask_keyframe(self) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        try:
            clip = self.timeline_project.get_clip(clip_id)
            frame = self.mask_keyframe_frame_spin.value()
            if frame >= clip.duration_frames:
                raise ValueError("فریم Keyframe باید داخل محدوده کلیپ باشد")
            self._push_undo()
            key = {
                "frame": frame,
                "x": self.mask_controls["mask_x"].value(),
                "y": self.mask_controls["mask_y"].value(),
                "width": self.mask_controls["mask_width"].value(),
                "height": self.mask_controls["mask_height"].value(),
                "rotation": self.mask_rotation_spin.value(),
                "points": self._parse_mask_points() if clip.mask_shape == "polygon" else clip.mask_points,
                "ease": "linear",
            }
            keys = [dict(item) for item in clip.mask_keyframes if int(item["frame"]) != frame]
            keys.append(key)
            clip.mask_keyframes = sorted(keys, key=lambda item: int(item["frame"]))
            clip.validate()
        except (KeyError, ValueError) as exc:
            if self._undo_stack:
                self._undo_stack.pop()
            self._update_history_buttons()
            self.statusBar().showMessage(f"Mask Keyframe ثبت نشد: {exc}")
            return
        self.timeline_widget.refresh()
        self._sync_transform_controls()
        self.statusBar().showMessage(f"Mask Keyframe در فریم {frame} ثبت شد؛ حرکت در رندر نهایی اعمال می‌شود.")

    def _delete_mask_keyframe(self) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        clip = self.timeline_project.get_clip(clip_id)
        frame = self.mask_keyframe_frame_spin.value()
        if not any(int(item["frame"]) == frame for item in clip.mask_keyframes):
            self.statusBar().showMessage("در این فریم Mask Keyframe وجود ندارد.")
            return
        self._push_undo()
        clip.mask_keyframes = [dict(item) for item in clip.mask_keyframes if int(item["frame"]) != frame]
        clip.validate()
        self.timeline_widget.refresh()
        self._sync_transform_controls()
        self.statusBar().showMessage(f"Mask Keyframe فریم {frame} حذف شد.")


    def _sync_mask_overlay(self, clip=None, local_frame: int | None = None) -> None:
        if clip is None:
            clip_id = self.timeline_widget.canvas.selected_clip_id
            try:
                clip = self.timeline_project.get_clip(clip_id) if clip_id else None
            except KeyError:
                clip = None
        if not clip or clip.media_type != "video" or not clip.track.startswith("V"):
            self.mask_overlay.set_mask([], self.timeline_project.width, self.timeline_project.height, False)
            return
        frame = (max(0, min(clip.duration_frames - 1,
                            self.timeline_project.playhead_frame - clip.start_frame))
                 if local_frame is None else int(local_frame))
        key = next((item for item in clip.mask_keyframes if int(item["frame"]) == frame), None)
        values = mask_values_at(clip.mask_keyframes, frame, {
            "x": clip.mask_x, "y": clip.mask_y,
            "width": clip.mask_width, "height": clip.mask_height,
            "rotation": clip.mask_rotation,
        })
        points = mask_points_at(clip.mask_keyframes, frame, clip.mask_points)
        bx, by = float(clip.mask_x), float(clip.mask_y)
        bw, bh = max(1e-9, float(clip.mask_width)), max(1e-9, float(clip.mask_height))
        x, y = float(values["x"]), float(values["y"])
        width, height = float(values["width"]), float(values["height"])
        display_points = [
            [x + ((float(px) - bx) / bw) * width,
             y + ((float(py) - by) / bh) * height]
            for px, py in points
        ]
        editable = bool(clip.mask_enabled and key is not None)
        self.mask_overlay.set_mask(
            display_points, self.timeline_project.width,
            self.timeline_project.height, bool(clip.mask_enabled),
            shape=clip.mask_shape, rect=[x, y, width, height],
            geometry_editable=editable, rotation=float(values["rotation"]),
            feather=float(clip.mask_feather_px)
        )
        self.mask_overlay.setGeometry(self.video_widget.rect())
        self.mask_overlay.raise_()
        self._mask_overlay_mapping = {
            "base": (bx, by, bw, bh), "current": (x, y, width, height)
        }

    def eventFilter(self, watched, event):
        if watched is getattr(self, "video_widget", None) and event.type() == QEvent.Type.Resize:
            if hasattr(self, "mask_overlay"):
                self.mask_overlay.setGeometry(self.video_widget.rect())
                self.mask_overlay.raise_()
        return super().eventFilter(watched, event)

    def _mask_overlay_edit_started(self) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        clip = self.timeline_project.get_clip(clip_id)
        frame = self.timeline_project.playhead_frame - clip.start_frame
        if clip.mask_enabled and (
            any(int(key["frame"]) == frame for key in clip.mask_keyframes)
            or clip.mask_shape in {"rectangle", "ellipse"}
        ):
            self._push_undo()

    def _mask_geometry_changed(self, rect) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        try:
            clip = self.timeline_project.get_clip(clip_id)
            frame = self.timeline_project.playhead_frame - clip.start_frame
            key = next((item for item in clip.mask_keyframes if int(item["frame"]) == frame), None)
            if key is None or not clip.mask_enabled or clip.mask_shape == "polygon":
                return
            x, y, width, height = [float(value) for value in rect]
            key.update({"x": x, "y": y, "width": width, "height": height})
            clip.validate()
            for name, value in (("x", x), ("y", y), ("width", width), ("height", height)):
                control = self.mask_controls[f"mask_{name}"]
                blocker = QSignalBlocker(control)
                control.setValue(value)
                del blocker
            self.timeline_widget.refresh()
            self.statusBar().showMessage("محدوده ماسک تغییر کرد؛ کل حرکت با یک Undo برمی‌گردد.")
        except (KeyError, TypeError, ValueError) as exc:
            self.statusBar().showMessage(f"تغییر محدوده ماسک نامعتبر است: {exc}")

    def _mask_rotation_control_changed(self, rotation: float) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        try:
            clip = self.timeline_project.get_clip(clip_id)
            frame = max(0, min(clip.duration_frames - 1,
                               self.timeline_project.playhead_frame - clip.start_frame))
            self._push_undo()
            if clip.mask_keyframes:
                values = mask_values_at(clip.mask_keyframes, frame, {
                    "x": clip.mask_x, "y": clip.mask_y,
                    "width": clip.mask_width, "height": clip.mask_height,
                    "rotation": clip.mask_rotation,
                })
                key = next((item for item in clip.mask_keyframes
                            if int(item["frame"]) == frame), None)
                if key is None:
                    key = {"frame": frame, **values, "ease": "linear"}
                    if clip.mask_shape == "polygon":
                        key["points"] = mask_points_at(clip.mask_keyframes, frame, clip.mask_points)
                key["rotation"] = float(rotation)
                keys = [dict(item) for item in clip.mask_keyframes
                        if int(item["frame"]) != frame]
                keys.append(key)
                clip.mask_keyframes = sorted(keys, key=lambda item: int(item["frame"]))
            else:
                clip.mask_rotation = float(rotation)
            clip.validate()
            self.timeline_widget.refresh()
            self._sync_transform_controls()
            self.statusBar().showMessage("چرخش ماسک ثبت شد؛ در رندر نهایی اعمال می‌شود.")
        except (KeyError, TypeError, ValueError) as exc:
            if self._undo_stack:
                self._undo_stack.pop()
            self._update_history_buttons()
            self.statusBar().showMessage(f"چرخش ماسک ثبت نشد: {exc}")

    def _mask_feather_changed(self, feather: float) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        try:
            clip = self.timeline_project.get_clip(clip_id)
            if not clip.mask_enabled or clip.mask_shape == "polygon":
                return
            clip.mask_feather_px = max(0.0, min(40.0, float(feather)))
            clip.validate()
            blocker = QSignalBlocker(self.mask_feather_spin)
            self.mask_feather_spin.setValue(clip.mask_feather_px)
            del blocker
            self.timeline_widget.refresh()
        except (KeyError, TypeError, ValueError) as exc:
            self.statusBar().showMessage(f"تنظیم Feather ماسک نامعتبر است: {exc}")

    def _mask_rotation_changed(self, rotation: float) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        try:
            clip = self.timeline_project.get_clip(clip_id)
            frame = self.timeline_project.playhead_frame - clip.start_frame
            key = next((item for item in clip.mask_keyframes if int(item["frame"]) == frame), None)
            if key is None or not clip.mask_enabled:
                return
            key["rotation"] = float(rotation)
            clip.validate()
            blocker = QSignalBlocker(self.mask_rotation_spin)
            self.mask_rotation_spin.setValue(float(rotation))
            del blocker
            self.timeline_widget.refresh()
        except (KeyError, TypeError, ValueError) as exc:
            self.statusBar().showMessage(f"چرخش ماسک نامعتبر است: {exc}")

    def _polygon_mask_points_changed(self, points) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        clip = self.timeline_project.get_clip(clip_id)
        frame = self.timeline_project.playhead_frame - clip.start_frame
        key = next((item for item in clip.mask_keyframes if int(item["frame"]) == frame), None)
        if key is None or clip.mask_shape != "polygon" or not clip.mask_enabled:
            return
        try:
            bx, by, bw, bh = self._mask_overlay_mapping["base"]
            x, y, width, height = self._mask_overlay_mapping["current"]
            if width <= 1e-9 or height <= 1e-9:
                return
            key["points"] = [[
                max(0.0, min(1.0, bx + ((float(px) - x) / width) * bw)),
                max(0.0, min(1.0, by + ((float(py) - y) / height) * bh)),
            ] for px, py in points]
            clip.validate()
            blocker = QSignalBlocker(self.mask_points_edit)
            self.mask_points_edit.setText("; ".join(
                f"{px:.3f},{py:.3f}" for px, py in key["points"]
            ))
            del blocker
            # Keep the overlay's active drag handle alive; the widget already
            # updates its own lightweight point list during this mouse gesture.
        except (TypeError, ValueError, KeyError) as exc:
            self.statusBar().showMessage(f"ویرایش رأس ماسک نامعتبر است: {exc}")

    def _sync_transform_controls(self) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        clip = None
        if clip_id:
            try:
                clip = self.timeline_project.get_clip(clip_id)
            except KeyError:
                pass
        enabled = bool(clip and clip.media_type == "video" and clip.track.startswith("V"))
        self.add_transform_keyframe_button.setEnabled(enabled)
        self.add_mask_keyframe_button.setEnabled(enabled)
        self.delete_mask_keyframe_button.setEnabled(enabled)
        self.mask_keyframe_frame_spin.setEnabled(enabled)
        self.blend_mode_combo.setEnabled(enabled)
        effect_controls = [
            self.chroma_key_checkbox, self.chroma_key_color_edit,
            self.chroma_key_similarity_spin, self.chroma_key_blend_spin,
            self.mask_checkbox, self.mask_invert_checkbox, *self.mask_controls.values(),
            self.mask_shape_combo, self.mask_feather_spin, self.mask_points_edit,
        ]
        for control in effect_controls:
            control.setEnabled(enabled)
        if enabled:
            blocker = QSignalBlocker(self.chroma_key_checkbox)
            self.chroma_key_checkbox.setChecked(bool(clip.chroma_key_enabled))
            del blocker
            blocker = QSignalBlocker(self.chroma_key_color_edit)
            self.chroma_key_color_edit.setText(str(clip.chroma_key_color))
            del blocker
            for control, value in (
                (self.chroma_key_similarity_spin, clip.chroma_key_similarity),
                (self.chroma_key_blend_spin, clip.chroma_key_blend),
            ):
                blocker = QSignalBlocker(control)
                control.setValue(float(value))
                del blocker
            blocker = QSignalBlocker(self.mask_checkbox)
            self.mask_checkbox.setChecked(bool(clip.mask_enabled))
            del blocker
            local_frame = max(0, min(clip.duration_frames - 1,
                self.timeline_project.playhead_frame - clip.start_frame))
            mask_values = mask_values_at(
                clip.mask_keyframes, local_frame,
                {"x": clip.mask_x, "y": clip.mask_y,
                 "width": clip.mask_width, "height": clip.mask_height,
                 "rotation": clip.mask_rotation},
            )
            for key, control in self.mask_controls.items():
                blocker = QSignalBlocker(control)
                control.setValue(float(mask_values[key.removeprefix("mask_")]))
                del blocker
            blocker = QSignalBlocker(self.mask_invert_checkbox)
            self.mask_invert_checkbox.setChecked(bool(clip.mask_invert))
            del blocker
            blocker = QSignalBlocker(self.mask_shape_combo)
            shape_index = self.mask_shape_combo.findData(str(clip.mask_shape))
            self.mask_shape_combo.setCurrentIndex(max(0, shape_index))
            del blocker
            blocker = QSignalBlocker(self.mask_rotation_spin)
            self.mask_rotation_spin.setValue(float(mask_values["rotation"]))
            del blocker
            blocker = QSignalBlocker(self.mask_feather_spin)
            self.mask_feather_spin.setValue(float(clip.mask_feather_px))
            del blocker
            blocker = QSignalBlocker(self.mask_points_edit)
            self.mask_points_edit.setText("; ".join(
                f"{float(point[0]):.3f},{float(point[1]):.3f}" for point in clip.mask_points
            ))
            del blocker
            local_frame = max(0, min(clip.duration_frames - 1,
                self.timeline_project.playhead_frame - clip.start_frame))
            blocker = QSignalBlocker(self.mask_keyframe_frame_spin)
            self.mask_keyframe_frame_spin.setValue(local_frame)
            del blocker
            key_frames = [int(key["frame"]) for key in clip.mask_keyframes]
            self.mask_keyframes_label.setText(
                "Mask Keyframes: " + (", ".join(str(frame) for frame in key_frames) if key_frames else "—")
            )
            self.delete_mask_keyframe_button.setEnabled(enabled and local_frame in key_frames)
        else:
            self.mask_keyframes_label.setText("Mask Keyframes: —")
        if enabled:
            blend_index = self.blend_mode_combo.findData(str(getattr(clip, "blend_mode", "normal")))
            if blend_index >= 0:
                blocker = QSignalBlocker(self.blend_mode_combo)
                self.blend_mode_combo.setCurrentIndex(blend_index)
                del blocker
        selected_frame = self.timeline_widget.canvas.selected_transform_keyframe_frame
        self.delete_transform_keyframe_button.setEnabled(bool(enabled and selected_frame is not None and any(int(item['frame']) == selected_frame for item in clip.transform_keyframes)))
        self.playback_speed_combo.setEnabled(enabled)
        self.apply_speed_button.setEnabled(enabled)
        self.motion_blur_checkbox.setEnabled(enabled)
        self.reverse_checkbox.setEnabled(enabled)
        self.speed_ramp_frame_spin.setEnabled(enabled)
        self.speed_ramp_rate_spin.setEnabled(enabled)
        self.add_speed_ramp_button.setEnabled(enabled)
        self.clear_speed_ramp_button.setEnabled(enabled and bool(clip.speed_ramp) if enabled else False)
        self.speed_ramp_preview_button.setEnabled(enabled and bool(clip.speed_ramp) if enabled else False)
        if enabled:
            local_frame_for_ramp = max(0, min(clip.duration_frames - 1,
                self.timeline_project.playhead_frame - clip.start_frame))
            self.speed_ramp_frame_spin.setMaximum(max(0, clip.duration_frames - 1))
            self.speed_ramp_frame_spin.setValue(local_frame_for_ramp)
            ramp_points = sorted(clip.speed_ramp, key=lambda point: int(point["frame"]))
            self.speed_ramp_label.setText(
                "Speed Ramp: " + (" | ".join(
                    f'{int(point["frame"])}f → {float(point["rate"]):.2f}x'
                    for point in ramp_points
                ) if ramp_points else "هنوز نقطه‌ای ثبت نشده")
            )
        else:
            self.speed_ramp_label.setText("Speed Ramp: —")
        if enabled:
            blocker = QSignalBlocker(self.reverse_checkbox)
            self.reverse_checkbox.setChecked(bool(getattr(clip, "reverse_playback", False)))
            del blocker
            blocker = QSignalBlocker(self.motion_blur_checkbox)
            self.motion_blur_checkbox.setChecked(bool(getattr(clip, "motion_blur", False)))
            del blocker
        if enabled:
            index = self.playback_speed_combo.findData(float(getattr(clip, "playback_rate", 1.0)))
            if index >= 0:
                blocker = QSignalBlocker(self.playback_speed_combo)
                self.playback_speed_combo.setCurrentIndex(index)
                del blocker
        for control in self.transform_controls.values():
            control.setEnabled(enabled)
        for control in self.bezier_controls.values():
            control.setEnabled(enabled)
        if not enabled:
            self.bezier_curve_widget.setVisible(False)
            self.transform_keyframes_label.setText("Keyframe: —")
            self._sync_mask_overlay(None)
            return
        local_frame = max(0, min(clip.duration_frames - 1,
                                 self.timeline_project.playhead_frame - clip.start_frame))
        keys = sorted(clip.transform_keyframes, key=lambda item: int(item["frame"]))
        defaults = {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}
        before = max((key for key in keys if int(key["frame"]) <= local_frame),
                     key=lambda item: int(item["frame"]), default=None)
        after = min((key for key in keys if int(key["frame"]) > local_frame),
                    key=lambda item: int(item["frame"]), default=None)
        if before and after:
            span = int(after["frame"]) - int(before["frame"])
            ratio = transform_eased_progress(before, (local_frame - int(before["frame"])) / max(1, span))
            values = {key: float(before.get(key, defaults[key])) +
                      (float(after.get(key, defaults[key])) - float(before.get(key, defaults[key]))) * ratio
                      for key in defaults}
        elif before:
            values = {key: float(before.get(key, defaults[key])) for key in defaults}
        elif after:
            values = {key: float(after.get(key, defaults[key])) for key in defaults}
        else:
            values = defaults
        for key, control in self.transform_controls.items():
            blocker = QSignalBlocker(control)
            control.setValue(values[key])
            del blocker
        for key, control in self.anchor_controls.items():
            blocker = QSignalBlocker(control)
            control.setValue(float(getattr(clip, key, 0.5)))
            del blocker
        active_key = before or after
        if active_key:
            index = self.transform_easing_combo.findData(active_key.get("ease", "linear"))
            if index >= 0:
                blocker = QSignalBlocker(self.transform_easing_combo)
                self.transform_easing_combo.setCurrentIndex(index)
                del blocker
            for key, control in self.bezier_controls.items():
                blocker = QSignalBlocker(control)
                control.setValue(float(active_key.get(key, 0.0 if key.endswith("y1") else 1.0)))
                del blocker
        self.bezier_curve_widget.set_values(
            float((before or {}).get("bezier_y1", 0.0)),
            float((before or {}).get("bezier_y2", 1.0)),
        )
        self._sync_bezier_graph_visibility()
        selected_frame = self.timeline_widget.canvas.selected_transform_keyframe_frame
        selected_text = f" | انتخاب: {selected_frame}f" if selected_frame is not None else ""
        self.transform_keyframes_label.setText(
            f"{len(clip.transform_keyframes)} Keyframe | فریم فعلی کلیپ: {local_frame}{selected_text}"
        )
        self._sync_mask_overlay(clip, local_frame)


    def _delete_transform_keyframe(self) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        frame = self.timeline_widget.canvas.selected_transform_keyframe_frame
        if not clip_id or frame is None:
            return
        clip = self.timeline_project.get_clip(clip_id)
        updated = [dict(item) for item in clip.transform_keyframes if int(item["frame"]) != int(frame)]
        if len(updated) == len(clip.transform_keyframes):
            return
        self._push_undo()
        self.timeline_project.set_clip_transform_keyframes(clip_id, updated)
        self.timeline_widget.canvas.selected_transform_keyframe_frame = None
        self._sync_transform_controls()
        self.timeline_widget.refresh()
        self.statusBar().showMessage("Keyframe حذف شد؛ با Undo قابل بازگشت است.")

    def _add_transform_keyframe(self) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            return
        clip = self.timeline_project.get_clip(clip_id)
        local_frame = self.timeline_project.playhead_frame - clip.start_frame
        if not 0 <= local_frame < clip.duration_frames:
            self.statusBar().showMessage("Playhead باید داخل کلیپ انتخاب‌شده باشد.")
            return
        self._push_undo()
        keys = [dict(item) for item in clip.transform_keyframes if int(item["frame"]) != local_frame]
        clip.anchor_x = self.anchor_controls["anchor_x"].value()
        clip.anchor_y = self.anchor_controls["anchor_y"].value()
        keys.append({
            "frame": local_frame,
            **{key: control.value() for key, control in self.transform_controls.items()},
            "ease": self.transform_easing_combo.currentData() or "linear",
            **{key: control.value() for key, control in self.bezier_controls.items()},
        })
        keys.sort(key=lambda item: int(item["frame"]))
        try:
            self.timeline_project.set_clip_transform_keyframes(clip_id, keys)
        except (KeyError, ValueError) as exc:
            self.statusBar().showMessage(f"ثبت Keyframe انجام نشد: {exc}")
            return
        self._sync_transform_controls()
        self.statusBar().showMessage("Keyframe ثبت شد؛ منحنی حرکتی انتخاب‌شده در خروجی MP4 اعمال می‌شود.")

    def _sync_color_controls(self) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        clip = None
        if clip_id:
            try:
                clip = self.timeline_project.get_clip(clip_id)
            except KeyError:
                pass
        enabled = bool(clip and clip.media_type == "video")
        if self._scope_clip_id != clip_id:
            self.rgb_histogram_widget.set_histogram(None)
            self.waveform_widget.set_data(None)
            self.rgb_parade_widget.set_data(None)
            self.vectorscope_widget.set_data(None)
            self._scope_clip_id = clip_id
        self.color_preview_button.setEnabled(enabled)
        self.color_wheel_reset_button.setEnabled(enabled)
        for wheel in self.color_wheels.values():
            wheel.setEnabled(enabled)
        scope_ready = bool(enabled and not self._scope_tasks)
        self.rgb_histogram_button.setEnabled(scope_ready)
        self.waveform_button.setEnabled(scope_ready)
        self.rgb_parade_button.setEnabled(scope_ready)
        self.vectorscope_button.setEnabled(scope_ready)
        for slider, label, scale in self.color_controls.values():
            slider.setEnabled(enabled)
            if not enabled:
                label.setText(label.text().split(":")[0] + ": —")
        if not enabled:
            return
        blockers = [QSignalBlocker(slider) for slider, _, _ in self.color_controls.values()]
        for key, (slider, label, scale) in self.color_controls.items():
            value = float(clip.color_grade.get(key, 0.0 if key in {"exposure", "temperature", "tint", "highlights", "shadows", "whites", "blacks"} else 1.0))
            slider.setValue(round(value / scale))
            label.setText(f"{key.title()}: {value:.2f}")
        del blockers
        for zone in ("shadows", "midtones", "highlights"):
            rgb = [float(clip.color_grade.get(f"wheel_{zone}_{channel}", 0.0)) for channel in ("r", "g", "b")]
            self.color_wheels[zone].set_values(*rgb_to_wheel(*rgb))

    def analyze_rgb_histogram(self) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            self.statusBar().showMessage("ابتدا یک کلیپ ویدیویی انتخاب کن")
            return
        try:
            clip = self.timeline_project.get_clip(clip_id)
        except KeyError:
            return
        if clip.media_type != "video" or not clip.track.startswith("V"):
            self.statusBar().showMessage("هیستوگرام فقط برای کلیپ ویدیویی قابل محاسبه است")
            return
        if not Path(clip.path).is_file():
            self.statusBar().showMessage("فایل اصلی کلیپ پیدا نشد")
            return
        if self._scope_tasks:
            self.statusBar().showMessage("یک تحلیل Scope در حال انجام است؛ برای جلوگیری از صف پردازشی صبر کن")
            return
        timestamp = clip.source_in / max(1, self.timeline_project.fps)
        task = RGBHistogramTask(clip_id, clip.path, timestamp, dict(clip.color_grade))
        task.signals.finished.connect(lambda cid, data, error: self._video_scope_finished(cid, "histogram", data, error))
        self._scope_tasks.append(task)
        self._set_scope_buttons_enabled(False)
        self.statusBar().showMessage("در حال نمونه‌برداری یک فریم ۲۵۶×۱۴۴ برای هیستوگرام RGB...")
        self._scope_pool.start(task)

    def analyze_video_scope(self, scope_kind: str) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        if not clip_id:
            self.statusBar().showMessage("ابتدا یک کلیپ ویدیویی انتخاب کن")
            return
        try:
            clip = self.timeline_project.get_clip(clip_id)
        except KeyError:
            return
        if clip.media_type != "video" or not clip.track.startswith("V"):
            self.statusBar().showMessage("این Scope فقط برای کلیپ ویدیویی قابل محاسبه است")
            return
        if not Path(clip.path).is_file():
            self.statusBar().showMessage("فایل اصلی کلیپ پیدا نشد")
            return
        if self._scope_tasks:
            self.statusBar().showMessage("یک تحلیل Scope در حال انجام است؛ برای جلوگیری از صف پردازشی صبر کن")
            return
        timestamp = clip.source_in / max(1, self.timeline_project.fps)
        task = RGBHistogramTask(clip_id, clip.path, timestamp, dict(clip.color_grade), scope_kind)
        task.signals.finished.connect(lambda cid, data, error: self._video_scope_finished(cid, scope_kind, data, error))
        self._scope_tasks.append(task)
        self._set_scope_buttons_enabled(False)
        self.statusBar().showMessage(f"در حال محاسبه {scope_kind} از یک فریم کوچک در پس‌زمینه...")
        self._scope_pool.start(task)

    def _set_scope_buttons_enabled(self, enabled: bool) -> None:
        clip_id = self.timeline_widget.canvas.selected_clip_id
        try:
            clip = self.timeline_project.get_clip(clip_id) if clip_id else None
        except KeyError:
            clip = None
        ready = bool(enabled and not self._scope_tasks and clip and clip.media_type == "video")
        self.rgb_histogram_button.setEnabled(ready)
        self.waveform_button.setEnabled(ready)
        self.rgb_parade_button.setEnabled(ready)
        self.vectorscope_button.setEnabled(ready)

    def _video_scope_finished(self, clip_id: str, scope_kind: str, data: object, error: str) -> None:
        self._scope_tasks = [task for task in self._scope_tasks if task.clip_id != clip_id]
        self._set_scope_buttons_enabled(True)
        if self.timeline_widget.canvas.selected_clip_id != clip_id:
            return
        if data is None:
            self.statusBar().showMessage(f"محاسبه {scope_kind} ناموفق بود: {error}")
            return
        if scope_kind == "waveform":
            self.waveform_widget.set_data(data)
        elif scope_kind == "parade":
            self.rgb_parade_widget.set_data(data)
        elif scope_kind == "vectorscope":
            self.vectorscope_widget.set_data(data)
        else:
            self.rgb_histogram_widget.set_histogram(data)
        self._scope_clip_id = clip_id
        self.statusBar().showMessage(f"{scope_kind} فریم نمونه با Grade فعلی محاسبه شد؛ تصویر اصلی تغییر نکرد.")

    def _color_wheel_changed(self, zone: str, x: float, y: float) -> None:
        red, green, blue = wheel_to_rgb(x, y)
        for channel, value in zip(("r", "g", "b"), (red, green, blue)):
            slider, _, scale = self.color_controls[f"wheel_{zone}_{channel}"]
            blocker = QSignalBlocker(slider)
            slider.setValue(round(value / scale))
            del blocker
        self._color_controls_changed()

    def _reset_color_wheels(self) -> None:
        self._push_undo()
        for wheel in self.color_wheels.values():
            wheel.set_values(0.0, 0.0)
        for zone in ("shadows", "midtones", "highlights"):
            for channel in ("r", "g", "b"):
                slider, _, _ = self.color_controls[f"wheel_{zone}_{channel}"]
                blocker = QSignalBlocker(slider)
                slider.setValue(0)
                del blocker
        self._color_controls_changed()

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
        self._sync_transform_controls()
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

    def _project_snapshot(self) -> str:
        """Return a stable snapshot of user-authored project state.

        Probe metadata and generated proxy paths are intentionally excluded:
        they are derived/cache data and must not trigger unsaved-change prompts.
        """
        media = [
            {"path": str(item.get("path", "")), "name": str(item.get("name", ""))}
            for item in self.media_items
        ]
        payload = {
            "media": media,
            "timeline_project": self.timeline_project.to_dict(),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _has_unsaved_changes(self) -> bool:
        return self._project_snapshot() != self._saved_project_snapshot

    def _confirm_project_switch(self, action: str) -> bool:
        if not self._has_unsaved_changes():
            return True
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("تغییرات ذخیره‌نشده")
        dialog.setText(f"پروژه تغییرات ذخیره‌نشده دارد. پیش از {action} چه کاری انجام شود؟")
        save_button = dialog.addButton("ذخیره", QMessageBox.AcceptRole)
        discard_button = dialog.addButton("صرف‌نظر از تغییرات", QMessageBox.DestructiveRole)
        cancel_button = dialog.addButton("انصراف", QMessageBox.RejectRole)
        dialog.setDefaultButton(save_button)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is discard_button:
            return True
        if clicked is not save_button:
            return False
        self.save_project()
        return not self._has_unsaved_changes()

    def closeEvent(self, event) -> None:
        if self._confirm_project_switch("بستن برنامه"):
            clear_recovery(self._recovery_path)
            event.accept()
        else:
            event.ignore()

    def new_project(self) -> None:
        if not self._confirm_project_switch("ساخت پروژه جدید"):
            return
        clear_recovery(self._recovery_path)
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
        self._saved_project_snapshot = self._project_snapshot()
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
                "missing_path": False, "proxy_path": None,
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
                item["missing_path"] = False
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
                item["probe_state"] = "missing" if not Path(path).is_file() else "failed"
                item["missing_path"] = not Path(path).is_file()
                item["probe_error"] = error
                label = "فایل گمشده — اتصال مجدد لازم است" if item["missing_path"] else "خطا در خواندن مشخصات"
                self.media_list.item(index).setText(item["name"] + "  •  " + label)
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
            self._saved_project_snapshot = self._project_snapshot()
            clear_recovery(self._recovery_path)
            self.statusBar().showMessage(f"پروژه ذخیره شد: {self.project_path.name}")
        except (OSError, TypeError, ValueError) as exc:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            QMessageBox.critical(self, "خطای ذخیره", str(exc))

    def _prepare_project_data(self, data: dict[str, Any]) -> tuple[TimelineProject, list[dict[str, Any]]]:
        """Validate project structure and prepare media records before changing live state."""
        media = data.get("media", [])
        if not isinstance(media, list):
            raise ValueError("فهرست رسانه‌های پروژه معتبر نیست")
        timeline_data = data.get("timeline_project", data)
        if not isinstance(timeline_data, dict):
            raise ValueError("ساختار تایم‌لاین پروژه معتبر نیست")
        loaded_timeline = TimelineProject.from_dict(timeline_data)
        loaded_media: list[dict[str, Any]] = []
        for item in media:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            path = str(item["path"])
            exists = Path(path).is_file()
            cached_metadata = item.get("metadata")
            metadata = cached_metadata if exists and isinstance(cached_metadata, dict) else None
            proxy_value = item.get("proxy_path")
            proxy_path = str(proxy_value) if proxy_value and Path(str(proxy_value)).is_file() else None
            loaded_media.append({
                "path": path,
                "name": str(item.get("name") or Path(path).name),
                "metadata": metadata,
                "probe_state": "missing" if not exists else ("ready" if metadata else "pending"),
                "missing_path": not exists,
                "proxy_path": proxy_path,
            })
        return loaded_timeline, loaded_media

    def _apply_project_data(self, data: dict[str, Any], project_path: Path | None,
                            recovered: bool = False) -> None:
        """Apply a validated project or recovery snapshot to the editor."""
        loaded_timeline, loaded_media = self._prepare_project_data(data)
        self.player.stop()
        self.player.setSource(QUrl())
        self.timeline_project = loaded_timeline
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._update_history_buttons()
        self.media_items = loaded_media
        self.waveforms = {}
        self.timeline_widget.set_waveforms(self.waveforms)
        self.project_path = project_path
        self.media_list.clear()
        for item in self.media_items:
            if item.get("missing_path"):
                self.media_list.addItem(item["name"] + "  •  فایل گمشده — اتصال مجدد لازم است")
                continue
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
        self._saved_project_snapshot = self._project_snapshot()
        for item in self.media_items:
            metadata = item.get("metadata") or {}
            if metadata.get("has_audio") and Path(item["path"]).is_file():
                self._start_waveform(item["path"])
        self._set_playhead(self.timeline_project.playhead_frame)
        if recovered:
            self.statusBar().showMessage("نسخه بازیابی‌شده بارگذاری شد؛ فایل اصلی پروژه بازنویسی نشده است.")
        elif self.project_path:
            self.statusBar().showMessage(f"پروژه باز شد: {self.project_path.name}")
        else:
            self.statusBar().showMessage("پروژه بازیابی شد؛ برای ذخیره دائمی از ذخیره پروژه استفاده کنید.")

    def _autosave_recovery(self) -> None:
        """Write a recovery snapshot only when authored project state is dirty."""
        if not self._has_unsaved_changes():
            return
        try:
            write_recovery(
                self._recovery_path,
                self._project_data(),
                str(self.project_path) if self.project_path else None,
            )
            self.statusBar().showMessage("بازیابی خودکار پروژه به‌روز شد", 4000)
        except (OSError, TypeError, ValueError) as exc:
            self.statusBar().showMessage(f"ذخیره بازیابی خودکار ناموفق بود: {exc}", 8000)

    def _check_recovery(self) -> None:
        """Offer a previous crash snapshot without ever overwriting its source project."""
        payload = read_recovery(self._recovery_path)
        if payload is None:
            return
        answer = QMessageBox.question(
            self,
            "بازیابی جلسه قبلی",
            "یک نسخه بازیابی از جلسه قبلی ZENITH پیدا شد. آیا می‌خواهید آن را بازیابی کنید؟\n\n"
            "فایل اصلی پروژه بازنویسی نخواهد شد.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            clear_recovery(self._recovery_path)
            return
        try:
            project_data = payload["project_data"]
            project_path_value = payload.get("project_path")
            original_path = Path(project_path_value) if project_path_value else None
            self._apply_project_data(project_data, original_path, recovered=True)
            # A recovery snapshot is not the same as a saved project file.
            # Keep it available until the user explicitly saves or discards it.
            self._saved_project_snapshot = ""
        except (OSError, ValueError, TypeError, KeyError) as exc:
            QMessageBox.warning(self, "بازیابی ناموفق بود", f"نسخه بازیابی بارگذاری نشد؛ فایل بازیابی حفظ شد.\n{exc}")

    def relink_selected_media(self) -> None:
        row = self.media_list.currentRow()
        if row < 0 or row >= len(self.media_items):
            self.statusBar().showMessage("ابتدا فایل گمشده را از فهرست رسانه‌ها انتخاب کنید")
            return
        item = self.media_items[row]
        if not item.get("missing_path") and Path(item["path"]).is_file():
            self.statusBar().showMessage("فایل انتخاب‌شده گمشده نیست")
            return
        replacement, _ = QFileDialog.getOpenFileName(
            self, "اتصال مجدد رسانه", "", MEDIA_FILTER
        )
        if not replacement:
            return
        new_path = str(Path(replacement).resolve())
        replacement_suffix = Path(new_path).suffix.lower()
        linked_clips = [clip for clip in self.timeline_project.clips if clip.path == item["path"]]
        if any(clip.media_type == "audio" for clip in linked_clips) and replacement_suffix not in AUDIO_EXTENSIONS:
            QMessageBox.warning(self, "نوع رسانه ناسازگار", "برای این رسانه صوتی، یک فایل صوتی سازگار انتخاب کنید.")
            return
        if any(clip.media_type == "video" for clip in linked_clips) and replacement_suffix in AUDIO_EXTENSIONS:
            QMessageBox.warning(self, "نوع رسانه ناسازگار", "برای این کلیپ تصویری، یک فایل تصویری یا ویدیویی انتخاب کنید.")
            return
        if any(other is not item and other.get("path") == new_path for other in self.media_items):
            QMessageBox.warning(self, "اتصال مجدد", "این فایل از قبل در فهرست رسانه‌های پروژه وجود دارد.")
            return
        old_path = item["path"]
        item["path"] = new_path
        item["name"] = Path(new_path).name
        item["metadata"] = None
        item["probe_state"] = "pending"
        item["missing_path"] = False
        item["proxy_path"] = None
        for clip in self.timeline_project.clips:
            if clip.path == old_path:
                clip.path = new_path
                clip.name = item["name"]
        self.media_list.item(row).setText(item["name"] + "  •  در حال بررسی")
        self._refresh_timeline()
        task = MediaProbeTask(new_path)
        task.signals.finished.connect(self._media_probe_finished)
        self._probe_tasks.append(task)
        self._probe_pool.start(task)
        self.statusBar().showMessage(f"مسیر رسانه اصلاح شد: {item['name']}")

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
            self._prepare_project_data(data)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            QMessageBox.critical(self, "خطای باز کردن", f"پروژه بارگذاری نشد؛ پروژه فعلی حفظ شد.\n{exc}")
            return
        if not self._confirm_project_switch("باز کردن پروژه دیگر"):
            return
        clear_recovery(self._recovery_path)
        try:
            self._apply_project_data(data, Path(filename))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            QMessageBox.critical(self, "خطای باز کردن", f"پروژه بارگذاری نشد؛ پروژه فعلی حفظ شد.\n{exc}")


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    window = ZenithEditor()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
