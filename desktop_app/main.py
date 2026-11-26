from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QMessageBox,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QSplitter, QFrame, QStatusBar
)

APP_NAME = "ZENITH Desktop"
PROJECT_VERSION = 1
MEDIA_FILTER = "Media files (*.mp4 *.mov *.mkv *.avi *.webm *.mp3 *.wav *.m4a *.aac *.png *.jpg *.jpeg);;All files (*.*)"


class ZenithEditor(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project_path: Path | None = None
        self.media_items: list[dict[str, Any]] = []
        self.timeline_items: list[dict[str, Any]] = []
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
        self.preview = QFrame()
        self.preview.setObjectName("preview")
        preview_inner = QVBoxLayout(self.preview)
        preview_label = QLabel("پیش‌نمایش پروژه")
        preview_label.setObjectName("preview_title")
        preview_hint = QLabel("پس از انتخاب کلیپ، پیش‌نمایش در این بخش نمایش داده می‌شود.")
        preview_hint.setAlignment(Qt.AlignCenter)
        preview_hint.setObjectName("muted")
        preview_inner.addStretch(1)
        preview_inner.addWidget(preview_label, alignment=Qt.AlignCenter)
        preview_inner.addWidget(preview_hint, alignment=Qt.AlignCenter)
        preview_inner.addStretch(1)
        preview_layout.addWidget(self.preview)

        inspector_panel = self._panel("تنظیمات کلیپ")
        inspector_layout = inspector_panel.layout()
        inspector_note = QLabel("انتخاب یک کلیپ از تایم‌لاین، تنظیمات آن را در این قسمت نمایش می‌دهد.")
        inspector_note.setWordWrap(True)
        inspector_note.setObjectName("muted")
        inspector_layout.addWidget(inspector_note)
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
            #preview { background:#08090A; border:1px solid #343434; border-radius:6px; }
            #preview_title { color:#D6AE55; font-size:15pt; font-weight:600; }
            #muted { color:#858585; }
            QListWidget { background:#101113; border:1px solid #303136; border-radius:5px; padding:5px; }
            QListWidget::item { padding:8px; border-bottom:1px solid #26272A; }
            QListWidget::item:selected { background:#393124; color:#F5D78F; }
            QPushButton { background:#28292D; color:#F2F2F2; border:1px solid #49433A; border-radius:5px; padding:8px 12px; }
            QPushButton:hover { background:#393124; border-color:#D6AE55; }
            QStatusBar { color:#B8B8B8; background:#191A1D; }
        """)

    def new_project(self) -> None:
        self.project_path = None
        self.media_items.clear()
        self.timeline_items.clear()
        self.media_list.clear()
        self.timeline_list.clear()
        self.statusBar().showMessage("پروژه جدید ایجاد شد")

    def import_media(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "انتخاب فایل‌های رسانه‌ای", "", MEDIA_FILTER)
        if not paths:
            return
        known = {item["path"] for item in self.media_items}
        for raw_path in paths:
            path = str(Path(raw_path).resolve())
            if path in known:
                continue
            record = {"path": path, "name": Path(path).name}
            self.media_items.append(record)
            self.media_list.addItem(QListWidgetItem(record["name"]))
            known.add(path)
        self.statusBar().showMessage(f"{len(paths)} فایل انتخاب شد")

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
            QMessageBox.critical(self, "خطای باز کردن پروژه", str(exc))


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    window = ZenithEditor()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
