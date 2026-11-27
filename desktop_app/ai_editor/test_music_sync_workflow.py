"""Tests for approval-gated music-aware edit orchestration."""
import unittest

from ai_editor.contracts import EditPlanError, MediaAsset
from ai_editor.media_analysis import AssetAnalysis, MediaAnalysisReport, SpectralAudioSummary
from ai_editor.music_sync_workflow import build_music_aware_edit_draft
from ai_editor.project_context import MediaInventoryItem, ProjectContext
from ai_editor.test_compiler import make_context, make_story


def context_with_music():
    base = make_context()
    music = MediaAsset("music-1", "/private/music.wav", "audio", 300, 30)
    return ProjectContext(
        base.schema_version, base.project,
        base.assets + (
            MediaInventoryItem(music, True, 100, 10.0, 0, 0, 30.0, "ffprobe"),
        ),
        base.warnings, base.errors,
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
        context = make_context()
        with self.assertRaisesRegex(EditPlanError, "no audio stream"):
            build_music_aware_edit_draft(
                make_story(), context, report_with_music(),
                audio_asset_id="video-1",
                story_approved=True,
                shot_selection_approved=True,
            )


if __name__ == "__main__":
    unittest.main()
