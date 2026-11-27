"""Tests for non-destructive FFmpeg audio mix command generation."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from audio_render import build_audio_mix_command


class AudioRenderCommandTests(unittest.TestCase):
    def make_clip(self, path, **changes):
        values = {
            "path": str(path), "name": "voice.wav", "track": "A1",
            "clip_id": "clip-a", "media_type": "audio",
            "start_frame": 90, "source_in": 30, "duration_frames": 300,
            "end_frame": 390, "volume": 0.8,
            "fade_in_frames": 30, "fade_out_frames": 60,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def test_builds_gain_fades_source_trim_and_timeline_delay(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "voice.wav"
            source.touch()
            output = Path(folder) / "mix.wav"
            command = build_audio_mix_command(
                "ffmpeg", [self.make_clip(source)], 30, output, 450
            )
        joined = " ".join(command)
        self.assertIn("atrim=start=1.000000:duration=10.000000", joined)
        self.assertIn("volume=0.8000", joined)
        self.assertIn("afade=t=in:st=0:d=1.000000", joined)
        self.assertIn("afade=t=out:st=8.000000:d=2.000000", joined)
        self.assertIn("adelay=3000:all=1", joined)
        self.assertIn("amix=inputs=1", joined)
        self.assertIn("alimiter=limit=0.95", joined)
        self.assertIn("atrim=duration=15.000000", joined)
        self.assertIn("pcm_s16le", joined)

    def test_rejects_empty_audio_tracks(self):
        with self.assertRaises(ValueError):
            build_audio_mix_command("ffmpeg", [], 30, "out.wav")

    def test_rejects_missing_source(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing.wav"
            with self.assertRaises(FileNotFoundError):
                build_audio_mix_command(
                    "ffmpeg", [self.make_clip(missing)], 30, "out.wav"
                )

    def test_rejects_invalid_fade_length(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "voice.wav"
            source.touch()
            clip = self.make_clip(source, fade_in_frames=301)
            with self.assertRaises(ValueError):
                build_audio_mix_command("ffmpeg", [clip], 30, "out.wav")

    def test_applies_per_track_gain_and_mute(self):
        with tempfile.TemporaryDirectory() as folder:
            voice = Path(folder) / "voice.wav"
            music = Path(folder) / "music.wav"
            voice.touch()
            music.touch()
            clips = [
                self.make_clip(voice, clip_id="voice", track="A1"),
                self.make_clip(music, clip_id="music", track="A2"),
            ]
            command = build_audio_mix_command(
                "ffmpeg", clips, 30, "mix.wav",
                audio_track_settings={
                    "A1": {"volume": 0.7, "muted": False, "solo": False},
                    "A2": {"volume": 0.4, "muted": True, "solo": False},
                },
            )
        joined = " ".join(command)
        self.assertIn("volume=0.7000", joined)
        self.assertNotIn("music.wav", joined)
        self.assertIn("amix=inputs=1", joined)

    def test_solo_keeps_only_solo_track(self):
        with tempfile.TemporaryDirectory() as folder:
            voice = Path(folder) / "voice.wav"
            music = Path(folder) / "music.wav"
            voice.touch()
            music.touch()
            clips = [
                self.make_clip(voice, clip_id="voice", track="A1"),
                self.make_clip(music, clip_id="music", track="A2"),
            ]
            command = build_audio_mix_command(
                "ffmpeg", clips, 30, "mix.wav",
                audio_track_settings={
                    "A1": {"volume": 1.0, "muted": False, "solo": True},
                    "A2": {"volume": 1.0, "muted": False, "solo": False},
                },
            )
        joined = " ".join(command)
        self.assertIn("voice.wav", joined)
        self.assertNotIn("music.wav", joined)

    def test_rejects_all_muted_tracks(self):
        with tempfile.TemporaryDirectory() as folder:
            voice = Path(folder) / "voice.wav"
            voice.touch()
            with self.assertRaises(ValueError):
                build_audio_mix_command(
                    "ffmpeg", [self.make_clip(voice)], 30, "mix.wav",
                    audio_track_settings={
                        "A1": {"volume": 1.0, "muted": True, "solo": False}
                    },
                )

    def test_ducking_applies_voice_sidechain_to_music_track(self):
        with tempfile.TemporaryDirectory() as folder:
            voice = Path(folder) / "voice.wav"
            music = Path(folder) / "music.wav"
            voice.touch()
            music.touch()
            clips = [
                self.make_clip(voice, clip_id="voice", track="A1"),
                self.make_clip(music, clip_id="music", track="A2"),
            ]
            command = build_audio_mix_command(
                "ffmpeg", clips, 30, "mix.wav",
                audio_ducking={
                    "enabled": True, "voice_track": "A1", "music_track": "A2",
                    "reduction_db": 12, "attack_ms": 20, "release_ms": 500,
                },
            )
        joined = " ".join(command)
        self.assertIn("sidechaincompress=threshold=0.025", joined)
        self.assertIn("attack=20:release=500", joined)
        self.assertIn("[track1][track0]", joined)
        self.assertIn("[musicducked]", joined)

    def test_ducking_rejects_same_or_unavailable_track(self):
        with tempfile.TemporaryDirectory() as folder:
            voice = Path(folder) / "voice.wav"
            music = Path(folder) / "music.wav"
            voice.touch()
            music.touch()
            clips = [
                self.make_clip(voice, clip_id="voice", track="A1"),
                self.make_clip(music, clip_id="music", track="A2"),
            ]
            with self.assertRaises(ValueError):
                build_audio_mix_command(
                    "ffmpeg", clips, 30, "mix.wav",
                    audio_ducking={
                        "enabled": True, "voice_track": "A1", "music_track": "A1"
                    },
                )
            with self.assertRaises(ValueError):
                build_audio_mix_command(
                    "ffmpeg", clips, 30, "mix.wav",
                    audio_track_settings={
                        "A1": {"volume": 1.0, "muted": True, "solo": False}
                    },
                    audio_ducking={
                        "enabled": True, "voice_track": "A1", "music_track": "A2"
                    },
                )

    def test_includes_embedded_video_audio_on_selected_audio_bus(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "camera.mp4"
            source.touch()
            clip = self.make_clip(
                source, clip_id="camera", track="V1", media_type="video",
                has_audio=True, audio_track="A3",
            )
            command = build_audio_mix_command("ffmpeg", [clip], 30, "mix.wav")
        joined = " ".join(command)
        self.assertIn("camera.mp4", joined)
        self.assertIn("[0:a:0]", joined)
        self.assertIn("track0", joined)

    def test_sorts_clips_by_timeline_position(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "first.wav"
            second = Path(folder) / "second.wav"
            first.touch()
            second.touch()
            late = self.make_clip(second, clip_id="late", start_frame=120)
            early = self.make_clip(first, clip_id="early", start_frame=0)
            command = build_audio_mix_command(
                "ffmpeg", [late, early], 30, "out.wav"
            )
        inputs = [command[i + 1] for i, value in enumerate(command[:-1]) if value == "-i"]
        self.assertEqual(inputs, [str(first), str(second)])


    def test_embedded_video_audio_uses_same_slow_motion_rate(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "slow-camera.mp4"
            source.touch()
            clip = self.make_clip(
                source, clip_id="slow-camera", track="V1", media_type="video",
                has_audio=True, audio_track="A2", playback_rate=0.5,
            )
            command = build_audio_mix_command("ffmpeg", [clip], 30, "mix.wav")
        joined = " ".join(command)
        self.assertIn("atrim=start=1.000000:duration=5.000000", joined)
        self.assertIn("atempo=0.500000", joined)


    def test_reverse_embedded_audio_is_reversed(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "reverse-camera.mp4"
            source.touch()
            clip = self.make_clip(source, clip_id="reverse-camera", track="V1",
                                  media_type="video", has_audio=True, audio_track="A1",
                                  reverse_playback=True)
            command = build_audio_mix_command("ffmpeg", [clip], 30, "mix.wav")
        self.assertIn("areverse", " ".join(command))

    def test_embedded_video_audio_uses_same_speed_ramp_segments(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "ramped-camera.mp4"
            source.touch()
            clip = self.make_clip(
                source, clip_id="ramped-camera", track="V1", media_type="video",
                has_audio=True, audio_track="A1", duration_frames=60,
            )
            clip.speed_ramp = [
                {"frame": 0, "rate": 0.5}, {"frame": 59, "rate": 2.0}
            ]
            command = build_audio_mix_command("ffmpeg", [clip], 30, "mix.wav")
        joined = " ".join(command)
        self.assertIn("asplit=11", joined)
        self.assertIn("concat=n=11:v=0:a=1", joined)
        self.assertIn("atempo=0.575000", joined)
        self.assertIn("atempo=2.000000", joined)
        self.assertNotIn("areverse", joined)

    def test_ffmpeg_progress_output_is_wired_when_requested(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "voice.wav"
            source.touch()
            progress = Path(folder) / "audio.progress"
            command = build_audio_mix_command(
                "ffmpeg", [self.make_clip(source)], 30, "mix.wav", 450,
                progress_path=progress,
            )
        self.assertIn("-progress", command)
        self.assertIn(str(progress), command)
        self.assertIn("-nostats", command)


    def test_overlapping_clips_on_same_track_get_equal_power_crossfade(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "first.wav"
            second = Path(folder) / "second.wav"
            first.touch()
            second.touch()
            outgoing = self.make_clip(
                first, clip_id="outgoing", track="A1", audio_track="A1",
                start_frame=0, duration_frames=120, end_frame=120,
                fade_in_frames=0, fade_out_frames=0,
            )
            incoming = self.make_clip(
                second, clip_id="incoming", track="A1", audio_track="A1",
                start_frame=90, duration_frames=120, end_frame=210,
                fade_in_frames=0, fade_out_frames=0,
            )
            command = build_audio_mix_command(
                "ffmpeg", [outgoing, incoming], 30, "mix.wav", 210
            )
        joined = " ".join(command)
        self.assertIn("afade=t=out:st=3.000000:d=1.000000:curve=iqsin", joined)
        self.assertIn("afade=t=in:st=0:d=1.000000:curve=qsin", joined)

    def test_non_overlapping_clips_do_not_get_automatic_crossfade(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "first.wav"
            second = Path(folder) / "second.wav"
            first.touch()
            second.touch()
            outgoing = self.make_clip(
                first, clip_id="outgoing", track="A1", audio_track="A1",
                start_frame=0, duration_frames=90, end_frame=90,
                fade_in_frames=0, fade_out_frames=0,
            )
            incoming = self.make_clip(
                second, clip_id="incoming", track="A1", audio_track="A1",
                start_frame=90, duration_frames=90, end_frame=180,
                fade_in_frames=0, fade_out_frames=0,
            )
            command = build_audio_mix_command(
                "ffmpeg", [outgoing, incoming], 30, "mix.wav", 180
            )
        joined = " ".join(command)
        self.assertNotIn("curve=qsin", joined)
        self.assertNotIn("curve=iqsin", joined)


    def test_ffmpeg_renders_real_crossfade_with_stable_overlap_level(self):
        import math
        import shutil
        import subprocess
        import wave

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("FFmpeg is not installed")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / "first.wav"
            second = root / "second.wav"
            output = root / "crossfade.wav"
            for path, frequency in ((first, 440), (second, 880)):
                subprocess.run(
                    [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                     f"sine=frequency={frequency}:duration=3:sample_rate=48000",
                     "-c:a", "pcm_s16le", str(path)],
                    check=True, timeout=30,
                )
            outgoing = self.make_clip(
                first, clip_id="outgoing", track="A1", audio_track="A1",
                start_frame=0, source_in=0, duration_frames=90, end_frame=90,
                volume=1.0, fade_in_frames=0, fade_out_frames=0,
            )
            incoming = self.make_clip(
                second, clip_id="incoming", track="A1", audio_track="A1",
                start_frame=60, source_in=0, duration_frames=90, end_frame=150,
                volume=1.0, fade_in_frames=0, fade_out_frames=0,
            )
            command = build_audio_mix_command(
                ffmpeg, [outgoing, incoming], 30, output, 150
            )
            subprocess.run(command, check=True, timeout=60)

            with wave.open(str(output), "rb") as rendered:
                self.assertEqual(rendered.getframerate(), 48000)
                self.assertEqual(rendered.getnchannels(), 2)
                frames = rendered.readframes(rendered.getnframes())

            def rms_at(seconds, window=0.2):
                start = int(seconds * 48000) * 2
                count = int(window * 48000) * 2
                samples = memoryview(frames)[start * 2:(start + count) * 2]
                values = [int.from_bytes(samples[i:i + 2], "little", signed=True)
                          for i in range(0, len(samples), 2)]
                return math.sqrt(sum(value * value for value in values) / max(1, len(values)))

            before = rms_at(1.5)
            overlap_start = rms_at(2.05)
            overlap_middle = rms_at(2.5)
            overlap_end = rms_at(2.85)
            after = rms_at(3.5)
            # FFmpeg's lavfi sine source defaults to a conservative 0.125
            # peak amplitude, so validate against its measured baseline rather
            # than an arbitrary high absolute RMS threshold.
            self.assertGreater(before, 1500)
            self.assertGreater(after, 1500)
            self.assertGreater(overlap_middle, 1500)
            self.assertGreater(overlap_start, before * 0.45)
            self.assertGreater(overlap_end, after * 0.45)
            self.assertLess(abs(overlap_middle - before) / before, 0.35)
            self.assertLess(abs(overlap_middle - after) / after, 0.35)


if __name__ == "__main__":
    unittest.main()
