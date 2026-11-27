"""Regression tests for safe AI edit-plan contracts."""
import unittest

from ai_editor.contracts import (
    EditOperation, EditPlan, EditPlanError, MediaAsset, ProjectBrief,
    plan_from_dict, plan_to_dict,
)


ASSETS = [MediaAsset("shot-a", "/media/a.mp4", "video", 900, 30, 1920, 1080, True)]


def valid_plan(operations=None):
    return EditPlan(
        plan_id="plan-001",
        brief=ProjectBrief("Create a short cinematic documentary", target_duration_frames=300),
        summary="Select and arrange the strongest available shots.",
        operations=tuple(operations or ()),
    )


class EditPlanContractTests(unittest.TestCase):
    def test_valid_plan_round_trip(self):
        plan = valid_plan([EditOperation("op-001", "add_clip", {
            "asset_id": "shot-a", "track": "V1", "start_frame": 0,
            "source_in": 30, "duration_frames": 120,
        })])
        plan.validate(ASSETS)
        restored = plan_from_dict(plan_to_dict(plan))
        restored.validate(ASSETS)
        self.assertEqual(restored.plan_id, plan.plan_id)
        self.assertEqual(restored.operations[0].parameters["duration_frames"], 120)

    def test_unknown_operation_is_rejected(self):
        plan = valid_plan([EditOperation("op-001", "run_python", {"code": "print(1)"})])
        with self.assertRaises(EditPlanError):
            plan.validate(ASSETS)

    def test_arbitrary_parameters_are_rejected(self):
        plan = valid_plan([EditOperation("op-001", "add_clip", {
            "asset_id": "shot-a", "track": "V1", "start_frame": 0,
            "source_in": 0, "duration_frames": 30, "shell": "rm -rf",
        })])
        with self.assertRaises(EditPlanError):
            plan.validate(ASSETS)

    def test_source_overrun_is_rejected(self):
        plan = valid_plan([EditOperation("op-001", "add_clip", {
            "asset_id": "shot-a", "track": "V1", "start_frame": 0,
            "source_in": 850, "duration_frames": 100,
        })])
        with self.assertRaises(EditPlanError):
            plan.validate(ASSETS)

    def test_cloud_permission_is_opt_in(self):
        brief = ProjectBrief("Edit my footage")
        self.assertFalse(brief.allow_cloud_media_analysis)
        self.assertFalse(brief.allow_online_asset_search)

    def test_approval_cannot_be_disabled(self):
        plan = EditPlan(
            "plan-001", ProjectBrief("Edit my footage"), "A valid plan.",
            tuple(), requires_user_approval=False,
        )
        with self.assertRaises(EditPlanError):
            plan.validate(ASSETS)

    def test_existing_clip_must_be_known(self):
        plan = valid_plan([EditOperation("op-001", "move_clip", {
            "clip_id": "missing-clip", "start_frame": 60,
        })])
        with self.assertRaises(EditPlanError):
            plan.validate(ASSETS)

    def test_color_values_are_bounded_and_finite(self):
        plan = valid_plan([EditOperation("op-001", "set_clip_grade", {
            "clip_id": "clip-1", "grade": {"exposure": float("nan")},
        })])
        with self.assertRaises(EditPlanError):
            plan.validate(ASSETS, {"clip-1"})

    def test_audio_clip_cannot_be_placed_on_video_track(self):
        audio = MediaAsset("music-a", "/media/music.wav", "audio", 1200, 30)
        plan = valid_plan([EditOperation("op-001", "add_clip", {
            "asset_id": "music-a", "track": "V1", "start_frame": 0,
            "source_in": 0, "duration_frames": 120,
        })])
        with self.assertRaises(EditPlanError):
            plan.validate(ASSETS + [audio])

    def test_duplicate_operation_ids_are_rejected(self):
        operation = EditOperation("op-001", "add_clip", {
            "asset_id": "shot-a", "track": "V1", "start_frame": 0,
            "source_in": 0, "duration_frames": 30,
        })
        with self.assertRaises(EditPlanError):
            valid_plan([operation, operation]).validate(ASSETS)

    def test_plan_requires_prompt_and_summary(self):
        with self.assertRaises(EditPlanError):
            ProjectBrief(" ").validate()
        plan = EditPlan("plan-001", ProjectBrief("Edit it"), " ", tuple())
        with self.assertRaises(EditPlanError):
            plan.validate(ASSETS)


if __name__ == "__main__":
    unittest.main()
