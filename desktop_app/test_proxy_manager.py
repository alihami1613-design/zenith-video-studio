"""Unit tests for safe proxy paths and FFmpeg command construction."""
import tempfile
import unittest
from pathlib import Path

from proxy_manager import build_proxy_command, proxy_cache_key, proxy_path_for


class ProxyManagerTests(unittest.TestCase):
    def test_proxy_is_cached_outside_source_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_dir = root / "media"
            cache = root / "cache"
            source_dir.mkdir()
            source = source_dir / "scene.mp4"
            source.write_bytes(b"source")
            target = proxy_path_for(source, cache)
            self.assertEqual(target.parent, cache)
            self.assertEqual(target.suffix, ".mp4")
            self.assertNotEqual(target, source)

    def test_cache_key_changes_when_source_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "scene.mp4"
            source.write_bytes(b"first")
            first = proxy_cache_key(source)
            source.write_bytes(b"second version")
            second = proxy_cache_key(source)
            self.assertNotEqual(first, second)

    def test_command_limits_preview_width_and_cpu_threads(self):
        command = build_proxy_command("ffmpeg", "input.mov", "output.mp4")
        self.assertIn("scale='min(960,iw)':-2", command)
        self.assertIn("2", command[command.index("-threads") + 1:])
        self.assertIn("libx264", command)
        self.assertIn("0:a?", command)


if __name__ == "__main__":
    unittest.main()
