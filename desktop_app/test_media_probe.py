"""Tests for metadata parsing helpers; no media files or Qt required."""
import unittest
from unittest.mock import patch
from subprocess import CompletedProcess
from pathlib import Path

from media_probe import _fraction, _from_ffmpeg_summary, duration_to_frames


class MediaProbeTests(unittest.TestCase):
    def test_fraction_handles_common_frame_rates(self):
        self.assertAlmostEqual(_fraction("30000/1001"), 29.97002997, places=5)
        self.assertIsNone(_fraction("0/0"))
        self.assertIsNone(_fraction("N/A"))

    def test_duration_to_frames_uses_project_rate(self):
        self.assertEqual(duration_to_frames(12.5, 30), 375)
        self.assertEqual(duration_to_frames(0.001, 30), 1)
        self.assertIsNone(duration_to_frames(None, 30))
        self.assertIsNone(duration_to_frames(4.0, 0))

    @patch("media_probe.subprocess.run")
    def test_ffmpeg_summary_extracts_video_metadata(self, run):
        run.return_value = CompletedProcess(
            args=[], returncode=1, stdout="",
            stderr=(
                "Input #0, mov,mp4: Duration: 00:01:23.45, start: 0.0\n"
                "Stream #0:0: Video: h264, yuv420p, 1920x1080, 29.97 fps\n"
                "Stream #0:1: Audio: aac, 48000 Hz, stereo"
            ),
        )
        result = _from_ffmpeg_summary(Path("sample.mp4"), "ffmpeg")
        self.assertAlmostEqual(result["duration_seconds"], 83.45)
        self.assertEqual((result["width"], result["height"]), (1920, 1080))
        self.assertAlmostEqual(result["fps"], 29.97)
        self.assertTrue(result["has_video"])
        self.assertTrue(result["has_audio"])


if __name__ == "__main__":
    unittest.main()
