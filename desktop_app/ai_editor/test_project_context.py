"""Tests for local AI project-context and media inventory construction."""
import tempfile
import unittest
from pathlib import Path

from ai_editor.project_context import build_project_context, media_inventory_fingerprint
from timeline_model import TimelineProject


class ProjectContextTests(unittest.TestCase):
    def test_inventory_is_deterministic_and_uses_project_frame_rate(self):
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "sample.mp4"
            media.write_bytes(b"metadata-only-test")
            project = TimelineProject(fps=25)
            fake_probe = lambda path: {
                "duration_seconds": 12.0, "width": 1280, "height": 720,
                "fps": 24.0, "has_video": True, "has_audio": True,
                "probe_method": "test",
            }
            first = build_project_context(project, [media], probe_fn=fake_probe)
            second = build_project_context(project, [media], probe_fn=fake_probe)
            self.assertEqual(first.assets[0].asset.asset_id, second.assets[0].asset.asset_id)
            self.assertEqual(first.assets[0].asset.duration_frames, 300)
            self.assertEqual(first.assets[0].asset.fps, 25)
            self.assertEqual(first.assets[0].asset.media_type, "video")
            self.assertEqual(first.to_dict(), second.to_dict())

    def test_missing_timeline_media_is_reported(self):
        project = TimelineProject()
        project.add_clip("/definitely/missing/zenith-source.mp4", "missing.mp4")
        context = build_project_context(project)
        self.assertFalse(context.assets[0].exists)
        self.assertTrue(context.warnings)
        self.assertEqual(context.timeline_clips[0]["clip_id"], project.clips[0].clip_id)

    def test_audio_only_media_is_classified(self):
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "voice.wav"
            media.write_bytes(b"audio")
            context = build_project_context(
                TimelineProject(), [media],
                probe_fn=lambda path: {
                    "duration_seconds": 4.0, "width": None, "height": None,
                    "fps": None, "has_video": False, "has_audio": True,
                    "probe_method": "test",
                },
            )
            self.assertEqual(context.assets[0].asset.media_type, "audio")
            self.assertTrue(context.assets[0].asset.has_audio)
            self.assertEqual(context.assets[0].asset.duration_frames, 120)

    def test_probe_failure_is_visible_as_warning(self):
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "broken.bin"
            media.write_bytes(b"broken")
            context = build_project_context(
                TimelineProject(), [media],
                probe_fn=lambda path: (_ for _ in ()).throw(RuntimeError("probe failed")),
            )
            self.assertIn("probe failed", context.assets[0].warning)
            self.assertTrue(context.warnings)


if __name__ == "__main__":
    unittest.main()
