"""Tests for conservative H.264 timeline render command generation."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from video_render import build_video_render_command, validate_render_project


class VideoRenderTests(unittest.TestCase):
    def project(self, folder):
        first = Path(folder) / "one.mp4"
        second = Path(folder) / "two.mp4"
        first.touch()
        second.touch()
        a = SimpleNamespace(
            path=str(first), name="one", track="V1", clip_id="one",
            media_type="video", start_frame=0, source_in=30,
            duration_frames=60, end_frame=60,
            color_grade={"exposure": 1, "contrast": 1.2, "saturation": 1.1},
        )
        b = SimpleNamespace(
            path=str(second), name="two", track="V1", clip_id="two",
            media_type="video", start_frame=90, source_in=0,
            duration_frames=30, end_frame=120, color_grade={},
        )
        return SimpleNamespace(
            fps=30, width=1920, height=1080, duration_frames=120,
            clips=[a, b],
        )

    def test_builds_1080p_h264_with_grade_and_black_gap(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("scale=1920:1080:force_original_aspect_ratio=decrease", joined)
        self.assertIn("color=c=black:s=1920x1080:r=30:d=4.000000", joined)
        self.assertIn("enable='between(t,3.000000,4.000000)'", joined)
        self.assertIn("exposure=exposure=1.000", joined)
        self.assertIn("libx264", joined)
        self.assertIn("-crf 22", joined)
        self.assertIn("-threads 2", joined)
        self.assertIn("-pix_fmt yuv420p", joined)

    def test_rejects_multiple_video_tracks(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[1].track = "V2"
            with self.assertRaisesRegex(ValueError, "V1"):
                validate_render_project(project)

    def test_rejects_overlapping_v1_clips(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[1].start_frame = 50
            project.clips[1].end_frame = 80
            with self.assertRaisesRegex(ValueError, "هم‌پوشانی"):
                validate_render_project(project)

    def test_rejects_unsupported_frame_rate_and_missing_media(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.fps = 24
            with self.assertRaises(ValueError):
                validate_render_project(project)
            project.fps = 30
            project.clips[0].path = str(Path(folder) / "missing.mp4")
            with self.assertRaises(FileNotFoundError):
                validate_render_project(project)


if __name__ == "__main__":
    unittest.main()
