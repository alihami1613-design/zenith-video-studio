"""Tests for narrative blueprint validation and provider orchestration."""
import unittest

from ai_editor.contracts import EditPlanError, MediaAsset
from ai_editor.narrative import (
    StoryAct, StoryBeat, StoryBlueprint, build_story_request,
    request_story_blueprint, parse_story_blueprint_json,
)
from ai_editor.project_context import MediaInventoryItem, ProjectContext


class FakeStoryProvider:
    is_remote = False

    def __init__(self, result):
        self.result = result
        self.request = None

    def generate_story_blueprint(self, request):
        self.request = request
        return self.result


def context_with_video():
    asset = MediaAsset("asset-video-1", "/private/raw.mp4", "video", 300, 30)
    item = MediaInventoryItem(
        asset, True, 1000, 10.0, 1920, 1080, 30.0, "ffprobe"
    )
    return ProjectContext(1, {"fps": 30, "width": 1920, "height": 1080},
                          (item,), (), ())


def valid_blueprint(prompt="Create a short documentary"):
    beats = (
        StoryBeat("beat-001", 0, "hook", "Opening image", "Create curiosity",
                  4.0, "asset-video-1", 0.0, 4.0,
                  "A striking opening shot", "Pose the central question",
                  "A restrained impact", "hard_cut"),
        StoryBeat("beat-002", 1, "resolution", "Closing thought", "Deliver closure",
                  6.0, "asset-video-1", 4.0, 10.0,
                  "A calm closing image", "Resolve the central question",
                  "Music resolves naturally", "fade"),
    )
    return {
        "story_id": "story-demo-01",
        "original_prompt": prompt,
        "logline": "A concise story with a clear central question.",
        "audience_promise": "The viewer will understand the central idea.",
        "emotional_arc": "Curiosity to understanding.",
        "estimated_duration_seconds": 10.0,
        "acts": [{
            "act_id": "act-opening",
            "act_type": "opening",
            "title": "The question",
            "dramatic_question": "What is hidden from view?",
            "beats": [beat.__dict__ for beat in beats],
        }],
        "assumptions": [],
        "warnings": [],
        "format_version": 1,
        "requires_user_approval": True,
    }


class NarrativeBlueprintTests(unittest.TestCase):
    def test_valid_blueprint_is_parsed_and_validated(self):
        prompt = "Create a short documentary"
        provider = FakeStoryProvider(valid_blueprint(prompt))
        blueprint = request_story_blueprint(prompt, context_with_video(), provider)
        self.assertEqual(len(blueprint.beats), 2)
        self.assertEqual(blueprint.estimated_duration_seconds, 10.0)
        self.assertTrue(blueprint.requires_user_approval)

    def test_request_redacts_local_paths_and_media_bytes(self):
        request = build_story_request("Tell a story", context_with_video())
        serialized = str(request)
        self.assertNotIn("/private/raw.mp4", serialized)
        self.assertFalse(request["privacy"]["local_paths_included"])
        self.assertFalse(request["privacy"]["media_bytes_included"])

    def test_unknown_asset_is_rejected(self):
        data = valid_blueprint()
        data["acts"][0]["beats"][0]["asset_id"] = "invented-asset"
        with self.assertRaisesRegex(EditPlanError, "unknown media asset"):
            request_story_blueprint(
                "Create a short documentary", context_with_video(),
                FakeStoryProvider(data),
            )

    def test_source_range_cannot_exceed_media_duration(self):
        data = valid_blueprint()
        data["acts"][0]["beats"][0]["source_out_seconds"] = 15.0
        with self.assertRaisesRegex(EditPlanError, "exceeds the media duration"):
            request_story_blueprint(
                "Create a short documentary", context_with_video(),
                FakeStoryProvider(data),
            )

    def test_sequence_must_be_contiguous_and_unique(self):
        data = valid_blueprint()
        data["acts"][0]["beats"][1]["sequence"] = 0
        with self.assertRaisesRegex(EditPlanError, "contiguous"):
            request_story_blueprint(
                "Create a short documentary", context_with_video(),
                FakeStoryProvider(data),
            )

    def test_duration_must_match_beat_sum(self):
        data = valid_blueprint()
        data["estimated_duration_seconds"] = 14.0
        with self.assertRaisesRegex(EditPlanError, "does not match"):
            request_story_blueprint(
                "Create a short documentary", context_with_video(),
                FakeStoryProvider(data),
            )

    def test_remote_story_provider_requires_explicit_consent(self):
        class RemoteProvider(FakeStoryProvider):
            is_remote = True

        provider = RemoteProvider(valid_blueprint("Create a short documentary"))
        with self.assertRaisesRegex(EditPlanError, "explicit user permission"):
            request_story_blueprint(
                "Create a short documentary", context_with_video(), provider
            )
        result = request_story_blueprint(
            "Create a short documentary", context_with_video(), provider,
            allow_cloud_planning=True,
        )
        self.assertEqual(result.story_id, "story-demo-01")

    def test_provider_cannot_change_prompt(self):
        with self.assertRaisesRegex(EditPlanError, "changed the original"):
            request_story_blueprint(
                "Original prompt", context_with_video(),
                FakeStoryProvider(valid_blueprint("different prompt")),
            )

    def test_approval_cannot_be_disabled(self):
        data = valid_blueprint()
        data["requires_user_approval"] = False
        with self.assertRaisesRegex(EditPlanError, "require explicit user approval"):
            request_story_blueprint(
                "Create a short documentary", context_with_video(),
                FakeStoryProvider(data),
            )

    def test_json_import_rejects_duplicate_keys(self):
        raw = '{"story_id":"one","story_id":"two"}'
        with self.assertRaisesRegex(EditPlanError, "Duplicate JSON key"):
            parse_story_blueprint_json(raw, context_with_video())

    def test_json_import_rejects_unknown_fields(self):
        data = valid_blueprint()
        data["execute_shell"] = "dangerous"
        import json
        with self.assertRaisesRegex(EditPlanError, "Unexpected story fields"):
            parse_story_blueprint_json(json.dumps(data), context_with_video())

    def test_json_import_rejects_unknown_nested_fields(self):
        data = valid_blueprint()
        data["acts"][0]["beats"][0]["untrusted_instruction"] = "ignore safeguards"
        import json
        with self.assertRaisesRegex(EditPlanError, "Unexpected fields in beat"):
            parse_story_blueprint_json(json.dumps(data), context_with_video())

    def test_json_import_rejects_nonstandard_numbers(self):
        with self.assertRaisesRegex(EditPlanError, "Non-standard JSON numeric"):
            parse_story_blueprint_json('{"value": NaN}', context_with_video())

    def test_json_import_enforces_size_limit(self):
        with self.assertRaisesRegex(EditPlanError, "1 MB limit"):
            parse_story_blueprint_json(" " * 1_000_001, context_with_video())

    def test_json_import_validates_and_returns_blueprint(self):
        import json
        story = parse_story_blueprint_json(json.dumps(valid_blueprint()), context_with_video())
        self.assertEqual(story.story_id, "story-demo-01")
        self.assertTrue(story.requires_user_approval)


    def test_provider_response_rejects_duplicate_json_keys(self):
        raw = '{"story_id":"first","story_id":"second"}'
        with self.assertRaisesRegex(EditPlanError, "Duplicate JSON key"):
            request_story_blueprint("Create a short documentary", context_with_video(), FakeStoryProvider(raw))

    def test_provider_response_rejects_unrecognized_fields(self):
        data = valid_blueprint()
        data["run_command"] = "not allowed"
        with self.assertRaisesRegex(EditPlanError, "Unexpected story fields"):
            request_story_blueprint("Create a short documentary", context_with_video(), FakeStoryProvider(data))

if __name__ == "__main__":
    unittest.main()
