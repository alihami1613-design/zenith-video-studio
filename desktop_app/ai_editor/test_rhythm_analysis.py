"""Tests for conservative RMS-envelope music pulse estimation."""
import unittest

from ai_editor.audio_energy import AudioEnergyAnalysis, AudioEnergyPoint
from ai_editor.rhythm_analysis import analyze_music_rhythm


def make_energy(duration=24.0, window=0.05, pulse_period=0.5):
    points = []
    count = int(duration / window)
    for index in range(count):
        time = index * window
        phase = (time % pulse_period) / window
        # A short, repeatable rise followed by decay, sampled at 50 ms.
        distance = min(phase, pulse_period / window - phase)
        level = 0.08 + 0.65 * max(0.0, 1.0 - distance / 2.0)
        points.append(AudioEnergyPoint(time, level, -20.0))
    return AudioEnergyAnalysis(
        sample_rate=4000, window_seconds=window,
        analyzed_duration_seconds=duration,
        energy_envelope=tuple(points),
        transient_candidates_seconds=(),
        warnings=(),
    )


class RhythmAnalysisTests(unittest.TestCase):
    def test_estimates_repeating_energy_pulse_near_120_bpm(self):
        result = analyze_music_rhythm(make_energy())
        self.assertIsNotNone(result.estimated_bpm)
        self.assertAlmostEqual(result.estimated_bpm, 120.0, delta=8.0)
        self.assertGreaterEqual(result.confidence, 0.18)
        self.assertGreater(len(result.pulse_candidates_seconds), 10)
        self.assertTrue(result.requires_user_review)
        self.assertTrue(any("not spectral beat tracking" in warning for warning in result.warnings))

    def test_short_or_flat_envelope_does_not_invent_tempo(self):
        short = make_energy(duration=1.0)
        result = analyze_music_rhythm(short)
        self.assertIsNone(result.estimated_bpm)
        flat = AudioEnergyAnalysis(
            sample_rate=4000, window_seconds=0.1,
            analyzed_duration_seconds=10.0,
            energy_envelope=tuple(
                AudioEnergyPoint(i * 0.1, 0.2, -14.0) for i in range(100)
            ),
            transient_candidates_seconds=(), warnings=(),
        )
        result = analyze_music_rhythm(flat)
        self.assertIsNone(result.estimated_bpm)
        self.assertEqual(result.pulse_candidates_seconds, ())

    def test_rejects_invalid_inputs_and_bpm_ranges(self):
        with self.assertRaises(TypeError):
            analyze_music_rhythm({})
        energy = make_energy()
        with self.assertRaises(ValueError):
            analyze_music_rhythm(energy, minimum_bpm=160, maximum_bpm=70)
        with self.assertRaises(ValueError):
            analyze_music_rhythm(energy, minimum_confidence=float("nan"))


if __name__ == "__main__":
    unittest.main()
