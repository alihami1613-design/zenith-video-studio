"""Tests for bounded low-resolution Speed Ramp preview generation."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from speed_ramp_preview import (
    _preview_segments, build_speed_ramp_preview_command,
    create_speed_ramp_preview,
)
from proxy_manager import find_ffmpeg


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


    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required for preview integration")
    def test_real_ffmpeg_speed_ramp_preview_decodes(self):
        ffmpeg = find_ffmpeg()
        with tempfile.TemporaryDirectory(prefix="zenith_speed_preview_") as folder:
            root = Path(folder)
            source = root / "source.mp4"
            generated = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=30:duration=3",
                 "-an", "-c:v", "libx264", "-preset", "ultrafast",
                 "-threads", "1", str(source)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(generated.returncode, 0, generated.stderr[-2000:])
            preview = create_speed_ramp_preview(
                source, 0, 90, 30,
                [{"frame": 0, "rate": 0.5}, {"frame": 89, "rate": 2.0}],
                15, 30, cache_dir=root / "cache",
            )
            self.assertGreater(preview.stat().st_size, 0)
            decoded = subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(preview),
                 "-f", "null", "-"],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(decoded.returncode, 0, decoded.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
