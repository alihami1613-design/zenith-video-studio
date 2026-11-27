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

        report = analyze_project_media(
            self.context, scene_detector=scenes,
            visual_sampler=samples, audio_analyzer=audio,
        )
        self.assertEqual([item.asset_id for item in report.assets],
                         ["asset-video", "asset-audio", "asset-image"])
        video = report.assets[0]
        self.assertEqual(video.scene_boundaries_seconds, (2.5,))
        self.assertEqual(video.visual_samples[0].width, 640)
        self.assertEqual(video.audio.peak_db, -2.0)
        self.assertEqual(report.assets[1].audio.mean_db, -18.0)
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

        report = analyze_project_media(
            self.context, scene_detector=broken_scenes,
            visual_sampler=samples, audio_analyzer=audio,
        )
        video = report.assets[0]
        self.assertFalse(video.scene_boundaries_seconds)
        self.assertEqual(len(video.visual_samples), 1)
        self.assertIsNotNone(video.audio)
        self.assertTrue(any("Scene detection failed" in warning
                            for warning in video.warnings))

    def test_visual_resource_limits_are_validated(self):
        with self.assertRaises(ValueError):
            analyze_project_media(self.context, visual_sample_count=25)
        with self.assertRaises(ValueError):
            analyze_project_media(self.context, max_visual_dimension=2048)


if __name__ == "__main__":
    unittest.main()
