"""Small real-FFmpeg integration tests for transform-keyframed rendering."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from video_render import build_video_render_command

FFMPEG = shutil.which("ffmpeg")


@unittest.skipUnless(FFMPEG, "FFmpeg is required for render integration tests")
class TransformRenderIntegrationTests(unittest.TestCase):
    def test_keyframed_scale_rotation_and_position_render_successfully(self):
        with tempfile.TemporaryDirectory(prefix="zenith_transform_test_") as folder:
            root = Path(folder)
            source, output = root / "source.mp4", root / "transformed.mp4"
            generated = subprocess.run(
                [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=25:duration=2",
                 "-an", "-c:v", "libx264", "-preset", "ultrafast",
                 "-threads", "1", str(source)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            clip = SimpleNamespace(
                path=str(source), name="generated test", track="V1",
                clip_id="integration", media_type="video", start_frame=0,
                source_in=0, duration_frames=50, end_frame=50, color_grade={},
                anchor_x=0.25, anchor_y=0.75, playback_rate=0.5, motion_blur=True, reverse_playback=True,
                transform_keyframes=[
                    {"frame": 0, "x": -0.1, "y": 0.0, "scale": 1.0, "rotation": 0.0, "ease": "ease_in_out"},
                    {"frame": 25, "x": 0.1, "y": 0.05, "scale": 1.35, "rotation": 12.0, "ease": "linear"},
                ])
            project = SimpleNamespace(fps=25, width=96, height=64,
                                      duration_frames=50, clips=[clip])
            rendered = subprocess.run(
                build_video_render_command(FFMPEG, project, output),
                capture_output=True, text=True, timeout=60)
            self.assertEqual(rendered.returncode, 0, rendered.stderr[-3000:])
            self.assertGreater(output.stat().st_size, 0)
            decoded = subprocess.run(
                [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(output),
                 "-f", "null", "-"], capture_output=True, text=True, timeout=30)
            self.assertEqual(decoded.returncode, 0, decoded.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
