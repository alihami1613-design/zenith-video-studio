"""Static wiring checks for the desktop AI workflow.

These checks do not replace a Windows/PySide runtime test, but ensure the UI
module parses and the approval-gated provider workflow remains connected.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"


class MainAIWorkflowWiringTests(unittest.TestCase):
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

    def test_main_module_parses_and_contains_model_plan_worker(self):
        self.assertIn("AIEditPlanTask", self.source)
        self.assertIn("request_edit_plan", self.source)
        self.assertIn("def generate_ai_edit_plan", self.source)
        self.assertIn("def _ai_edit_plan_finished", self.source)

    def test_model_plan_requires_both_human_approvals(self):
        method = ast.get_source_segment(self.source, self.methods["generate_ai_edit_plan"])
        self.assertIn("ai_story_approval.isChecked()", method)
        self.assertIn("ai_shot_approval.isChecked()", method)
        self.assertIn("QMessageBox.question", method)

    def test_model_plan_is_previewed_before_final_apply(self):
        self.assertIn('self.ai_model_plan_button.clicked.connect(self.generate_ai_edit_plan)', self.source)
        self.assertIn('self.ai_preview_plan_button.clicked.connect(self.preview_ai_edit_draft)', self.source)
        self.assertIn('self.ai_apply_plan_button.clicked.connect(self.apply_ai_edit_draft)', self.source)
        self.assertIn("preview_edit_plan", self.source)
        self.assertIn("apply_edit_plan", self.source)

    def test_async_result_is_discarded_if_approvals_changed(self):
        method = ast.get_source_segment(self.source, self.methods["_ai_edit_plan_finished"])
        self.assertIn("approvals_still_valid", method)
        self.assertIn("self._ai_plan_story_snapshot", method)
        self.assertIn("self._ai_plan_shot_snapshot", method)

    def test_quality_control_blocks_final_apply_on_errors(self):
        method = ast.get_source_segment(self.source, self.methods["preview_ai_edit_draft"])
        self.assertIn("run_quality_checks(preview.project, self._ai_project_context)", method)
        self.assertIn("qc_report.ready_for_export", method)
        self.assertIn("not conflicts and qc_report.ready_for_export", method)
        self.assertIn("qc_report.error_count", method)

    def test_director_review_is_available_and_review_only(self):
        self.assertIn("from ai_editor.director_review import", self.source)
        self.assertIn('self.ai_director_review_button.clicked.connect(self.run_ai_director_review)', self.source)
        method = ast.get_source_segment(self.source, self.methods["run_ai_director_review"])
        self.assertIn("review_edit(", method)
        self.assertIn("self.timeline_project", method)
        self.assertNotIn("apply_edit_plan(", method)

    def test_director_review_receives_local_media_analysis(self):
        method = ast.get_source_segment(self.source, self.methods["run_ai_director_review"])
        self.assertIn("media_analysis=self._ai_media_analysis", method)
        self.assertIn("review_edit(", method)

    def test_music_alignment_uses_the_existing_preview_and_approval_gate(self):
        self.assertIn("build_music_alignment_plan", self.source)
        self.assertIn(
            'self.ai_music_align_button.clicked.connect(self.prepare_ai_music_alignment_fixes)',
            self.source,
        )
        method = ast.get_source_segment(
            self.source, self.methods["prepare_ai_music_alignment_fixes"]
        )
        self.assertIn("build_music_alignment_plan(", method)
        self.assertIn("self.ai_preview_plan_button.setEnabled(True)", method)
        self.assertIn("self.ai_apply_plan_button.setEnabled(False)", method)
        self.assertNotIn("apply_edit_plan(", method)

    def test_director_gap_fixes_use_existing_preview_and_approval_path(self):
        self.assertIn("build_gap_repair_plan", self.source)
        self.assertIn('self.ai_director_fix_button.clicked.connect(self.prepare_ai_director_fixes)', self.source)
        method = ast.get_source_segment(self.source, self.methods["prepare_ai_director_fixes"])
        self.assertIn("build_gap_repair_plan(", method)
        self.assertIn("self.ai_preview_plan_button.setEnabled(True)", method)
        self.assertIn("self.ai_apply_plan_button.setEnabled(False)", method)


if __name__ == "__main__":
    unittest.main()
