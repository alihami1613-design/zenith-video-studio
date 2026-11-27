"""Tests for the unified local media analysis pipeline."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ai_editor.contracts import MediaAsset
from ai_editor.project_context import MediaInventoryItem, ProjectContext
from ai_editor.media_analysis import analyze_project_media


class MediaAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.video = Path(self.temp.name) / "video.mp4"
        self.audio = Path(self.temp.name) / "voice.wav"
        self.image = Path(self.temp.name) / "still.png"
        for path in (self.video, self.audio, self.image):
            path.write_bytes(b"fixture")
        assets = (
            MediaInventoryItem(
                MediaAsset("asset-video", str(self.video), "video", 300, 30,
                           has_audio=True),
                True, 10, 10.0, 1920, 1080, 30.0, "test",
            ),
            MediaInventoryItem(
                MediaAsset("asset-audio", str(self.audio), "audio", 300, 30),
                True, 10, 10.0, None, None, None, "test",
            ),
            MediaInventoryItem(
                MediaAsset("asset-image", str(self.image), "image", 0, 30),
                True, 10, None, 800, 600, None, "test",
            ),
        )
        self.context = ProjectContext(1, {}, assets, (), ())

    def tearDown(self):
        self.temp.cleanup()

    def test_combines_local_diagnostics_without_media_bytes_or_paths(self):
        def scenes(path, duration):
            return SimpleNamespace(boundaries=(
                SimpleNamespace(timestamp_seconds=2.5),
            ))

        def samples(path, duration, **kwargs):
            return (
                SimpleNamespace(timestamp_seconds=1.0, width=640, height=360,
                                jpeg_bytes=b"private-frame"),
            )

        def audio(path):
            return SimpleNamespace(
                silence_intervals=(
                    SimpleNamespace(start_seconds=3.0, end_seconds=3.5),
                ),
                peak_db=-2.0, mean_db=-18.0,
            )

        def energy(path):
            return SimpleNamespace(
                window_seconds=0.1, analyzed_duration_seconds=10.0,
                energy_envelope=(
                    SimpleNamespace(time_seconds=0.0, rms_dbfs=-25.0),
                    SimpleNamespace(time_seconds=0.1, rms_dbfs=-8.0),
                ),
                transient_candidates_seconds=(0.1,),
                warnings=("Transient candidates are not verified beats.",),
            )

        def rhythm(measured):
            return SimpleNamespace(
                estimated_bpm=120.0, confidence=0.8,
                pulse_period_seconds=0.5,
                pulse_candidates_seconds=(0.0, 0.5),
                warnings=("RMS periodicity only.",),
            )

        def spectral(path):
            return SimpleNamespace(
                sample_rate=8000, frame_size=512, hop_size=128,
                estimated_bpm=120.0, tempo_confidence=0.9,
                onset_candidates_seconds=(0.25, 0.75),
                pulse_candidates_seconds=(0.0, 0.5),
                warnings=("Spectral onset estimate only.",),
            )

        report = analyze_project_media(
            self.context, scene_detector=scenes,
            visual_sampler=samples, audio_analyzer=audio,
            audio_energy_analyzer=energy, rhythm_analyzer=rhythm,
            spectral_analyzer=spectral,
        )
        self.assertEqual([item.asset_id for item in report.assets],
                         ["asset-video", "asset-audio", "asset-image"])
        video = report.assets[0]
        self.assertEqual(video.scene_boundaries_seconds, (2.5,))
        self.assertEqual(video.visual_samples[0].width, 640)
        self.assertEqual(video.audio.peak_db, -2.0)
        self.assertEqual(video.audio_energy.transient_candidates_seconds, (0.1,))
        self.assertEqual(video.audio_rhythm.estimated_bpm, 120.0)
        self.assertEqual(video.audio_rhythm.pulse_candidates_seconds, (0.0, 0.5))
        self.assertEqual(video.spectral_audio.estimated_bpm, 120.0)
        self.assertEqual(video.spectral_audio.onset_candidates_seconds, (0.25, 0.75))
        self.assertEqual(len(video.audio_energy.energy_dbfs), 2)
        self.assertEqual(report.assets[1].audio.mean_db, -18.0)
        self.assertIsNotNone(report.assets[1].audio_energy)
        self.assertIsNone(report.assets[2].audio)
        serialized = str(report.to_dict())
        self.assertNotIn(str(self.video), serialized)
        self.assertNotIn("private-frame", serialized)

    def test_one_analyzer_failure_does_not_abort_other_diagnostics(self):
        def broken_scenes(*args, **kwargs):
            raise RuntimeError("scene detector unavailable")

        def samples(path, duration, **kwargs):
            return (SimpleNamespace(timestamp_seconds=1.0, width=320,
                                    height=180, jpeg_bytes=b"x"),)

        def audio(path):
            return SimpleNamespace(silence_intervals=(), peak_db=-1.0,
                                   mean_db=-12.0)

        def broken_energy(path):
            raise RuntimeError(f"decoder failed for {path}")

        report = analyze_project_media(
            self.context, scene_detector=broken_scenes,
            visual_sampler=samples, audio_analyzer=audio,
            audio_energy_analyzer=broken_energy,
        )
        video = report.assets[0]
        self.assertFalse(video.scene_boundaries_seconds)
        self.assertEqual(len(video.visual_samples), 1)
        self.assertIsNotNone(video.audio)
        self.assertIsNone(video.audio_energy)
        self.assertTrue(any("Scene detection failed" in warning
                            for warning in video.warnings))
        self.assertTrue(any("Audio energy analysis failed" in warning
                            for warning in video.warnings))
        serialized = str(report.to_dict())
        self.assertNotIn(str(self.video), serialized)
        self.assertNotIn(str(self.audio), serialized)

    def test_visual_resource_limits_are_validated(self):
        with self.assertRaises(ValueError):
            analyze_project_media(self.context, visual_sample_count=25)
        with self.assertRaises(ValueError):
            analyze_project_media(self.context, max_visual_dimension=2048)


if __name__ == "__main__":
    unittest.main()
