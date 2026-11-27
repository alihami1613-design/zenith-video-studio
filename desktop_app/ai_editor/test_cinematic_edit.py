"""Tests for cinematic rhythm design."""
import unittest

from ai_editor.contracts import MediaAsset, EditPlanError
from ai_editor.narrative import StoryAct, StoryBeat, StoryBlueprint
from ai_editor.project_context import MediaInventoryItem, ProjectContext
from ai_editor.cinematic_edit import design_cinematic_rhythm


def fixture():
    video = MediaAsset("video-1", "/private/video.mp4", "video", 300, 30)
    context = ProjectContext(
        1, {"fps": 30, "width": 1920, "height": 1080},
        (MediaInventoryItem(video, True, 100, 10.0, 1920, 1080, 30.0, "ffprobe"),),
        (), (),
    )
    beats = (
        StoryBeat("beat-001", 0, "hook", "Hook", "Open strongly", 2.0,
                  "video-1", 0.0, 2.0, "Opening image", "Question", "Impact", "hard_cut"),
        StoryBeat("beat-002", 1, "revelation", "Reveal", "Reveal evidence", 8.0,
                  "video-1", 2.0, 10.0, "Evidence", "Explain", "Music rise", "dissolve"),
    )
    story = StoryBlueprint(
        "story-rhythm", "Create a film", "A story", "A promise", "Tension to clarity",
        10.0, (StoryAct("act-1", "opening", "Opening", "What is it?", beats),),
    )
    return context, story


class CinematicRhythmTests(unittest.TestCase):
    def test_frame_accurate_rhythm_and_timeline_positions(self):
        context, story = fixture()
        design = design_cinematic_rhythm(story, context)
        self.assertEqual(design.total_frames, 300)
        self.assertEqual(design.decisions[0].start_frame, 0)
        self.assertEqual(design.decisions[0].rhythm, "quick")
        self.assertEqual(design.decisions[0].transition_duration_frames, 0)
        self.assertEqual(design.decisions[1].start_frame, 60)
        self.assertEqual(design.decisions[1].rhythm, "hold")
        self.assertEqual(design.decisions[1].transition_type, "dissolve")
        self.assertEqual(design.decisions[1].transition_duration_frames, 15)
        self.assertTrue(design.requires_user_approval)

    def test_match_cut_is_not_claimed_as_visually_verified(self):
        context, story = fixture()
        beat = story.beats[0]
        from dataclasses import replace
        changed = replace(beat, transition_intent="match_cut")
        story = replace(story, acts=(replace(story.acts[0], beats=(changed, story.beats[1])),))
        design = design_cinematic_rhythm(story, context)
        self.assertTrue(any("not verified" in w for w in design.decisions[0].warnings))

    def test_invalid_pace_profile_is_rejected(self):
        context, story = fixture()
        with self.assertRaisesRegex(EditPlanError, "pace profile"):
            design_cinematic_rhythm(story, context, pace_profile="hyperdrive")

    def test_transition_duration_is_bounded(self):
        context, story = fixture()
        with self.assertRaisesRegex(EditPlanError, "between 0 and 3"):
            design_cinematic_rhythm(story, context, transition_duration_seconds=4)


if __name__ == "__main__":
    unittest.main()
