"""Tests for compiling story beats into safe edit-plan drafts."""
import unittest

from ai_editor.compiler import compile_story_to_edit_plan
from ai_editor.contracts import EditPlanError, MediaAsset
from ai_editor.narrative import StoryAct, StoryBeat, StoryBlueprint
from ai_editor.project_context import MediaInventoryItem, ProjectContext


def make_context():
    video = MediaAsset("video-1", "/private/video.mp4", "video", 300, 30)
    image = MediaAsset("image-1", "/private/image.png", "image", 0, 30)
    return ProjectContext(
        1, {"fps": 30, "width": 1920, "height": 1080},
        (
            MediaInventoryItem(video, True, 100, 10.0, 1920, 1080, 30.0, "ffprobe"),
            MediaInventoryItem(image, True, 20, None, 1024, 1024, None, "image"),
        ), (), (),
    )


def make_story():
    beats = (
        StoryBeat("beat-001", 0, "hook", "Opening", "Hook the viewer",
                  4.0, "video-1", 0.0, 4.0,
                  "Strong first image", "Ask a question", "Impact", "hard_cut"),
        StoryBeat("beat-002", 1, "resolution", "Ending", "Resolve the idea",
                  3.0, "image-1", None, None,
                  "Quiet final frame", "Close the story", "Music resolves", "fade"),
    )
    return StoryBlueprint(
        "story-demo", "Create a documentary", "A clear logline",
        "A meaningful takeaway", "Curiosity to clarity", 7.0,
        (StoryAct("act-1", "opening", "Opening act", "What happens next?", beats),),
    )


class StoryCompilerTests(unittest.TestCase):
    def test_compiles_source_backed_beats_to_non_mutating_operations(self):
        plan = compile_story_to_edit_plan(make_story(), make_context())
        self.assertEqual(len(plan.operations), 2)
        self.assertEqual(plan.operations[0].parameters["start_frame"], 0)
        self.assertEqual(plan.operations[0].parameters["duration_frames"], 120)
        self.assertEqual(plan.operations[1].parameters["start_frame"], 120)
        self.assertEqual(plan.operations[1].parameters["track"], "V1")
        self.assertTrue(plan.requires_user_approval)

    def test_unassigned_beats_become_explicit_placeholders(self):
        story = make_story()
        beat = StoryBeat("beat-002", 1, "resolution", "Ending", "Close",
                         3.0, None, None, None, "Final visual", "Closing line",
                         "Resolve", "fade")
        story = StoryBlueprint(
            story.story_id, story.original_prompt, story.logline,
            story.audience_promise, story.emotional_arc,
            7.0, (StoryAct("act-1", "opening", "Opening", "Question?",
                           (story.beats[0], beat)),),
        )
        plan = compile_story_to_edit_plan(story, make_context())
        self.assertEqual(len(plan.operations), 1)
        self.assertTrue(any("placeholder" in warning for warning in plan.warnings))

    def test_mismatched_source_and_target_duration_is_rejected(self):
        story = make_story()
        mismatched = StoryBeat(
            "beat-001", 0, "hook", "Opening", "Hook", 5.0,
            "video-1", 0.0, 4.0, "Visual", "Narration", "Sound", "hard_cut",
        )
        story = StoryBlueprint(
            story.story_id, story.original_prompt, story.logline,
            story.audience_promise, story.emotional_arc, 8.0,
            (StoryAct("act-1", "opening", "Opening", "Question?",
                      (mismatched, story.beats[1])),),
        )
        with self.assertRaisesRegex(EditPlanError, "duration differ"):
            compile_story_to_edit_plan(story, make_context())

    def test_missing_project_fps_is_rejected(self):
        context = make_context()
        context = ProjectContext(1, {"width": 1920}, context.assets, (), ())
        with self.assertRaisesRegex(EditPlanError, "frame rate"):
            compile_story_to_edit_plan(make_story(), context)


if __name__ == "__main__":
    unittest.main()
