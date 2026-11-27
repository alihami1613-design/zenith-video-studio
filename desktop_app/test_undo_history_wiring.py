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

    def test_mask_keyframe_signals_are_forwarded_by_timeline_widget(self):
        timeline_source = (Path(__file__).resolve().parent / "timeline_widget.py").read_text(encoding="utf-8")
        timeline_tree = ast.parse(timeline_source)
        widget = next(
            node for node in timeline_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "TimelineWidget"
        )
        declarations = {
            node.targets[0].id
            for node in widget.body
            if isinstance(node, ast.Assign)
            and node.targets and isinstance(node.targets[0], ast.Name)
        }
        self.assertIn("maskKeyframeMoved", declarations)
        self.assertIn("maskKeyframeSelected", declarations)
        self.assertIn("self.canvas.maskKeyframeMoved.connect(self.maskKeyframeMoved)", timeline_source)
        self.assertIn("self.canvas.maskKeyframeSelected.connect(self.maskKeyframeSelected)", timeline_source)

    def test_keyframe_drag_branches_capture_undo_before_edit(self):
        timeline_source = (Path(__file__).resolve().parent / "timeline_widget.py").read_text(encoding="utf-8")
        press = timeline_source.split("    def mousePressEvent(self, event):", 1)[1].split(
            "    def mouseMoveEvent(self, event):", 1
        )[0]
        for mode in ('"transform_keyframe"', '"mask_keyframe"', '"ramp"'):
            branch = press.split(f'self._drag_mode = {mode}', 1)
            self.assertEqual(len(branch), 2, f"missing drag mode {mode}")
            self.assertIn("self.editStarted.emit()", branch[1].split("return", 1)[0] if mode != '"ramp"' else press)

    def test_all_bound_main_window_callbacks_are_defined(self):
        connected = {
            node.args[0].attr
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "connect"
            and node.args
            and isinstance(node.args[0], ast.Attribute)
            and isinstance(node.args[0].value, ast.Name)
            and node.args[0].value.id == "self"
        }
        self.assertEqual(sorted(connected - set(self.methods)), [])

    def test_speed_and_keyframe_callbacks_are_present(self):
        required = {
            "_speed_ramp_changed", "_transform_keyframe_moved",
            "_transform_keyframe_selected", "_mask_keyframe_moved",
            "_mask_keyframe_selected", "_add_speed_ramp_point",
            "_clear_speed_ramp", "preview_speed_ramp",
            "_apply_clip_speed", "_toggle_clip_motion_blur",
            "_toggle_clip_reverse", "_sync_bezier_graph_visibility",
            "_bezier_graph_changed", "_bezier_graph_edit_started",
            "_bezier_graph_edit_finished",
        }
        self.assertTrue(required.issubset(self.methods))


if __name__ == "__main__":
    unittest.main()
