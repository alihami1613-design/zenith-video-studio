"""Tests for local FFmpeg audio diagnostics."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ai_editor.audio_analysis import analyze_audio, SilenceInterval


class AudioAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.media = Path(self.temp.name) / "voice.wav"
        self.media.write_bytes(b"fixture")

    def tearDown(self):
        self.temp.cleanup()

    def test_parses_silence_and_volume_without_uploading_media(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return SimpleNamespace(stderr=(
                b"[silencedetect] silence_start: 1.250\n"
                b"[silencedetect] silence_end: 2.500 | silence_duration: 1.250\n"
                b"[Parsed_volumedetect] mean_volume: -21.4 dB\n"
                b"[Parsed_volumedetect] max_volume: -2.1 dB\n"
            ))

        result = analyze_audio(
            self.media, ffmpeg_executable="ffmpeg-test", run=fake_run
        )
        self.assertEqual(result.silence_intervals, (SilenceInterval(1.25, 2.5),))
        self.assertEqual(result.mean_db, -21.4)
        self.assertEqual(result.peak_db, -2.1)
        self.assertIn("-af", captured["command"])
        self.assertEqual(captured["kwargs"]["timeout"], 120)
        self.assertNotIn("upload", " ".join(captured["command"]).lower())

    def test_infinite_volume_is_reported_as_unknown(self):
        def fake_run(*args, **kwargs):
            return SimpleNamespace(stderr=b"mean_volume: -inf dB\nmax_volume: -inf dB\n")
        result = analyze_audio(self.media, ffmpeg_executable="ffmpeg-test", run=fake_run)
        self.assertIsNone(result.mean_db)
        self.assertIsNone(result.peak_db)

    def test_rejects_unsafe_thresholds(self):
        with self.assertRaises(ValueError):
            analyze_audio(self.media, silence_threshold_db=-120)
        with self.assertRaises(ValueError):
            analyze_audio(self.media, minimum_silence_seconds=0)

    def test_missing_media_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            analyze_audio(Path(self.temp.name) / "missing.wav", ffmpeg_executable="unused")


if __name__ == "__main__":
    unittest.main()
