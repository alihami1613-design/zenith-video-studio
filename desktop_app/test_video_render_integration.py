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


    def test_final_mp4_composites_video_layers_and_mixes_independent_audio_tracks(self):
        from video_render import render_timeline_mp4

        with tempfile.TemporaryDirectory(prefix="zenith_multilayer_final_test_") as folder:
            root = Path(folder)
            base = root / "base_red.mp4"
            overlay = root / "overlay_green_blue.mp4"
            narration = root / "narration_440.wav"
            music = root / "music_880.wav"

            base_result = subprocess.run(
                [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "color=c=red:size=128x96:rate=25:duration=4",
                 "-an", "-c:v", "libx264", "-preset", "ultrafast",
                 "-threads", "1", "-pix_fmt", "yuv420p", str(base)],
                capture_output=True, text=True, timeout=45,
            )
            self.assertEqual(base_result.returncode, 0, base_result.stderr[-2000:])

            overlay_result = subprocess.run(
                [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i",
                 "color=c=blue:size=128x96:rate=25:duration=4,drawbox=x=0:y=0:w=64:h=96:color=green:t=fill",
                 "-an", "-c:v", "libx264", "-preset", "ultrafast",
                 "-threads", "1", "-pix_fmt", "yuv420p", str(overlay)],
                capture_output=True, text=True, timeout=45,
            )
            self.assertEqual(overlay_result.returncode, 0, overlay_result.stderr[-2000:])

            for target, frequency in ((narration, 440), (music, 880)):
                audio_result = subprocess.run(
                    [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                     "-f", "lavfi", "-i",
                     f"sine=frequency={frequency}:sample_rate=48000:duration=4",
                     "-c:a", "pcm_s16le", str(target)],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(audio_result.returncode, 0, audio_result.stderr[-1500:])

            def clip(path_value, name, track, media_type, *, has_audio=False,
                     audio_track=None, chroma=False):
                return SimpleNamespace(
                    path=str(path_value), name=name, track=track,
                    clip_id=name, media_type=media_type,
                    start_frame=0, source_in=0, duration_frames=100,
                    end_frame=100, color_grade={}, has_audio=has_audio,
                    audio_track=audio_track or track, volume=1.0,
                    fade_in_frames=0, fade_out_frames=0,
                    video_fade_in_frames=0, video_fade_out_frames=0,
                    transition_in_frames=0, playback_rate=1.0,
                    reverse_playback=False, speed_ramp=[],
                    chroma_key_enabled=chroma,
                    chroma_key_color="#00FF00",
                    chroma_key_similarity=0.45,
                    chroma_key_blend=0.02,
                )

            clips = [
                clip(base, "base-picture", "V1", "video"),
                clip(overlay, "top-overlay", "V2", "video", chroma=True),
                clip(narration, "narration", "A1", "audio"),
                clip(music, "music", "A2", "audio"),
            ]
            project = SimpleNamespace(
                fps=25, width=128, height=96, duration_frames=100,
                clips=clips,
                audio_track_settings={
                    "A1": {"volume": 1.0, "muted": False, "solo": False},
                    "A2": {"volume": 0.5, "muted": False, "solo": False},
                },
                audio_ducking={},
            )
            output = root / "multilayer_final.mp4"
            reports = []
            rendered = render_timeline_mp4(
                project, output, timeout_seconds=120,
                validation_callback=reports.append,
            )
            self.assertEqual(rendered, output.resolve())
            self.assertTrue(output.is_file())
            self.assertEqual(len(reports), 1)
            self.assertTrue(reports[0].valid)
            self.assertTrue(reports[0].decode_succeeded)
            self.assertTrue(reports[0].has_audio)
            self.assertAlmostEqual(reports[0].duration_seconds, 4.0, delta=0.15)

            # Decode one composited frame: left side must reveal V1 through
            # the keyed green area; right side must show the blue V2 overlay.
            frame = subprocess.run(
                [FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", "1.0",
                 "-i", str(output), "-frames:v", "1", "-f", "rawvideo",
                 "-pix_fmt", "rgb24", "pipe:1"],
                capture_output=True, timeout=30,
            )
            self.assertEqual(frame.returncode, 0, frame.stderr[-1500:])
            self.assertEqual(len(frame.stdout), 128 * 96 * 3)
            left_index = (48 * 128 + 24) * 3
            right_index = (48 * 128 + 96) * 3
            left_rgb = tuple(frame.stdout[left_index:left_index + 3])
            right_rgb = tuple(frame.stdout[right_index:right_index + 3])
            self.assertGreater(left_rgb[0], left_rgb[1] * 1.5,
                               f"V1 base should show through chroma key, got {left_rgb}")
            self.assertGreater(right_rgb[2], right_rgb[0] * 1.5,
                               f"V2 blue overlay should be on top, got {right_rgb}")

            # Both independent audio tracks must survive the final mix.
            import math
            import struct
            audio = subprocess.run(
                [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(output),
                 "-ss", "1.0", "-t", "2.0", "-vn", "-ac", "1", "-ar", "8000",
                 "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1"],
                capture_output=True, timeout=30,
            )
            self.assertEqual(audio.returncode, 0, audio.stderr[-1500:])
            sample_bytes = len(audio.stdout) - (len(audio.stdout) % 2)
            self.assertGreater(sample_bytes, 0)
            samples = struct.unpack("<" + "h" * (sample_bytes // 2),
                                     audio.stdout[:sample_bytes])
            count = len(samples)
            self.assertGreater(count, 8000)
            def spectral_power(frequency):
                real = 0.0
                imag = 0.0
                for index, sample in enumerate(samples):
                    angle = 2.0 * math.pi * frequency * index / 8000.0
                    real += sample * math.cos(angle)
                    imag -= sample * math.sin(angle)
                return real * real + imag * imag
            self.assertGreater(spectral_power(440), 1.0e12,
                               "Narration track tone missing from final mix")
            self.assertGreater(spectral_power(880), 1.0e11,
                               "Music track tone missing from final mix")


if __name__ == "__main__":
    unittest.main()
