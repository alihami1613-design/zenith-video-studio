"""Tests for durable atomic project-file writes."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from project_storage import atomic_write_text


class AtomicProjectStorageTests(unittest.TestCase):
    def test_writes_utf8_and_replaces_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "project.znproj"
            target.write_text("old", encoding="utf-8")
            result = atomic_write_text(target, '{"title":"سلام"}')
            self.assertEqual(result, target)
            self.assertEqual(target.read_text(encoding="utf-8"), '{"title":"سلام"}')
            self.assertFalse(target.with_name(target.name + ".tmp").exists())

    def test_failed_replace_preserves_previous_project_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "project.znproj"
            target.write_text("valid previous project", encoding="utf-8")
            with patch("project_storage.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "new project")
            self.assertEqual(target.read_text(encoding="utf-8"), "valid previous project")
            self.assertFalse(target.with_name(target.name + ".tmp").exists())

    def test_flushes_file_before_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "project.znproj"
            with patch("project_storage.os.fsync", wraps=__import__("os").fsync) as sync:
                atomic_write_text(target, "durable")
                sync.assert_called_once()


if __name__ == "__main__":
    unittest.main()
