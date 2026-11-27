"""Tests for safe plugin manifest discovery and explicit trust controls."""
import json
from pathlib import Path
import tempfile
import unittest

from plugin_registry import (
    PluginRegistryError, discover_plugins, empty_registry, load_registry,
    save_registry, set_plugin_enabled, set_plugin_trust, validate_registry,
)


class PluginRegistryTests(unittest.TestCase):
    def make_plugin(self, root, plugin_id="com.example.color", api_version=1,
                    entrypoint="plugin.py"):
        folder = Path(root) / "sample"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / entrypoint).write_text("# plugin code is never executed", encoding="utf-8")
        (folder / "zenith-plugin.json").write_text(json.dumps({
            "id": plugin_id, "name": "Example Color", "version": "1.2.3",
            "api_version": api_version, "entrypoint": entrypoint,
            "capabilities": ["video_effect"], "license": "MIT",
        }), encoding="utf-8")
        return folder

    def test_discovery_defaults_to_untrusted_and_never_executes_entrypoint(self):
        with tempfile.TemporaryDirectory() as root:
            folder = self.make_plugin(root)
            marker = Path(root) / "executed.txt"
            (folder / "plugin.py").write_text(
                f"from pathlib import Path; Path({str(marker)!r}).touch()", encoding="utf-8")
            item = discover_plugins([root])[0]
            self.assertEqual(item["status"], "untrusted")
            self.assertFalse(marker.exists())

    def test_trust_then_enable(self):
        with tempfile.TemporaryDirectory() as root:
            self.make_plugin(root)
            registry = set_plugin_trust(empty_registry(), "com.example.color", True)
            self.assertEqual(discover_plugins([root], registry)[0]["status"], "disabled")
            registry = set_plugin_enabled(registry, "com.example.color", True)
            self.assertEqual(discover_plugins([root], registry)[0]["status"], "ready")

    def test_incompatible_api_is_not_ready_even_when_enabled(self):
        with tempfile.TemporaryDirectory() as root:
            self.make_plugin(root, api_version=99)
            registry = set_plugin_trust(empty_registry(), "com.example.color", True)
            registry = set_plugin_enabled(registry, "com.example.color", True)
            self.assertEqual(discover_plugins([root], registry)[0]["status"], "incompatible")

    def test_path_traversal_entrypoint_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            folder = self.make_plugin(root, entrypoint="../outside.py")
            item = discover_plugins([root])[0]
            self.assertEqual(item["status"], "invalid")

    def test_untrusted_cannot_be_enabled(self):
        with self.assertRaises(PluginRegistryError):
            set_plugin_enabled(empty_registry(), "com.example.color", True)

    def test_registry_round_trip_and_invalid_enabled_state(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "settings" / "plugins.json"
            registry = set_plugin_trust(empty_registry(), "com.example.color", True)
            save_registry(path, registry)
            self.assertEqual(load_registry(path), registry)
        with self.assertRaises(PluginRegistryError):
            validate_registry({"format_version": 1, "trusted_ids": [],
                               "enabled_ids": ["com.example.color"]})


if __name__ == "__main__":
    unittest.main()
