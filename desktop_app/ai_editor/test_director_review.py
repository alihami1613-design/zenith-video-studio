"""Tests for evidence-backed, review-only director diagnostics."""
import tempfile
import unittest
from pathlib import Path

from timeline_model import TimelineProject
from ai_editor.director_review import review_edit, review_is_current, build_gap_repair_plan
from ai_editor.executor import preview_edit_plan
from ai_editor.project_context import build_project_context
from ai_editor.narrative import StoryBeat, StoryAct, StoryBlueprint
from ai_editor.shot_selection import ShotSelectionReport, BeatShotDecision


class DirectorReviewTests(unittest.TestCase):
    def _project(self, folder):
        a = Path(folder) / "a.mp4"
        b = Path(folder) / "b.mp4"
        a.write_bytes(b"a")
        b.write_bytes(b"b")
        project = TimelineProject(fps=30)
        project.add_clip(str(a), "Opening", start_frame=0, duration_frames=12)
        project.add_clip(str(b), "Second", start_frame=45, duration_frames=420)
        return project

    def test_review_reports_measured_gap_and_pacing_advice_without_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            before = [(c.clip_id, c.start_frame, c.duration_frames) for c in project.clips]
            report = review_edit(project, pace_profile="balanced")
            ids = {item.finding_id for item in report.findings}
            self.assertTrue(any(value.startswith("gap-V1-") for value in ids))
            self.assertTrue(any(value.startswith("short-shot-") for value in ids))
            self.assertTrue(any(value.startswith("long-shot-") for value in ids))
            self.assertEqual(before, [(c.clip_id, c.start_frame, c.duration_frames) for c in project.clips])
            self.assertTrue(report.requires_user_review)

    def test_gap_repair_is_a_previewable_move_plan_and_does_not_mutate_source(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            report = review_edit(project)
            draft = build_gap_repair_plan(report, project, [])
            self.assertEqual(len(draft.edit_plan.operations), 1)
            operation = draft.edit_plan.operations[0]
            self.assertEqual(operation.kind, "move_clip")
            target_clip = next(c for c in project.clips if c.clip_id == operation.parameters["clip_id"])
            self.assertEqual(target_clip.start_frame, 45)
            preview = preview_edit_plan(project, draft.edit_plan, [])
            moved = preview.project.get_clip(target_clip.clip_id)
            self.assertEqual(moved.start_frame, 12)
            self.assertEqual(target_clip.start_frame, 45)
            self.assertTrue(draft.edit_plan.requires_user_approval)

    def test_gap_repair_rejects_stale_review_and_non_gap_findings(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            report = review_edit(project)
            project.clips[0].start_frame += 1
            with self.assertRaises(ValueError):
                build_gap_repair_plan(report, project, [])

    def test_report_becomes_stale_after_timeline_change(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            report = review_edit(project)
            self.assertTrue(review_is_current(report, project))
            project.clips[0].start_frame += 1
            self.assertFalse(review_is_current(report, project))

    def test_unassigned_story_beat_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            context = build_project_context(project, probe_fn=lambda _: {
                "duration_seconds": 20.0, "width": 1920, "height": 1080,
                "fps": 30.0, "has_video": True, "has_audio": False,
                "probe_method": "test",
            })
            beat = StoryBeat("beat-1", 0, "hook", "Opening hook", "Introduce the subject",
                             3.0, visual_intent="A clear opening image")
            story = StoryBlueprint("story-1", "make a film", "A film", "Promise", "Arc",
                                   3.0, (StoryAct("act-1", "opening", "Opening",
                                                  "What happens?", (beat,)),))
            report = review_edit(project, context, story=story)
            self.assertIn("unassigned-beat-beat-1", {item.finding_id for item in report.findings})

    def test_technical_only_shot_assignment_is_flagged(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            context = build_project_context(project, probe_fn=lambda _: {
                "duration_seconds": 20.0, "width": 1920, "height": 1080,
                "fps": 30.0, "has_video": True, "has_audio": False,
                "probe_method": "test",
            })
            beat = StoryBeat("beat-1", 0, "hook", "Opening hook", "Introduce the subject",
                             3.0, visual_intent="A clear opening image")
            story = StoryBlueprint("story-1", "make a film", "A film", "Promise", "Arc",
                                   3.0, (StoryAct("act-1", "opening", "Opening",
                                                  "What happens?", (beat,)),))
            selection = ShotSelectionReport(story, (
                BeatShotDecision("beat-1", "candidate", "technical_only", 0.5,
                                 ("No semantic visual description supplied.",)),
            ), 1, ())
            report = review_edit(project, context, story=story, shot_selection=selection)
            self.assertIn("shot-confidence-beat-1", {item.finding_id for item in report.findings})

    def test_invalid_pace_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            with self.assertRaises(ValueError):
                review_edit(project, pace_profile="viral")

if __name__ == "__main__":
    unittest.main()
