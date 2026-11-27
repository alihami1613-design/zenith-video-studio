"""Tests for privacy-safe AI edit planning orchestration."""
import unittest

from ai_editor.contracts import EditPlanError
from ai_editor.planner import build_planning_request, request_edit_plan
from ai_editor.project_context import MediaInventoryItem, ProjectContext
from ai_editor.contracts import MediaAsset
from timeline_model import TimelineProject


class FakeProvider:
    def __init__(self, result):
        self.result = result
        self.request = None

    def generate_edit_plan(self, request):
        self.request = request
        return self.result


def empty_plan(prompt):
    return {
        "plan_id": "plan-provider-01",
        "brief": {"prompt": prompt},
        "summary": "A validated empty starter plan.",
        "operations": [],
        "assumptions": [],
        "warnings": [],
        "format_version": 1,
        "requires_user_approval": True,
    }


class AIPlannerTests(unittest.TestCase):
    def test_request_redacts_local_paths(self):
        asset = MediaAsset("asset-001", "/private/user/video.mp4", "video", 300, 30)
        context = ProjectContext(
            schema_version=1,
            project={"fps": 30, "width": 1920, "height": 1080},
            assets=(MediaInventoryItem(
                asset, True, 1024, 10.0, 1920, 1080, 30.0, "ffprobe"
            ),),
            timeline_clips=(),
            warnings=(),
        )
        request = build_planning_request("Make a short film", context)
        serialized = str(request)
        self.assertNotIn("/private/user/video.mp4", serialized)
        self.assertEqual(request["assets"][0]["asset_id"], "asset-001")
        self.assertFalse(request["privacy"]["local_paths_included"])
        self.assertFalse(request["privacy"]["media_bytes_included"])

    def test_provider_result_is_parsed_and_validated(self):
        prompt = "Create a short documentary"
        provider = FakeProvider(empty_plan(prompt))
        plan = request_edit_plan(prompt, TimelineProject(), provider)
        self.assertEqual(plan.brief.prompt, prompt)
        self.assertTrue(plan.requires_user_approval)
        self.assertIn("response_schema", provider.request)

    def test_provider_cannot_change_original_prompt(self):
        provider = FakeProvider(empty_plan("different request"))
        with self.assertRaises(EditPlanError):
            request_edit_plan("my original request", TimelineProject(), provider)

    def test_invalid_provider_json_is_rejected(self):
        provider = FakeProvider("not valid JSON")
        with self.assertRaises(EditPlanError):
            request_edit_plan("Make a film", TimelineProject(), provider)

    def test_provider_is_required(self):
        with self.assertRaises(EditPlanError):
            request_edit_plan("Make a film", TimelineProject(), None)


if __name__ == "__main__":
    unittest.main()
