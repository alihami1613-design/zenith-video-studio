import tempfile
import unittest
from pathlib import Path

from color_preview import (
    build_color_preview_command, color_preview_path, color_preview_key,
)


class ColorPreviewTests(unittest.TestCase):
    def test_command_is_proxy_sized_and_cpu_limited(self):
        command = build_color_preview_command(
            "ffmpeg", "source.mp4", "preview.mp4", 2.5, 8.0,
            {"exposure": 1.0, "contrast": 1.2, "saturation": 1.1,
             "temperature": 0.2, "tint": 0.0},
        )
        self.assertEqual(command[command.index("-ss") + 1], "2.500000")
        self.assertEqual(command[command.index("-t") + 1], "8.000000")
        self.assertIn("scale='min(960,iw)':-2,exposure=exposure=1.000", command)
        self.assertEqual(command[command.index("-threads") + 1], "2")
        self.assertIn("0:a?", command)

    def test_default_grade_command_has_no_color_filters(self):
        command = build_color_preview_command(
            "ffmpeg", "source.mp4", "preview.mp4", 0, 4,
            {"exposure": 0, "contrast": 1, "saturation": 1,
             "temperature": 0, "tint": 0},
        )
        vf = command[command.index("-vf") + 1]
        self.assertEqual(vf, "scale='min(960,iw)':-2")

    def test_cache_key_changes_for_grade_and_source_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "clip.mp4"
            source.write_bytes(b"one")
            grade = {"exposure": 0, "contrast": 1, "saturation": 1,
                     "temperature": 0, "tint": 0}
            first = color_preview_key(source, 0, 5, grade)
            changed = dict(grade, exposure=1)
            self.assertNotEqual(first, color_preview_key(source, 0, 5, changed))
            source.write_bytes(b"two changed")
            self.assertNotEqual(first, color_preview_key(source, 0, 5, grade))
            self.assertNotEqual(
                color_preview_path(source, 0, 5, grade, Path(temp) / "cache"),
                source,
            )

    def test_invalid_source_range_rejected(self):
        with self.assertRaises(ValueError):
            build_color_preview_command("ffmpeg", "in.mp4", "out.mp4", -1, 2, {})
        with self.assertRaises(ValueError):
            build_color_preview_command("ffmpeg", "in.mp4", "out.mp4", 0, 0, {})


if __name__ == "__main__":
    unittest.main()
