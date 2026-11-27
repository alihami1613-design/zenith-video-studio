"""Tests for ZENITH pre-export quality checks."""
import tempfile
import unittest
from pathlib import Path

from ai_editor.project_context import build_project_context
from ai_editor.quality_control import run_quality_checks
from timeline_model import TimelineProject


class QualityControlTests(unittest.TestCase):
    def test_missing_source_blocks_export(self):
        project = TimelineProject()
        project.add_clip("/missing/zenith-file.mp4", "missing.mp4")
        report = run_quality_checks(project)
        self.assertFalse(report.ready_for_export)
        self.assertEqual(report.error_count, 1)
        self.assertEqual(report.issues[0].check_id, "missing_media")

    def test_valid_media_is_export_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shot.mp4"
            path.write_bytes(b"placeholder")
            project = TimelineProject()
            project.add_clip(str(path), "shot.mp4", duration_frames=60)
            context = build_project_context(
                project, probe_fn=lambda _: {
                    "duration_seconds": 10.0, "width": 1920, "height": 1080,
                    "fps": 30.0, "has_video": True, "has_audio": True,
                    "probe_method": "test",
                },
            )
            report = run_quality_checks(project, context)
            self.assertTrue(report.ready_for_export)
            self.assertEqual(report.error_count, 0)

    def test_source_overrun_is_an_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "short.mp4"
            path.write_bytes(b"placeholder")
            project = TimelineProject(fps=30)
            project.add_clip(str(path), "short.mp4", duration_frames=120)
            context = build_project_context(
                project, probe_fn=lambda _: {
                    "duration_seconds": 2.0, "width": 640, "height": 360,
                    "fps": 30.0, "has_video": True, "has_audio": False,
                    "probe_method": "test",
                },
            )
            report = run_quality_checks(project, context)
            self.assertFalse(report.ready_for_export)
            self.assertIn("source_overrun", {issue.check_id for issue in report.issues})

    def test_primary_track_gap_is_a_warning_not_an_error(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "a.mp4"
            b = Path(folder) / "b.mp4"
            a.write_bytes(b"a")
            b.write_bytes(b"b")
            project = TimelineProject()
            project.add_clip(str(a), "a.mp4", start_frame=0, duration_frames=30)
            project.add_clip(str(b), "b.mp4", start_frame=45, duration_frames=30)
            report = run_quality_checks(project)
            self.assertTrue(report.ready_for_export)
            self.assertEqual(report.warning_count, 1)
            self.assertEqual(report.issues[0].check_id, "primary_track_gap")


if __name__ == "__main__":
    unittest.main()
