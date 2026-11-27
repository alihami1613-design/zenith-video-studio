"""Tests for evidence-aware narrative shot selection."""
import unittest

from ai_editor.contracts import MediaAsset
from ai_editor.media_analysis import AssetAnalysis, MediaAnalysisReport
from ai_editor.narrative import StoryAct, StoryBeat, StoryBlueprint
from ai_editor.project_context import MediaInventoryItem, ProjectContext
from ai_editor.shot_selection import VisualObservation, select_shots_for_story


def fixture():
    video = MediaAsset("video-1", "/private/video.mp4", "video", 300, 30, 1920, 1080)
    image = MediaAsset("image-1", "/private/image.png", "image", 0, 30, 1024, 1024)
    context = ProjectContext(1, {"fps": 30, "width": 1920, "height": 1080}, (
        MediaInventoryItem(video, True, 100, 10.0, 1920, 1080, 30.0, "ffprobe"),
        MediaInventoryItem(image, True, 20, None, 1024, 1024, None, "image"),
    ), (), ())
    report = MediaAnalysisReport(1, (
        AssetAnalysis("video-1", "video", (4.0, 7.0), (), None, ()),
    ), ())
    beat = StoryBeat("beat-001", 0, "hook", "Ocean discovery", "Reveal the ocean",
                     3.0, None, None, None, "deep ocean creatures",
                     "Introduce the discovery", "Subtle tension", "hard_cut")
    story = StoryBlueprint(
        "story-demo", "Make a documentary", "A story about discovery",
        "Explain a discovery", "Curiosity to wonder", 3.0,
        (StoryAct("act-1", "opening", "Opening", "What is below?", (beat,)),),
    )
    return context, report, story


class ShotSelectionTests(unittest.TestCase):
    def test_uses_semantic_observation_to_rank_matching_source(self):
        context, report, story = fixture()
        report = MediaAnalysisReport(1, (
            AssetAnalysis("video-1", "video", (4.0, 7.0), (), None, ()),
            AssetAnalysis("image-1", "image"),
        ), ())
        observations = (
            VisualObservation("video-1", 1.5, "deep ocean creatures underwater", 0.9),
            VisualObservation("video-1", 5.5, "city traffic at night", 0.8),
        )
        result = select_shots_for_story(story, context, report, observations=observations)
        selected = result.blueprint.beats[0]
        self.assertEqual(selected.asset_id, "video-1")
        self.assertEqual(selected.source_in_seconds, 0.5)
        self.assertEqual(selected.source_out_seconds, 3.5)
        self.assertEqual(result.decisions[0].confidence, "high")

    def test_without_semantics_marks_technical_only_not_high_confidence(self):
        context, report, story = fixture()
        result = select_shots_for_story(story, context, report)
        self.assertEqual(result.decisions[0].confidence, "technical_only")
        self.assertTrue(any("human review" in warning for warning in result.warnings))

    def test_preserves_existing_asset_assignments(self):
        context, report, story = fixture()
        beat = StoryBeat("beat-001", 0, "hook", "Ocean", "Reveal ocean", 3.0,
                         "video-1", 0.0, 3.0, "Ocean", "Narration", "Sound", "hard_cut")
        story = StoryBlueprint(story.story_id, story.original_prompt, story.logline,
                               story.audience_promise, story.emotional_arc, 3.0,
                               (StoryAct("act-1", "opening", "Open", "Question?", (beat,)),))
        result = select_shots_for_story(story, context, report)
        self.assertEqual(result.blueprint.beats[0].asset_id, "video-1")
        self.assertEqual(result.decisions[0].confidence, "preserved")

    def test_no_candidate_leaves_beat_unassigned(self):
        context, report, story = fixture()
        short_context = ProjectContext(
            1, context.project,
            (MediaInventoryItem(context.assets[0].asset, True, 100, 2.0,
                                1920, 1080, 30.0, "ffprobe"),),
            (), (),
        )
        result = select_shots_for_story(story, short_context, report)
        self.assertIsNone(result.blueprint.beats[0].asset_id)
        self.assertEqual(result.decisions[0].confidence, "unassigned")

    def test_unknown_observation_asset_is_rejected(self):
        context, report, story = fixture()
        with self.assertRaisesRegex(ValueError, "unknown or unavailable"):
            select_shots_for_story(
                story, context, report,
                observations=(VisualObservation("missing", 0.0, "ocean"),),
            )


if __name__ == "__main__":
    unittest.main()
