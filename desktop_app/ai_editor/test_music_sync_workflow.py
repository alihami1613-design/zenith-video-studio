"""Tests for approval-gated music-aware edit orchestration."""
import unittest

from ai_editor.contracts import EditPlanError, MediaAsset
from ai_editor.media_analysis import AssetAnalysis, MediaAnalysisReport, SpectralAudioSummary
from ai_editor.music_sync_workflow import build_music_aware_edit_draft
from ai_editor.project_context import MediaInventoryItem, ProjectContext
from ai_editor.narrative import StoryAct, StoryBeat, StoryBlueprint


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


def context_with_music():
    video = MediaAsset("video-1", "/private/video.mp4", "video", 300, 30, 1920, 1080)
    music = MediaAsset("music-1", "/private/music.wav", "audio", 300, 30)
    return ProjectContext(
        1, {"fps": 30, "width": 1920, "height": 1080},
        (
            MediaInventoryItem(video, True, 100, 10.0, 1920, 1080, 30.0, "ffprobe"),
            MediaInventoryItem(music, True, 100, 10.0, 0, 0, 30.0, "ffprobe"),
        ), (), (),
    )


def report_with_music(spectral=True):
    assets = ()
    if spectral:
        assets = (AssetAnalysis(
            "music-1", "audio",
            spectral_audio=SpectralAudioSummary(
                8000, 512, 128, 120.0, 0.8, (), (4.1,), ()
            ),
        ),)
    return MediaAnalysisReport(1, assets, ())


class MusicSyncWorkflowTests(unittest.TestCase):
    def test_requires_story_and_shot_selection_approval(self):
        with self.assertRaisesRegex(EditPlanError, "approvals are required"):
            build_music_aware_edit_draft(
                make_story(), context_with_music(), report_with_music(),
                audio_asset_id="music-1",
            )

    def test_story_approval_alone_does_not_bypass_shot_approval(self):
        with self.assertRaisesRegex(EditPlanError, "approvals are required"):
            build_music_aware_edit_draft(
                make_story(), context_with_music(), report_with_music(),
                audio_asset_id="music-1",
                story_approved=True,
                shot_selection_approved=False,
            )

    def test_builds_compilable_plan_after_both_approvals(self):
        context = context_with_music()
        result = build_music_aware_edit_draft(
            make_story(), context, report_with_music(),
            audio_asset_id="music-1",
            story_approved=True,
            shot_selection_approved=True,
        )
        self.assertTrue(result.requires_user_approval)
        self.assertTrue(result.edit_plan.requires_user_approval)
        clips = [op for op in result.edit_plan.operations if op.kind == "add_clip"]
        self.assertEqual([op.parameters["start_frame"] for op in clips], [0, 123])
        self.assertEqual([op.parameters["duration_frames"] for op in clips], [123, 87])

    def test_missing_spectral_data_falls_back_to_narrative_timing(self):
        result = build_music_aware_edit_draft(
            make_story(), context_with_music(), report_with_music(False),
            audio_asset_id="music-1",
            story_approved=True,
            shot_selection_approved=True,
        )
        clips = [op for op in result.edit_plan.operations if op.kind == "add_clip"]
        self.assertEqual([op.parameters["duration_frames"] for op in clips], [120, 90])
        self.assertTrue(any("No spectral audio analysis" in warning for warning in result.warnings))

    def test_unknown_audio_asset_is_rejected(self):
        with self.assertRaisesRegex(EditPlanError, "unavailable"):
            build_music_aware_edit_draft(
                make_story(), context_with_music(), report_with_music(),
                audio_asset_id="missing-audio",
                story_approved=True,
                shot_selection_approved=True,
            )

    def test_video_without_audio_stream_is_rejected(self):
        context = context_with_music()
        with self.assertRaisesRegex(EditPlanError, "no audio stream"):
            build_music_aware_edit_draft(
                make_story(), context, report_with_music(),
                audio_asset_id="video-1",
                story_approved=True,
                shot_selection_approved=True,
            )


if __name__ == "__main__":
    unittest.main()
