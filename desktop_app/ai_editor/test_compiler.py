"""Tests for compiling story beats into safe edit-plan drafts."""
import unittest

from ai_editor.compiler import compile_story_to_edit_plan
from ai_editor.cinematic_edit import design_cinematic_rhythm
from ai_editor.music_sync import MusicSyncDecision, MusicSyncDesign
from ai_editor.contracts import EditPlanError, MediaAsset
from ai_editor.narrative import StoryAct, StoryBeat, StoryBlueprint
from ai_editor.project_context import MediaInventoryItem, ProjectContext
from ai_editor.executor import preview_edit_plan
from timeline_model import TimelineProject


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
                  3.0, "video-1", 4.0, 7.0,
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
        self.assertEqual(len(plan.operations), 3)
        self.assertEqual(plan.operations[0].parameters["start_frame"], 0)
        self.assertEqual(plan.operations[0].parameters["duration_frames"], 120)
        self.assertEqual(plan.operations[1].parameters["start_frame"], 120)
        self.assertEqual(plan.operations[1].parameters["track"], "V1")
        self.assertEqual(plan.operations[2].kind, "set_transition")
        self.assertEqual(plan.operations[2].parameters["duration_frames"], 15)
        self.assertEqual(plan.operations[2].kind, "set_transition")
        self.assertEqual(plan.operations[2].parameters["clip_id"], "ai-b7458f4735-0001")
        self.assertTrue(plan.requires_user_approval)
        preview = preview_edit_plan(TimelineProject(), plan, [item.asset for item in make_context().assets])
        self.assertEqual(len(preview.project.clips), 2)
        self.assertEqual(preview.project.clips[1].transition_in_frames, 15)

    def test_compiler_uses_the_exact_approved_cinematic_transition_duration(self):
        story = make_story()
        context = make_context()
        design = design_cinematic_rhythm(
            story, context, transition_duration_seconds=1.0
        )
        plan = compile_story_to_edit_plan(
            story, context, cinematic_design=design
        )
        transition = next(op for op in plan.operations if op.kind == "set_transition")
        self.assertEqual(transition.parameters["duration_frames"], 30)

    def test_compiler_rejects_cinematic_design_from_a_different_frame_rate(self):
        from dataclasses import replace
        story = make_story()
        context = make_context()
        design = design_cinematic_rhythm(story, context)
        with self.assertRaisesRegex(EditPlanError, "frame rate"):
            compile_story_to_edit_plan(
                story, context, cinematic_design=replace(design, fps=24)
            )

    def test_compiler_rejects_cinematic_design_with_changed_beat_order(self):
        from dataclasses import replace
        story = make_story()
        context = make_context()
        design = design_cinematic_rhythm(story, context)
        first, second = design.decisions
        changed = replace(design, decisions=(second, first))
        with self.assertRaisesRegex(EditPlanError, "beat order or timing"):
            compile_story_to_edit_plan(
                story, context, cinematic_design=changed
            )

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


    def test_compiles_approved_music_sync_durations_into_real_clip_operations(self):
        story = make_story()
        context = make_context()
        cinematic = design_cinematic_rhythm(story, context)
        sync = MusicSyncDesign(
            fps=30, total_frames=210, estimated_bpm=120.0, tempo_confidence=0.8,
            decisions=(
                MusicSyncDecision("beat-001", 0, 0, 123, 120, 123, 4.1, 3,
                                  "candidate", "Matched a nearby pulse.",),
                MusicSyncDecision("beat-002", 1, 123, 87, 90, None, None, 0,
                                  "unchanged", "Narrative hold retained."),
            ),
            warnings=("Review the extended source range.",),
        )
        plan = compile_story_to_edit_plan(
            story, context, cinematic_design=cinematic, music_sync_design=sync
        )
        clips = [op for op in plan.operations if op.kind == "add_clip"]
        self.assertEqual([op.parameters["start_frame"] for op in clips], [0, 123])
        self.assertEqual([op.parameters["duration_frames"] for op in clips], [123, 87])
        self.assertTrue(any("extends the selected source range" in warning for warning in plan.warnings))
        preview = preview_edit_plan(
            TimelineProject(), plan, [item.asset for item in context.assets]
        )
        self.assertEqual([clip.duration_frames for clip in preview.project.clips], [123, 87])
        self.assertEqual(preview.project.duration_frames, 210)

    def test_music_sync_compilation_requires_cinematic_design(self):
        story = make_story()
        sync = MusicSyncDesign(30, 210, 120.0, 0.8, (), ())
        with self.assertRaisesRegex(EditPlanError, "requires its source cinematic"):
            compile_story_to_edit_plan(
                story, make_context(), music_sync_design=sync
            )

    def test_music_sync_compilation_rejects_source_overrun(self):
        story = make_story()
        context = make_context()
        cinematic = design_cinematic_rhythm(story, context)
        sync = MusicSyncDesign(
            30, 210, 120.0, 0.8,
            (
                MusicSyncDecision("beat-001", 0, 0, 303, 120, 303, 10.1, 183,
                                  "candidate", "Invalid overrun."),
                MusicSyncDecision("beat-002", 1, 303, -93, 90, None, None, 0,
                                  "unchanged", "Invalid duration."),
            ), (),
        )
        with self.assertRaises(EditPlanError):
            compile_story_to_edit_plan(
                story, context, cinematic_design=cinematic, music_sync_design=sync
            )

    def test_missing_project_fps_is_rejected(self):
        context = make_context()
        context = ProjectContext(1, {"width": 1920}, context.assets, (), ())
        with self.assertRaisesRegex(EditPlanError, "frame rate"):
            compile_story_to_edit_plan(make_story(), context)


if __name__ == "__main__":
    unittest.main()
