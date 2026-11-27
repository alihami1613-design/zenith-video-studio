"""Tests for evidence-only black-frame and freeze diagnostics."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from render_quality import inspect_rendered_video

FFMPEG = shutil.which("ffmpeg")


@unittest.skipUnless(FFMPEG, "FFmpeg is required for visual render diagnostics")
class RenderVisualQualityTests(unittest.TestCase):
    def _make_video(self, path, source):
        result = subprocess.run(
            [
                FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", source, "-an",
                "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1",
                "-pix_fmt", "yuv420p", str(path),
            ],
            capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])

    def test_sustained_black_is_reported_for_human_review(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "black.mp4"
            self._make_video(path, "color=c=black:s=96x64:r=25:d=2.5")
            report = inspect_rendered_video(path, FFMPEG)
            self.assertTrue(report.scanned)
            self.assertTrue(report.black_intervals)
            self.assertTrue(report.requires_human_review)
            self.assertGreaterEqual(report.black_intervals[0].duration_seconds, 1.0)

    def test_sustained_freeze_is_reported_for_human_review(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "freeze.mp4"
            self._make_video(path, "color=c=red:s=96x64:r=25:d=3")
            report = inspect_rendered_video(path, FFMPEG)
            self.assertTrue(report.freeze_intervals)
            self.assertTrue(report.requires_human_review)

    def test_moving_video_has_no_sustained_black_or_freeze_finding(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "motion.mp4"
            self._make_video(path, "testsrc2=size=96x64:rate=25:duration=3")
            report = inspect_rendered_video(path, FFMPEG)
            self.assertFalse(report.black_intervals)
            self.assertFalse(report.freeze_intervals)
            self.assertFalse(report.requires_human_review)

    def test_invalid_thresholds_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "motion.mp4"
            self._make_video(path, "testsrc2=size=96x64:rate=25:duration=1")
            with self.assertRaises(ValueError):
                inspect_rendered_video(path, FFMPEG, freeze_min_duration=0)


if __name__ == "__main__":
    unittest.main()
