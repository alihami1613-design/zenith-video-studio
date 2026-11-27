"""Tests for bounded local audio energy analysis."""
import array
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ai_editor.audio_energy import analyze_audio_energy


class AudioEnergyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.media = Path(self.temp.name) / "music.wav"
        self.media.write_bytes(b"fixture")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def pcm(samples):
        values = array.array("h", samples)
        if values.itemsize != 2:
            raise AssertionError("Test platform requires 16-bit signed shorts.")
        return values.tobytes()

    def test_builds_rms_envelope_and_transient_candidate(self):
        # 4 kHz, 100 ms windows: quiet, quiet, loud transient, quiet, quiet.
        samples = []
        for amplitude in (100, 100, 12000, 100, 100, 100):
            samples.extend([amplitude] * 400)
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return SimpleNamespace(stdout=self.pcm(samples))

        result = analyze_audio_energy(
            self.media, ffmpeg_executable="ffmpeg-test", run=fake_run
        )
        self.assertEqual(len(result.energy_envelope), 6)
        self.assertGreater(result.energy_envelope[2].rms, result.energy_envelope[0].rms)
        self.assertIn(0.2, result.transient_candidates_seconds)
        self.assertTrue(result.requires_user_review)
        self.assertTrue(any("not verified musical beats" in item for item in result.warnings))
        self.assertIn("-ac", captured["command"])
        self.assertIn("pipe:1", captured["command"])
        self.assertEqual(captured["kwargs"]["timeout"], 90)
        self.assertNotIn("upload", " ".join(captured["command"]).lower())

    def test_rejects_empty_and_oversized_pcm(self):
        def empty_run(*args, **kwargs):
            return SimpleNamespace(stdout=b"")
        with self.assertRaises(RuntimeError):
            analyze_audio_energy(self.media, ffmpeg_executable="ffmpeg-test", run=empty_run)

        def oversized_run(*args, **kwargs):
            return SimpleNamespace(stdout=b"\x00\x00" * (4000 * 2 + 1))
        with self.assertRaises(RuntimeError):
            analyze_audio_energy(
                self.media, max_duration_seconds=1,
                ffmpeg_executable="ffmpeg-test", run=oversized_run
            )

    def test_validates_resource_and_detection_parameters(self):
        for kwargs in (
            {"sample_rate": 100},
            {"window_seconds": 0.001},
            {"max_duration_seconds": 99999},
            {"minimum_candidate_spacing_seconds": 0.01},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                analyze_audio_energy(self.media, **kwargs)

    def test_missing_media_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            analyze_audio_energy(
                Path(self.temp.name) / "missing.wav",
                ffmpeg_executable="unused",
            )


if __name__ == "__main__":
    unittest.main()
