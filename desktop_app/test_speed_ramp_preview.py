"""Tests for bounded low-resolution Speed Ramp preview generation."""
import tempfile
import unittest
from pathlib import Path

from speed_ramp_preview import (
    _preview_segments, build_speed_ramp_preview_command,
    create_speed_ramp_preview,
)


class SpeedRampPreviewTests(unittest.TestCase):
    def test_preview_segments_keep_source_continuity_from_clip_start(self):
        segments = _preview_segments(
            90, 30,
            [{"frame": 0, "rate": 0.5}, {"frame": 89, "rate": 2.0}],
            30, 60,
        )
        self.assertTrue(segments)
        self.assertAlmostEqual(segments[0]["source_start_frames"], 22.58, delta=0.15)
        self.assertAlmostEqual(
            sum(item["source_duration_frames"] for item in segments), 37.75, delta=0.5
        )
        self.assertAlmostEqual(segments[0]["preview_start_frames"], 0.0)

    def test_command_is_short_low_resolution_and_silent(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.mp4"
            source.touch()
            command = build_speed_ramp_preview_command(
                "ffmpeg", source, Path(folder) / "preview.mp4",
                15, 90, 30,
                [{"frame": 0, "rate": 0.5}, {"frame": 89, "rate": 2.0}],
                30, 30,
            )
        joined = " ".join(command)
        self.assertIn("scale='min(480,iw)':-2", joined)
        self.assertIn("fps=15", joined)
        self.assertIn("-threads 1", joined)
        self.assertIn("-an", joined)
        self.assertIn("concat=n=", joined)

    def test_invalid_preview_range_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.mp4"
            source.touch()
            with self.assertRaises(ValueError):
                build_speed_ramp_preview_command(
                    "ffmpeg", source, Path(folder) / "preview.mp4",
                    0, 30, 30, [{"frame": 0, "rate": 1.0}], 30, 10,
                )


if __name__ == "__main__":
    unittest.main()
