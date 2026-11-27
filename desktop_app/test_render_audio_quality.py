"""Tests for bounded audio export diagnostics using synthetic PCM fixtures."""
import array
import shutil
import tempfile
import unittest
import wave
from pathlib import Path

from render_audio_quality import inspect_rendered_audio

FFMPEG = shutil.which("ffmpeg")


@unittest.skipUnless(FFMPEG, "FFmpeg is required for audio render diagnostics")
class RenderAudioQualityTests(unittest.TestCase):
    def _wav(self, path, samples, sample_rate=16000):
        values = array.array("h", samples)
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(sample_rate)
            stream.writeframes(values.tobytes())

    def test_detects_abrupt_transient_candidates_without_claiming_confirmed_clicks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "transient.wav"
            samples = [1000] * 16000
            samples[8000] = 30000
            self._wav(path, samples)
            report = inspect_rendered_audio(path, FFMPEG, expected_video_duration_seconds=1.0, fps=25)
            self.assertTrue(report.scanned)
            self.assertTrue(report.duration_matches_video)
            self.assertTrue(report.transient_candidates)
            self.assertTrue(report.requires_human_review)
            self.assertTrue(any("نامزد شنیداری" in item for item in report.warnings))

    def test_detects_sustained_clipping_intervals(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "clipped.wav"
            samples = [1000] * 16000
            samples[4000:4010] = [32767] * 10
            self._wav(path, samples)
            report = inspect_rendered_audio(path, FFMPEG, expected_video_duration_seconds=1.0, fps=25)
            self.assertTrue(report.clipped_intervals_seconds)
            self.assertGreater(report.clipped_intervals_seconds[0][1], report.clipped_intervals_seconds[0][0])

    def test_reports_audio_duration_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "short.wav"
            self._wav(path, [1000] * 16000)
            report = inspect_rendered_audio(path, FFMPEG, expected_video_duration_seconds=1.5, fps=25)
            self.assertFalse(report.duration_matches_video)
            self.assertTrue(report.requires_human_review)

    def test_marks_duration_scan_incomplete_when_resource_cap_is_reached(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "long.wav"
            self._wav(path, [1000] * 32000)
            report = inspect_rendered_audio(
                path, FFMPEG, expected_video_duration_seconds=2.0,
                fps=25, max_duration_seconds=1,
            )
            self.assertFalse(report.duration_scan_complete)
            self.assertTrue(report.requires_human_review)

    def test_rejects_invalid_limits_and_missing_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "silence.wav"
            self._wav(path, [0] * 16000)
            with self.assertRaises(ValueError):
                inspect_rendered_audio(path, FFMPEG, expected_video_duration_seconds=1.0, fps=25, sample_rate=100)
            missing = Path(folder) / "missing.wav"
            with self.assertRaises(FileNotFoundError):
                inspect_rendered_audio(missing, FFMPEG, expected_video_duration_seconds=1.0, fps=25)


if __name__ == "__main__":
    unittest.main()
