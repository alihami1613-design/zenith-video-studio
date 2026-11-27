"""Tests for crash-safe recovery storage."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from project_recovery import clear_recovery, read_recovery, write_recovery


class ProjectRecoveryTests(unittest.TestCase):
    def test_round_trip_preserves_project_and_source_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "recovery.json"
            project = {"media": [{"path": "clip.mp4"}], "timeline_project": {"clips": []}}
            write_recovery(path, project, "C:/Projects/demo.znproj")
            recovered = read_recovery(path)
            self.assertIsNotNone(recovered)
            self.assertEqual(recovered["project_data"], project)
            self.assertEqual(recovered["project_path"], "C:/Projects/demo.znproj")
            self.assertTrue(recovered["created_at"])

    def test_incomplete_json_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "recovery.json"
            path.write_text('{"format_version":', encoding="utf-8")
            self.assertIsNone(read_recovery(path))

    def test_unknown_format_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "recovery.json"
            path.write_text(json.dumps({"format_version": 999, "project_data": {}}), encoding="utf-8")
            self.assertIsNone(read_recovery(path))

    def test_invalid_project_shape_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "recovery.json"
            path.write_text(json.dumps({"format_version": 1, "project_data": {"media": "bad"}}), encoding="utf-8")
            self.assertIsNone(read_recovery(path))

    def test_clear_removes_recovery_and_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "recovery.json"
            write_recovery(path, {"media": [], "timeline_project": {}})
            path.with_name(path.name + ".tmp").write_text("partial", encoding="utf-8")
            clear_recovery(path)
            self.assertFalse(path.exists())
            self.assertFalse(path.with_name(path.name + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
