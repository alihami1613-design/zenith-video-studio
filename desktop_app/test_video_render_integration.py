"""Small real-FFmpeg integration tests for transform-keyframed rendering."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from video_render import build_video_render_command
from audio_render import build_audio_mix_command

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


    def test_ellipse_polygon_and_feather_masks_render_and_decode(self):
        with tempfile.TemporaryDirectory(prefix="zenith_mask_test_") as folder:
            root = Path(folder)
            source = root / "source.mp4"
            generated = subprocess.run(
                [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=25:duration=1",
                 "-an", "-c:v", "libx264", "-preset", "ultrafast",
                 "-threads", "1", str(source)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            for shape in ("ellipse", "polygon"):
                output = root / f"{shape}.mp4"
                clip = SimpleNamespace(
                    path=str(source), name="mask test", track="V1",
                    clip_id=shape, media_type="video", start_frame=0,
                    source_in=0, duration_frames=25, end_frame=25,
                    color_grade={}, mask_enabled=True, mask_shape=shape,
                    mask_x=0.1, mask_y=0.1, mask_width=0.8, mask_height=0.8,
                    mask_feather_px=2.0, mask_rotation=18.0,
                    mask_points=[[0.5, 0.05], [0.95, 0.9], [0.05, 0.9]],
                )
                project = SimpleNamespace(
                    fps=25, width=96, height=64, duration_frames=25, clips=[clip]
                )
                rendered = subprocess.run(
                    build_video_render_command(FFMPEG, project, output),
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(rendered.returncode, 0, rendered.stderr[-3000:])
                self.assertGreater(output.stat().st_size, 0)
                decoded = subprocess.run(
                    [FFMPEG, "-hide_banner", "-loglevel", "error",
                     "-i", str(output), "-f", "null", "-"],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(decoded.returncode, 0, decoded.stderr[-2000:])

    def test_animated_mask_shapes_render_and_decode(self):
        with tempfile.TemporaryDirectory(prefix="zenith_animated_mask_test_") as folder:
            root = Path(folder)
            source = root / "source.mp4"
            generated = subprocess.run(
                [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=25:duration=1",
                 "-an", "-c:v", "libx264", "-preset", "ultrafast",
                 "-threads", "1", str(source)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            for shape in ("rectangle", "ellipse", "polygon"):
                output = root / f"animated_{shape}.mp4"
                clip = SimpleNamespace(
                    path=str(source), name="animated mask", track="V1",
                    clip_id=shape, media_type="video", start_frame=0,
                    source_in=0, duration_frames=25, end_frame=25,
                    color_grade={}, mask_enabled=True, mask_shape=shape,
                    mask_x=0.0, mask_y=0.0, mask_width=1.0, mask_height=1.0,
                    mask_feather_px=1.5,
                    mask_points=[[0.5, 0.1], [0.9, 0.9], [0.1, 0.9]],
                    mask_keyframes=[
                        {"frame": 0, "x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0,
                         "rotation": -8.0},
                        {"frame": 20, "x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8,
                         "rotation": 27.0},
                    ],
                )
                project = SimpleNamespace(
                    fps=25, width=96, height=64, duration_frames=25, clips=[clip]
                )
                rendered = subprocess.run(
                    build_video_render_command(FFMPEG, project, output),
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(rendered.returncode, 0, rendered.stderr[-3500:])
                self.assertGreater(output.stat().st_size, 0)
                decoded = subprocess.run(
                    [FFMPEG, "-hide_banner", "-loglevel", "error",
                     "-i", str(output), "-f", "null", "-"],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(decoded.returncode, 0, decoded.stderr[-2000:])

    def test_speed_ramp_renders_video_and_matching_embedded_audio(self):
        with tempfile.TemporaryDirectory(prefix="zenith_speed_ramp_test_") as folder:
            root = Path(folder)
            source = root / "source_with_audio.mp4"
            picture = root / "ramped_picture.mp4"
            mixed_audio = root / "ramped_audio.wav"
            generated = subprocess.run(
                [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=25:duration=4",
                 "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
                 "-map", "0:v:0", "-map", "1:a:0",
                 "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1",
                 "-c:a", "aac", "-shortest", str(source)],
                capture_output=True, text=True, timeout=45)
            self.assertEqual(generated.returncode, 0, generated.stderr[-2500:])
            clip = SimpleNamespace(
                path=str(source), name="ramped clip", track="V1", clip_id="ramped",
                media_type="video", start_frame=0, source_in=0, duration_frames=50,
                end_frame=50, color_grade={}, playback_rate=1.0,
                reverse_playback=False, speed_ramp=[
                    {"frame": 0, "rate": 0.5}, {"frame": 49, "rate": 2.0}
                ],
                has_audio=True, audio_track="A1", volume=1.0,
                fade_in_frames=0, fade_out_frames=0,
            )
            project = SimpleNamespace(
                fps=25, width=96, height=64, duration_frames=50, clips=[clip]
            )
            rendered_video = subprocess.run(
                build_video_render_command(FFMPEG, project, picture),
                capture_output=True, text=True, timeout=60)
            self.assertEqual(rendered_video.returncode, 0, rendered_video.stderr[-3500:])
            audio_command = build_audio_mix_command(
                FFMPEG, [clip], 25, mixed_audio, timeline_duration_frames=50
            )
            rendered_audio = subprocess.run(
                audio_command, capture_output=True, text=True, timeout=60)
            self.assertEqual(rendered_audio.returncode, 0, rendered_audio.stderr[-3500:])
            for output in (picture, mixed_audio):
                self.assertGreater(output.stat().st_size, 0)
                decoded = subprocess.run(
                    [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(output),
                     "-f", "null", "-"],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(decoded.returncode, 0, decoded.stderr[-2500:])

    def test_final_mp4_renders_picture_transition_and_embedded_audio_together(self):
        from video_render import render_timeline_mp4

        with tempfile.TemporaryDirectory(prefix="zenith_final_mp4_test_") as folder:
            root = Path(folder)
            sources = []
            for name, color, frequency in (
                ("outgoing", "red", 440),
                ("incoming", "blue", 880),
            ):
                source = root / f"{name}.mp4"
                generated = subprocess.run(
                    [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                     "-f", "lavfi", "-i",
                     f"color=c={color}:size=96x64:rate=25:duration=4",
                     "-f", "lavfi", "-i",
                     f"sine=frequency={frequency}:sample_rate=48000:duration=4",
                     "-map", "0:v:0", "-map", "1:a:0",
                     "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1",
                     "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                     str(source)],
                    capture_output=True, text=True, timeout=45,
                )
                self.assertEqual(generated.returncode, 0, generated.stderr[-2500:])
                sources.append(source)

            outgoing = SimpleNamespace(
                path=str(sources[0]), name="outgoing", track="V1",
                clip_id="outgoing", media_type="video", start_frame=0,
                source_in=0, duration_frames=75, end_frame=75,
                color_grade={}, has_audio=True, audio_track="A1",
                volume=1.0, fade_in_frames=0, fade_out_frames=0,
                playback_rate=1.0, reverse_playback=False, speed_ramp=[],
                transition_in_frames=0, video_fade_in_frames=0,
                video_fade_out_frames=0,
            )
            incoming = SimpleNamespace(
                path=str(sources[1]), name="incoming", track="V1",
                clip_id="incoming", media_type="video", start_frame=75,
                source_in=15, duration_frames=75, end_frame=150,
                color_grade={}, has_audio=True, audio_track="A1",
                volume=1.0, fade_in_frames=0, fade_out_frames=0,
                playback_rate=1.0, reverse_playback=False, speed_ramp=[],
                transition_in_frames=15, transition_in_type="dissolve",
                video_fade_in_frames=0, video_fade_out_frames=0,
            )
            project = SimpleNamespace(
                fps=25, width=96, height=64, duration_frames=150,
                clips=[outgoing, incoming],
                audio_track_settings={}, audio_ducking={},
            )
            output = root / "final.mp4"
            reports = []
            rendered = render_timeline_mp4(
                project, output, timeout_seconds=120,
                validation_callback=reports.append,
            )
            self.assertEqual(rendered, output.resolve())
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 0)
            self.assertEqual(len(reports), 1)
            report = reports[0]
            self.assertTrue(report.valid)
            self.assertTrue(report.decode_succeeded)
            self.assertTrue(report.has_video)
            self.assertTrue(report.has_audio)
            self.assertEqual((report.width, report.height), (96, 64))
            self.assertAlmostEqual(report.fps, 25.0, delta=0.05)
            self.assertAlmostEqual(report.duration_seconds, 6.0, delta=0.15)

            decoded = subprocess.run(
                [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(output),
                 "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
                capture_output=True, text=True, timeout=45,
            )
            self.assertEqual(decoded.returncode, 0, decoded.stderr[-2500:])

            # The final mux must retain audible program material throughout
            # the picture dissolve and after the incoming clip takes over.
            import math
            import struct
            for start, end in ((2.55, 2.75), (3.35, 3.55)):
                measured = subprocess.run(
                    [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(output),
                     "-ss", str(start), "-t", str(end - start), "-vn",
                     "-ac", "1", "-ar", "8000", "-f", "s16le",
                     "-acodec", "pcm_s16le", "pipe:1"],
                    capture_output=True, timeout=30,
                )
                self.assertEqual(measured.returncode, 0, measured.stderr[-1500:])
                usable_bytes = len(measured.stdout) - (len(measured.stdout) % 2)
                self.assertGreater(usable_bytes, 0)
                samples = struct.unpack("<" + "h" * (usable_bytes // 2),
                                        measured.stdout[:usable_bytes])
                rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768.0
                self.assertGreater(rms, 0.0178, f"Audio RMS too low at {start:.2f}s: {rms:.6f}")


if __name__ == "__main__":
    unittest.main()
