"""Static regression checks for transactional undo/redo wiring in the desktop editor."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


MAIN_PATH = Path(__file__).resolve().parent / "main.py"


class UndoHistoryWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MAIN_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(MAIN_PATH))
        cls.editor = next(
            node for node in cls.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ZenithEditor"
        )
        cls.methods = {
            node.name: node for node in cls.editor.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def method_source(self, name: str) -> str:
        return ast.get_source_segment(self.source, self.methods[name])

    def test_mask_and_chroma_key_edits_are_transactional(self):
        method = self.method_source("_clip_effects_changed")
        self.assertIn("history_before = self._history_snapshot()", method)
        self.assertIn("self._restore_history_snapshot(history_before)", method)
        self.assertIn("self._append_history_snapshot(self._undo_stack, history_before)", method)
        self.assertIn("self._redo_stack.clear()", method)

    def test_mask_rotation_is_transactional(self):
        method = self.method_source("_mask_rotation_control_changed")
        self.assertIn("history_before = self._history_snapshot()", method)
        self.assertIn("self._restore_history_snapshot(history_before)", method)
        self.assertIn("self._append_history_snapshot(self._undo_stack, history_before)", method)

    def test_blend_mode_is_transactional(self):
        method = self.method_source("_blend_mode_changed")
        self.assertIn("history_before = self._history_snapshot()", method)
        self.assertIn("self._restore_history_snapshot(history_before)", method)
        self.assertIn("self._append_history_snapshot(self._undo_stack, history_before)", method)
        self.assertIn("self._redo_stack.clear()", method)

    def test_timeline_drag_uses_one_press_snapshot(self):
        self.assertIn("self.timeline_widget.editStarted.connect(self._push_undo)", self.source)
        for name in ("_clip_trimmed", "_clip_moved"):
            method = self.method_source(name)
            self.assertNotIn("self._push_undo()", method)
            self.assertIn("TimelineWidget emits editStarted", method)

    def test_continuous_color_and_audio_sliders_snapshot_on_press(self):
        self.assertIn("slider.sliderPressed.connect(self._push_undo)", self.source)
        for name in ("volume_slider", "audio_pan_slider", "fade_in_slider", "fade_out_slider"):
            self.assertIn(f"self.{name}.sliderPressed.connect(self._push_undo)", self.source)

    def test_video_fade_and_transition_sliders_snapshot_on_press(self):
        for name in ("video_fade_in_slider", "video_fade_out_slider", "cross_dissolve_slider"):
            self.assertIn(f"self.{name}.sliderPressed.connect(self._push_undo)", self.source)

    def test_color_wheel_gesture_uses_single_edit_start_snapshot(self):
        self.assertIn("wheel.editingStarted.connect(self._push_undo)", self.source)

    def test_blend_mode_change_does_not_depend_on_stale_undo_pop(self):
        method = self.method_source("_blend_mode_changed")
        self.assertNotIn("self._undo_stack.pop()", method)


if __name__ == "__main__":
    unittest.main()
