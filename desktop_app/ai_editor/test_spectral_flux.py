"""Synthetic and safety tests for local spectral-flux analysis."""
import array
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ai_editor.spectral_flux import analyze_spectral_flux


class SpectralFluxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.media = Path(self.temp.name) / "synthetic.wav"
        self.media.write_bytes(b"fixture")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def make_pcm(duration=12.0, sample_rate=8000, bpm=120):
        values = array.array("h")
        period = 60.0 / bpm
        for index in range(int(duration * sample_rate)):
            time = index / sample_rate
            phase = time % period
            envelope = math.exp(-phase * 35.0) if phase < 0.12 else 0.0
            sample = int(18000 * envelope * math.sin(2 * math.pi * 110 * time))
            values.append(sample)
        return values.tobytes()

    def test_detects_spectral_onsets_and_periodic_pulse(self):
        pcm = self.make_pcm()
        result = analyze_spectral_flux(
            self.media, ffmpeg_executable="ffmpeg-test",
            run=lambda *a, **k: SimpleNamespace(stdout=pcm),
        )
        self.assertGreater(len(result.onset_envelope), 10)
        self.assertGreater(len(result.onset_candidates_seconds), 5)
        self.assertIsNotNone(result.estimated_bpm)
        self.assertAlmostEqual(result.estimated_bpm, 120.0, delta=12.0)
        self.assertTrue(result.requires_user_review)
        self.assertTrue(any("does not understand musical structure" in w for w in result.warnings))

    def test_rejects_empty_oversized_and_invalid_settings(self):
        empty = lambda *a, **k: SimpleNamespace(stdout=b"")
        with self.assertRaises(RuntimeError):
            analyze_spectral_flux(self.media, ffmpeg_executable="ffmpeg-test", run=empty)
        oversized = lambda *a, **k: SimpleNamespace(stdout=b"\x00\x00" * (8000 * 6 + 1))
        with self.assertRaises(RuntimeError):
            analyze_spectral_flux(
                self.media, max_duration_seconds=5,
                ffmpeg_executable="ffmpeg-test", run=oversized,
            )
        with self.assertRaises(ValueError):
            analyze_spectral_flux(self.media, frame_size=300)

    def test_missing_media_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            analyze_spectral_flux(
                Path(self.temp.name) / "missing.wav",
                ffmpeg_executable="unused",
            )


if __name__ == "__main__":
    unittest.main()
