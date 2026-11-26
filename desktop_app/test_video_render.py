"""Tests for CPU-conscious multi-layer H.264 timeline render command generation."""
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
        self.assertIn("setpts=PTS+3.000000/TB", joined)
        self.assertIn("exposure=exposure=1.000", joined)
        self.assertIn("libx264", joined)
        self.assertIn("-crf 22", joined)
        self.assertIn("-threads 2", joined)
        self.assertIn("-filter_complex_threads 1", joined)
        self.assertIn("-pix_fmt yuv420p", joined)

    def test_renders_visual_fades_as_alpha_filters(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[0].video_fade_in_frames = 15
            project.clips[0].video_fade_out_frames = 30
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("fade=t=in:st=0:d=0.500000:alpha=1", joined)
        self.assertIn("fade=t=out:st=1.000000:d=1.000000:alpha=1", joined)

    def test_cross_dissolve_prerolls_incoming_clip_without_changing_timeline(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[1].start_frame = 60
            project.clips[1].end_frame = 90
            project.clips[1].transition_in_frames = 15
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("fade=t=in:st=0:d=0.500000:alpha=1", joined)
        self.assertIn("setpts=PTS+1.500000/TB", joined)
        self.assertEqual(project.duration_frames, 90)

    def test_rejects_cross_dissolve_without_adjacent_previous_clip(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[1].transition_in_frames = 15
            with self.assertRaisesRegex(ValueError, "چسبیده"):
                validate_render_project(project)

    def test_rejects_cross_dissolve_when_visual_fade_in_also_enabled(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[1].start_frame = 60
            project.clips[1].end_frame = 90
            project.clips[1].transition_in_frames = 15
            project.clips[1].video_fade_in_frames = 10
            with self.assertRaisesRegex(ValueError, "هم‌زمان"):
                validate_render_project(project)

    def test_rejects_visual_fade_longer_than_clip(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[0].video_fade_in_frames = 61
            with self.assertRaisesRegex(ValueError, "Fade تصویری"):
                validate_render_project(project)

    def test_composites_upper_track_over_lower_track(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            upper = Path(folder) / "upper.mp4"
            upper.touch()
            overlay = SimpleNamespace(
                path=str(upper), name="overlay", track="V2", clip_id="overlay",
                media_type="video", start_frame=30, source_in=0,
                duration_frames=30, end_frame=60, color_grade={},
            )
            project.clips.append(overlay)
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("setpts=PTS+1.000000/TB", joined)
        self.assertIn("[base1][v1]overlay", joined)
        self.assertIn("[base2][v2]overlay", joined)

    def test_allows_overlap_between_different_video_tracks(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[1].track = "V2"
            clips = validate_render_project(project)
            self.assertEqual(len(clips), 2)

    def test_rejects_overlap_on_same_track(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[1].start_frame = 50
            project.clips[1].end_frame = 80
            with self.assertRaisesRegex(ValueError, "هم‌پوشانی"):
                validate_render_project(project)

    def test_still_image_is_looped_for_its_timeline_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            image = Path(folder) / "still.png"
            image.touch()
            project.clips[0].path = str(image)
            project.clips[0].source_in = 0
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("-loop 1 -framerate 30 -t 2.000000", joined)
        self.assertIn("color=black@0", joined)

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
