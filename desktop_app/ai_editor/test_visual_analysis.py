"""Tests for bounded local frame sampling and cloud-analysis consent."""
import tempfile
import unittest
from pathlib import Path

from ai_editor.contracts import EditPlanError
from ai_editor.visual_analysis import (
    _jpeg_dimensions, analyze_video_visuals, sample_video_frames,
)


def minimal_jpeg(width=100, height=72):
    # SOF0 segment with one component; sufficient for dimension parsing.
    payload = bytes([8, height >> 8, height & 255, width >> 8, width & 255, 1, 1, 0x11, 0])
    return b"\\xff\\xd8\\xff\\xc0" + (len(payload) + 2).to_bytes(2, "big") + payload + b"\\xff\\xd9"


class RemoteAnalyzer:
    name = "remote-test"
    is_remote = True

    def describe_frames(self, frames):
        return ["A test frame"] * len(frames)


class VisualSamplingTests(unittest.TestCase):
    def test_jpeg_dimensions_are_read_without_imaging_dependency(self):
        self.assertEqual(_jpeg_dimensions(minimal_jpeg(320, 180)), (320, 180))

    def test_invalid_jpeg_is_rejected(self):
        with self.assertRaises(RuntimeError):
            _jpeg_dimensions(b"not jpeg")

    def test_sampling_is_bounded_and_uses_even_timestamps(self):
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "sample.mp4"
            media.write_bytes(b"placeholder")
            commands = []

            def fake_run(command, **kwargs):
                commands.append(command)
                Path(command[-1]).write_bytes(minimal_jpeg())
                return None

            frames = sample_video_frames(
                media, 12, sample_count=3, max_dimension=256,
                ffmpeg_executable="ffmpeg-test", run=fake_run,
            )
            self.assertEqual([round(frame.timestamp_seconds, 2) for frame in frames],
                             [2.0, 6.0, 10.0])
            self.assertEqual(len(commands), 3)
            self.assertEqual((frames[0].width, frames[0].height), (100, 72))
            self.assertIn("256", commands[0][commands[0].index("-vf") + 1])

    def test_remote_analysis_requires_explicit_consent(self):
        with self.assertRaises(EditPlanError):
            analyze_video_visuals(
                "/does/not/matter.mp4", 10, RemoteAnalyzer(),
                allow_cloud_media_analysis=False,
            )

    def test_sample_count_limits_are_enforced(self):
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "sample.mp4"
            media.write_bytes(b"placeholder")
            with self.assertRaises(EditPlanError):
                sample_video_frames(
                    media, 10, sample_count=25,
                    ffmpeg_executable="unused", run=lambda *a, **k: None,
                )


if __name__ == "__main__":
    unittest.main()
