"""Tests for evidence-backed, review-only director diagnostics."""
import tempfile
import unittest
from pathlib import Path

from timeline_model import TimelineProject
from ai_editor.director_review import (
    review_edit, review_is_current, build_gap_repair_plan,
    build_music_alignment_plan,
)
from ai_editor.executor import preview_edit_plan
from ai_editor.project_context import build_project_context
from ai_editor.narrative import StoryBeat, StoryAct, StoryBlueprint
from ai_editor.shot_selection import ShotSelectionReport, BeatShotDecision
from ai_editor.media_analysis import (
    AssetAnalysis, MediaAnalysisReport, SpectralAudioSummary,
)


class DirectorReviewTests(unittest.TestCase):
    def _project(self, folder):
        a = Path(folder) / "a.mp4"
        b = Path(folder) / "b.mp4"
        a.write_bytes(b"a")
        b.write_bytes(b"b")
        project = TimelineProject(fps=30)
        project.add_clip(str(a), "Opening", start_frame=0, duration_frames=12)
        project.add_clip(str(b), "Second", start_frame=45, duration_frames=420)
        return project

    def test_review_reports_measured_gap_and_pacing_advice_without_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            before = [(c.clip_id, c.start_frame, c.duration_frames) for c in project.clips]
            report = review_edit(project, pace_profile="balanced")
            ids = {item.finding_id for item in report.findings}
            self.assertTrue(any(value.startswith("gap-V1-") for value in ids))
            self.assertTrue(any(value.startswith("short-shot-") for value in ids))
            self.assertTrue(any(value.startswith("long-shot-") for value in ids))
            self.assertEqual(before, [(c.clip_id, c.start_frame, c.duration_frames) for c in project.clips])
            self.assertTrue(report.requires_user_review)

    def test_gap_repair_is_a_previewable_move_plan_and_does_not_mutate_source(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            report = review_edit(project)
            draft = build_gap_repair_plan(report, project, [])
            self.assertEqual(len(draft.edit_plan.operations), 1)
            operation = draft.edit_plan.operations[0]
            self.assertEqual(operation.kind, "move_clip")
            target_clip = next(c for c in project.clips if c.clip_id == operation.parameters["clip_id"])
            self.assertEqual(target_clip.start_frame, 45)
            preview = preview_edit_plan(project, draft.edit_plan, [])
            moved = preview.project.get_clip(target_clip.clip_id)
            self.assertEqual(moved.start_frame, 12)
            self.assertEqual(target_clip.start_frame, 45)
            self.assertTrue(draft.edit_plan.requires_user_approval)

    def test_chained_gap_repairs_keep_the_track_contiguous(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            third = Path(folder) / "c.mp4"
            third.write_bytes(b"c")
            project.add_clip(str(third), "Third", start_frame=500, duration_frames=60)
            report = review_edit(project)
            draft = build_gap_repair_plan(report, project, [])
            preview = preview_edit_plan(project, draft.edit_plan, [])
            ordered = sorted(
                (clip for clip in preview.project.clips if clip.track == "V1"),
                key=lambda clip: clip.start_frame,
            )
            self.assertEqual(ordered[1].start_frame, ordered[0].end_frame)
            self.assertEqual(ordered[2].start_frame, ordered[1].end_frame)

    def test_gap_repair_rejects_stale_review_and_non_gap_findings(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            report = review_edit(project)
            project.clips[0].start_frame += 1
            with self.assertRaises(ValueError):
                build_gap_repair_plan(report, project, [])

    def test_report_becomes_stale_after_timeline_change(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            report = review_edit(project)
            self.assertTrue(review_is_current(report, project))
            project.fps = 24
            self.assertFalse(review_is_current(report, project))
            project.fps = 30
            project.clips[0].start_frame += 1
            self.assertFalse(review_is_current(report, project))

    def test_unassigned_story_beat_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            context = build_project_context(project, probe_fn=lambda _: {
                "duration_seconds": 20.0, "width": 1920, "height": 1080,
                "fps": 30.0, "has_video": True, "has_audio": False,
                "probe_method": "test",
            })
            beat = StoryBeat("beat-1", 0, "hook", "Opening hook", "Introduce the subject",
                             3.0, visual_intent="A clear opening image")
            story = StoryBlueprint("story-1", "make a film", "A film", "Promise", "Arc",
                                   3.0, (StoryAct("act-1", "opening", "Opening",
                                                  "What happens?", (beat,)),))
            report = review_edit(project, context, story=story)
            self.assertIn("unassigned-beat-beat-1", {item.finding_id for item in report.findings})

    def test_technical_only_shot_assignment_is_flagged(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            context = build_project_context(project, probe_fn=lambda _: {
                "duration_seconds": 20.0, "width": 1920, "height": 1080,
                "fps": 30.0, "has_video": True, "has_audio": False,
                "probe_method": "test",
            })
            beat = StoryBeat("beat-1", 0, "hook", "Opening hook", "Introduce the subject",
                             3.0, visual_intent="A clear opening image")
            story = StoryBlueprint("story-1", "make a film", "A film", "Promise", "Arc",
                                   3.0, (StoryAct("act-1", "opening", "Opening",
                                                  "What happens?", (beat,)),))
            selection = ShotSelectionReport(story, (
                BeatShotDecision("beat-1", "candidate", "technical_only", 0.5,
                                 ("No semantic visual description supplied.",)),
            ), 1, ())
            report = review_edit(project, context, story=story, shot_selection=selection)
            self.assertIn("shot-confidence-beat-1", {item.finding_id for item in report.findings})

    def test_review_uses_scene_boundaries_and_estimated_music_pulses(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            music = Path(folder) / "music.wav"
            music.write_bytes(b"music")
            project.add_clip(
                str(music), "Music", track="A1", start_frame=0,
                duration_frames=180, media_type="audio",
            )

            def probe(path):
                if Path(path).suffix == ".wav":
                    return {
                        "duration_seconds": 10.0, "width": None, "height": None,
                        "fps": None, "has_video": False, "has_audio": True,
                        "probe_method": "test",
                    }
                return {
                    "duration_seconds": 20.0, "width": 1920, "height": 1080,
                    "fps": 30.0, "has_video": True, "has_audio": False,
                    "probe_method": "test",
                }

            context = build_project_context(project, probe_fn=probe)
            video_asset = next(
                item.asset.asset_id for item in context.assets
                if item.asset.path == str(Path(folder) / "a.mp4")
            )
            audio_asset = next(
                item.asset.asset_id for item in context.assets
                if item.asset.path == str(music)
            )
            media = MediaAnalysisReport(
                1,
                (
                    AssetAnalysis(
                        video_asset, "video",
                        scene_boundaries_seconds=(0.2,),
                    ),
                    AssetAnalysis(
                        audio_asset, "audio",
                        spectral_audio=SpectralAudioSummary(
                            8000, 512, 128, 120.0, 0.9,
                            (1.5,), (1.5,),
                            ("Estimated pulse candidates; not verified beats.",),
                        ),
                    ),
                ),
                (),
            )
            report = review_edit(project, context, media_analysis=media)
            finding_ids = {item.finding_id for item in report.findings}
            self.assertIn(
                f"hidden-scene-boundary-{project.clips[0].clip_id}-1",
                finding_ids,
            )
            self.assertTrue(any(
                item.startswith("possible-music-cut-alignment-")
                for item in finding_ids
            ))
            self.assertTrue(all(
                finding.requires_user_approval for finding in report.findings
            ))

    def test_music_alignment_plan_trims_and_moves_cut_in_isolated_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            project.clips[0].duration_frames = 45
            music = Path(folder) / "music.wav"
            music.write_bytes(b"music")
            project.add_clip(
                str(music), "Music", track="A1", start_frame=0,
                duration_frames=180, media_type="audio",
            )

            def probe(path):
                if Path(path).suffix == ".wav":
                    return {
                        "duration_seconds": 10.0, "width": None, "height": None,
                        "fps": None, "has_video": False, "has_audio": True,
                        "probe_method": "test",
                    }
                return {
                    "duration_seconds": 20.0, "width": 1920, "height": 1080,
                    "fps": 30.0, "has_video": True, "has_audio": False,
                    "probe_method": "test",
                }

            context = build_project_context(project, probe_fn=probe)
            video_asset = next(
                item.asset.asset_id for item in context.assets
                if item.asset.path == str(Path(folder) / "a.mp4")
            )
            audio_asset = next(
                item.asset.asset_id for item in context.assets
                if item.asset.path == str(music)
            )
            media = MediaAnalysisReport(
                1,
                (
                    AssetAnalysis(video_asset, "video"),
                    AssetAnalysis(
                        audio_asset, "audio",
                        spectral_audio=SpectralAudioSummary(
                            8000, 512, 128, 120.0, 0.9,
                            (1.4,), (1.4,),
                            ("Estimated pulse candidates; not verified beats.",),
                        ),
                    ),
                ),
                (),
            )
            report = review_edit(project, context, media_analysis=media)
            finding = next(
                item for item in report.findings
                if item.category == "audio_visual_sync"
            )
            self.assertEqual(finding.target_frame, 42)
            self.assertEqual(finding.related_clip_id, project.clips[0].clip_id)
            draft = build_music_alignment_plan(
                report, project, [item.asset for item in context.assets]
            )
            self.assertEqual([op.kind for op in draft.edit_plan.operations], [
                "trim_clip", "move_clip",
            ])
            preview = preview_edit_plan(
                project, draft.edit_plan, [item.asset for item in context.assets]
            )
            self.assertEqual(preview.project.clips[0].end_frame, 42)
            self.assertEqual(preview.project.clips[1].start_frame, 42)
            self.assertEqual(project.clips[0].end_frame, 45)
            self.assertEqual(project.clips[1].start_frame, 45)
            self.assertTrue(draft.edit_plan.requires_user_approval)

    def test_music_alignment_plan_rejects_later_or_noncontiguous_cut(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            report = review_edit(project)
            with self.assertRaises(ValueError):
                build_music_alignment_plan(report, project, [])

    def test_media_analysis_type_is_validated(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            with self.assertRaises(TypeError):
                review_edit(project, media_analysis={"assets": []})

    def test_invalid_pace_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self._project(folder)
            with self.assertRaises(ValueError):
                review_edit(project, pace_profile="viral")

if __name__ == "__main__":
    unittest.main()
