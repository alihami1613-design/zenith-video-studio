"""Tests for post-render MP4 metadata and decode verification."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from render_validation import validate_rendered_mp4
from timeline_model import TimelineProject
from video_render import render_timeline_mp4

FFMPEG = shutil.which("ffmpeg")


@unittest.skipUnless(FFMPEG, "FFmpeg is required for MP4 validation tests")
class RenderValidationTests(unittest.TestCase):
    def _make_mp4(self, path, *, audio=False):
        command = [
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=25:duration=1",
        ]
        if audio:
            command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1"]
        command += ["-map", "0:v:0"]
        if audio:
            command += ["-map", "1:a:0"]
        command += [
            "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1",
            "-pix_fmt", "yuv420p",
        ]
        if audio:
            command += ["-c:a", "aac", "-shortest"]
        command += [str(path)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_valid_video_and_audio_are_fully_decoded(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "valid.mp4"
            self._make_mp4(output, audio=True)
            report = validate_rendered_mp4(
                output, FFMPEG, expected_width=96, expected_height=64,
                expected_fps=25, expected_duration_seconds=1.0,
                expect_audio=True,
            )
            self.assertTrue(report.valid)
            self.assertTrue(report.has_video)
            self.assertTrue(report.has_audio)
            self.assertTrue(report.decode_succeeded)
            self.assertIsNotNone(report.visual_quality)
            self.assertTrue(report.visual_quality.scanned)
            self.assertIsNone(report.visual_scan_error)
            self.assertEqual((report.width, report.height, report.fps), (96, 64, 25.0))

    def test_missing_expected_audio_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "silent.mp4"
            self._make_mp4(output)
            with self.assertRaisesRegex(ValueError, "ترک صوتی"):
                validate_rendered_mp4(
                    output, FFMPEG, expected_width=96, expected_height=64,
                    expected_fps=25, expected_duration_seconds=1.0,
                    expect_audio=True,
                )

    def test_wrong_project_dimensions_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "wrong-size.mp4"
            self._make_mp4(output)
            with self.assertRaisesRegex(ValueError, "ابعاد تصویر"):
                validate_rendered_mp4(
                    output, FFMPEG, expected_width=128, expected_height=64,
                    expected_fps=25, expected_duration_seconds=1.0,
                    expect_audio=False,
                )

    def test_timeline_renderer_validates_before_finalizing_mp4(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            output = root / "final.mp4"
            self._make_mp4(source)
            project = TimelineProject(fps=25, width=96, height=64)
            project.add_clip(str(source), "Test shot", duration_frames=25)
            result = render_timeline_mp4(project, output, timeout_seconds=90)
            self.assertEqual(result, output.resolve())
            report = validate_rendered_mp4(
                result, FFMPEG, expected_width=96, expected_height=64,
                expected_fps=25, expected_duration_seconds=1.0,
                expect_audio=False,
            )
            self.assertTrue(report.valid)
            self.assertTrue(report.decode_succeeded)
            self.assertTrue(report.visual_quality.scanned)

    def test_corrupt_or_empty_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "broken.mp4"
            output.write_bytes(b"not an mp4")
            with self.assertRaises(ValueError):
                validate_rendered_mp4(
                    output, FFMPEG, expected_width=96, expected_height=64,
                    expected_fps=25, expected_duration_seconds=1.0,
                    expect_audio=False,
                )


if __name__ == "__main__":
    unittest.main()
