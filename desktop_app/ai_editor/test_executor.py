"""Tests for preview isolation, approval gates, and transactional AI edits."""
import unittest

from ai_editor.contracts import EditOperation, EditPlan, EditPlanError, MediaAsset, ProjectBrief
from ai_editor.executor import apply_edit_plan, preview_edit_plan
from timeline_model import TimelineProject


ASSETS = [MediaAsset("shot-a", "/media/a.mp4", "video", 900, 30, 1920, 1080, True)]


def make_plan(operations):
    return EditPlan(
        "plan-exec-01", ProjectBrief("Create a concise cinematic film"),
        "Arrange source footage and apply a restrained grade.",
        tuple(operations),
    )


class AIEditExecutorTests(unittest.TestCase):
    def test_preview_does_not_mutate_live_project(self):
        project = TimelineProject()
        plan = make_plan([EditOperation("op-add", "add_clip", {
            "asset_id": "shot-a", "track": "V1", "start_frame": 0,
            "source_in": 30, "duration_frames": 120, "clip_id": "ai-new-clip-01",
        })])
        preview = preview_edit_plan(project, plan, ASSETS)
        self.assertEqual(project.clips, [])
        self.assertEqual(len(preview.project.clips), 1)
        self.assertEqual(preview.project.clips[0].source_in, 30)

    def test_commit_requires_explicit_approval(self):
        project = TimelineProject()
        plan = make_plan([])
        with self.assertRaises(EditPlanError):
            apply_edit_plan(project, plan, ASSETS)
        self.assertEqual(project.clips, [])

    def test_approved_commit_updates_live_project(self):
        project = TimelineProject()
        plan = make_plan([EditOperation("op-add", "add_clip", {
            "asset_id": "shot-a", "track": "V1", "start_frame": 15,
            "source_in": 0, "duration_frames": 90, "clip_id": "ai-new-clip-02",
        })])
        result = apply_edit_plan(project, plan, ASSETS, approved=True)
        self.assertIs(result.project, project)
        self.assertEqual(len(project.clips), 1)
        self.assertEqual(project.clips[0].start_frame, 15)

    def test_failed_operation_leaves_live_project_unchanged(self):
        project = TimelineProject()
        existing = project.add_clip("/media/existing.mp4", "existing.mp4",
                                    start_frame=200, duration_frames=60)
        before = project.to_dict()
        plan = make_plan([EditOperation("op-add", "add_clip", {
            "asset_id": "shot-a", "track": "V1", "start_frame": 0,
            "source_in": 0, "duration_frames": 90,
        }), EditOperation("op-transition", "set_transition", {
            "clip_id": existing.clip_id, "duration_frames": 15,
        })])
        with self.assertRaises(ValueError):
            apply_edit_plan(project, plan, ASSETS, approved=True)
        self.assertEqual(project.to_dict(), before)

    def test_split_clip_is_previewed_without_mutating_source_timeline(self):
        project = TimelineProject()
        clip = project.add_clip("/media/a.mp4", "a.mp4", start_frame=10, duration_frames=100)
        clip.color_grade = dict(clip.color_grade, exposure=0.5)
        plan = make_plan([EditOperation("op-split", "split_clip", {
            "clip_id": clip.clip_id, "at_frame": 55,
        })])
        preview = preview_edit_plan(project, plan, ASSETS)
        self.assertEqual(len(preview.project.clips), 2)
        left, right = sorted(preview.project.clips, key=lambda item: item.start_frame)
        self.assertEqual((left.start_frame, left.end_frame), (10, 55))
        self.assertEqual((right.start_frame, right.end_frame), (55, 110))
        self.assertEqual(right.source_in, 45)
        self.assertEqual(right.color_grade["exposure"], 0.5)
        self.assertEqual(len(project.clips), 1)
        self.assertEqual(project.clips[0].end_frame, 110)
        self.assertEqual(preview.created_clip_ids, (right.clip_id,))

    def test_split_clip_rejects_boundary_outside_clip(self):
        project = TimelineProject()
        clip = project.add_clip("/media/a.mp4", "a.mp4", start_frame=10, duration_frames=100)
        plan = make_plan([EditOperation("op-split", "split_clip", {
            "clip_id": clip.clip_id, "at_frame": 10,
        })])
        with self.assertRaises(ValueError):
            preview_edit_plan(project, plan, ASSETS)

    def test_trim_can_change_only_one_edge(self):
        project = TimelineProject()
        clip = project.add_clip("/media/a.mp4", "a.mp4", start_frame=10, duration_frames=100)
        plan = make_plan([EditOperation("op-trim", "trim_clip", {
            "clip_id": clip.clip_id, "new_start_frame": 20,
        })])
        preview = preview_edit_plan(project, plan, ASSETS)
        trimmed = preview.project.get_clip(clip.clip_id)
        self.assertEqual(trimmed.start_frame, 20)
        self.assertEqual(trimmed.end_frame, 110)


if __name__ == "__main__":
    unittest.main()
