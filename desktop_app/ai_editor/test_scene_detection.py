"""Tests for bounded FFmpeg shot-boundary detection."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ai_editor.scene_detection import detect_scene_changes, SceneBoundary


class SceneDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.media = Path(self.temp.name) / "source.mp4"
        self.media.write_bytes(b"fixture")

    def tearDown(self):
        self.temp.cleanup()

    def test_parses_and_filters_scene_boundaries(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return SimpleNamespace(stderr=(
                b"[Parsed_showinfo] n: 1 pts_time:0.500\n"
                b"[Parsed_showinfo] n: 2 pts_time:0.600\n"
                b"[Parsed_showinfo] n: 3 pts_time:2.250\n"
                b"[Parsed_showinfo] n: 4 pts_time:8.000\n"
            ))

        result = detect_scene_changes(
            self.media, 10, threshold=0.4, minimum_spacing_seconds=0.5,
            ffmpeg_executable="ffmpeg-test", run=fake_run,
        )
        self.assertEqual(result.boundaries, (
            SceneBoundary(0.5), SceneBoundary(2.25), SceneBoundary(8.0)
        ))
        self.assertIn("scale=320:-2,format=gray", captured["command"])
        self.assertIn("0.400", captured["command"][captured["command"].index("-vf") + 1])
        self.assertEqual(captured["kwargs"]["timeout"], 300)

    def test_caps_boundary_count(self):
        log = b"".join(
            f"[showinfo] pts_time:{i + 0.1}\n".encode() for i in range(10)
        )
        result = detect_scene_changes(
            self.media, 20, max_boundaries=3,
            ffmpeg_executable="ffmpeg-test",
            run=lambda *a, **k: SimpleNamespace(stderr=log),
        )
        self.assertEqual(len(result.boundaries), 3)

    def test_rejects_invalid_limits(self):
        for kwargs in (
            {"duration_seconds": 0},
            {"duration_seconds": 90000},
            {"threshold": 1.2},
            {"minimum_spacing_seconds": 0},
            {"max_boundaries": 5001},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                detect_scene_changes(
                    self.media, kwargs.pop("duration_seconds", 10),
                    ffmpeg_executable="unused", run=lambda *a, **k: None,
                    **kwargs,
                )

    def test_missing_media_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            detect_scene_changes(
                Path(self.temp.name) / "missing.mp4", 10,
                ffmpeg_executable="unused",
            )


if __name__ == "__main__":
    unittest.main()
