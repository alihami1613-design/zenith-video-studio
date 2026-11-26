"""Unit tests for compact waveform envelope extraction and cache paths."""
import tempfile
import unittest
from pathlib import Path

from waveform_manager import peak_envelope, waveform_cache_path


class WaveformManagerTests(unittest.TestCase):
    def test_peak_envelope_groups_samples_and_normalizes(self):
        import array
        pcm = array.array("f", [0.1, -0.8, 0.2, 0.1, 0.3, -0.4, 0.2]).tobytes()
        result = peak_envelope(pcm, 5)
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0], 0.8, places=6)
        self.assertAlmostEqual(result[1], 0.4, places=6)

    def test_peak_envelope_handles_empty_and_partial_bytes(self):
        self.assertEqual(peak_envelope(b""), [])
        self.assertEqual(peak_envelope(b"abc"), [])

    def test_cache_is_outside_source_and_changes_with_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_dir, cache = root / "media", root / "cache"
            source_dir.mkdir()
            source = source_dir / "voice.wav"
            source.write_bytes(b"one")
            first = waveform_cache_path(source, cache)
            self.assertEqual(first.parent, cache)
            source.write_bytes(b"updated audio")
            second = waveform_cache_path(source, cache)
            self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
