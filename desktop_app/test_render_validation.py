"""Tests for post-render MP4 metadata and decode verification."""
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from render_validation import validate_rendered_mp4
from timeline_model import TimelineProject
from video_render import RenderCancelledError, render_timeline_mp4

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
            self.assertIsNotNone(report.audio_quality)
            self.assertTrue(report.audio_quality.scanned)
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
            reports = []
            progress_events = []
            result = render_timeline_mp4(
                project, output, timeout_seconds=90, validation_callback=reports.append,
                progress_callback=lambda percent, stage: progress_events.append((percent, stage)),
            )
            self.assertEqual(result, output.resolve())
            self.assertTrue(any(stage == "رندر تصویر" for _, stage in progress_events))
            self.assertTrue(any(stage == "اعتبارسنجی و کنترل کیفیت" for _, stage in progress_events))
            self.assertEqual(progress_events[-1], (100, "پایان رندر"))
            self.assertEqual(
                [percent for percent, _ in progress_events],
                sorted(percent for percent, _ in progress_events),
            )
            self.assertEqual(len(reports), 1)
            self.assertTrue(reports[0].valid)
            self.assertTrue(reports[0].visual_quality.scanned)
            self.assertIsNone(reports[0].audio_quality)  # This fixture intentionally has no audio stream.
            report = validate_rendered_mp4(
                result, FFMPEG, expected_width=96, expected_height=64,
                expected_fps=25, expected_duration_seconds=1.0,
                expect_audio=False,
            )
            self.assertTrue(report.valid)
            self.assertTrue(report.decode_succeeded)
            self.assertTrue(report.visual_quality.scanned)

    def test_pre_cancelled_render_preserves_existing_final_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            output = root / "final.mp4"
            self._make_mp4(source)
            original = b"previous-approved-export"
            output.write_bytes(original)
            project = TimelineProject(fps=25, width=96, height=64)
            project.add_clip(str(source), "Test shot", duration_frames=25)
            cancel = threading.Event()
            cancel.set()
            with self.assertRaises(RenderCancelledError):
                render_timeline_mp4(project, output, cancel_event=cancel)
            self.assertEqual(output.read_bytes(), original)
            self.assertFalse((root / "final.partial.mp4").exists())

    def test_real_multitrack_render_places_upper_video_only_during_its_timeline_range(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lower = root / "lower-red.mp4"
            upper = root / "upper-blue.mp4"
            output = root / "multitrack.mp4"
            for source, color in ((lower, "red"), (upper, "blue")):
                command = [
                    FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i",
                    f"color=c={color}:s=64x64:r=25:d=1",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-threads", "1", "-pix_fmt", "yuv420p", str(source),
                ]
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=45
                )
                self.assertEqual(result.returncode, 0, result.stderr[-2000:])

            project = TimelineProject(fps=25, width=64, height=64)
            project.add_clip(str(lower), "Lower red", track="V1",
                             start_frame=0, duration_frames=25)
            project.add_clip(str(upper), "Upper blue", track="V2",
                             start_frame=10, duration_frames=10)
            rendered = render_timeline_mp4(project, output, timeout_seconds=120)
            self.assertTrue(rendered.is_file())

            def sample_rgb(timestamp):
                command = [
                    FFMPEG, "-hide_banner", "-loglevel", "error",
                    "-ss", f"{timestamp:.3f}", "-i", str(rendered),
                    "-frames:v", "1", "-vf", "scale=1:1",
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
                ]
                result = subprocess.run(
                    command, capture_output=True, timeout=30, check=True
                )
                self.assertEqual(len(result.stdout), 3)
                return tuple(result.stdout)

            before_overlay = sample_rgb(0.20)
            during_overlay = sample_rgb(0.60)
            after_overlay = sample_rgb(0.90)
            self.assertGreater(before_overlay[0], before_overlay[2] * 2)
            self.assertGreater(during_overlay[2], during_overlay[0] * 2)
            self.assertGreater(after_overlay[0], after_overlay[2] * 2)

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
