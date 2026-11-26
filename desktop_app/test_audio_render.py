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
                                  media_type="video", has_audio=True, reverse_playback=True)
            command = build_audio_mix_command("ffmpeg", [clip], 30, "mix.wav")
        self.assertIn("areverse", " ".join(command))
if __name__ == "__main__":
    unittest.main()
