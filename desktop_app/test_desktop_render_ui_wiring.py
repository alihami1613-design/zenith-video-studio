"""Regression checks for the desktop MP4 export UI wiring.

These AST-based checks run without importing Qt or opening a desktop window.
"""
import ast
from pathlib import Path
import unittest


MAIN_PATH = Path(__file__).resolve().parent / "main.py"


class DesktopRenderUIWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MAIN_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.editor = next(
            node for node in cls.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ZenithEditor"
        )
        cls.methods = {
            node.name: node
            for node in cls.editor.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def method_source(self, name):
        node = self.methods[name]
        return ast.get_source_segment(self.source, node)

    def test_export_controls_are_connected(self):
        init = self.method_source("__init__")
        build = self.method_source("_build_ui")
        self.assertIn("self.video_render_button.clicked.connect(self.export_video_mp4)", build)
        self.assertIn("self.video_render_cancel_button.clicked.connect(self.cancel_video_render)", build)
        self.assertIn("self.video_render_progress.setRange(0, 100)", build)
        self.assertIn("self.video_render_progress.setVisible(False)", build)
        self.assertIn("self.video_render_button.clicked.connect(self.export_video_mp4)", self.source)

    def test_render_worker_signals_are_connected_before_start(self):
        export = self.method_source("export_video_mp4")
        self.assertIn("task.signals.validation.connect(self._video_render_validation_ready)", export)
        self.assertIn("task.signals.progress.connect(self._video_render_progress_changed)", export)
        self.assertIn("task.signals.finished.connect(self._video_render_finished)", export)
        self.assertLess(export.index("task.signals.finished.connect"), export.index("self._video_render_pool.start(task)"))

    def test_cancel_requests_worker_cancellation(self):
        cancel = self.method_source("cancel_video_render")
        self.assertIn("self._video_render_task.cancel()", cancel)
        self.assertIn("self.video_render_cancel_button.setEnabled(False)", cancel)

    def test_validation_phase_disables_cancellation(self):
        progress = self.method_source("_video_render_progress_changed")
        self.assertIn('stage == "اعتبارسنجی و کنترل کیفیت"', progress)
        self.assertIn("self.video_render_cancel_button.setEnabled(not validating)", progress)

    def test_finish_handler_restores_controls_for_success_and_failure(self):
        finished = self.method_source("_video_render_finished")
        self.assertIn("self._video_render_task = None", finished)
        self.assertIn("self.video_render_button.setEnabled(True)", finished)
        self.assertIn("self.video_render_cancel_button.setEnabled(False)", finished)
        self.assertIn("if error:", finished)
        self.assertIn("self.video_render_progress.setValue(100)", finished)

    def test_render_task_cancel_event_is_thread_safe(self):
        task = next(
            node for node in self.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "VideoRenderTask"
        )
        methods = {
            node.name: node for node in task.body if isinstance(node, ast.FunctionDef)
        }
        cancel = ast.get_source_segment(self.source, methods["cancel"])
        run = ast.get_source_segment(self.source, methods["run"])
        self.assertIn("self.cancel_event.set()", cancel)
        self.assertIn("cancel_event=self.cancel_event", run)


if __name__ == "__main__":
    unittest.main()
