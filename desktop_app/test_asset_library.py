"""Tests for the user-owned asset catalog."""
from pathlib import Path
import tempfile
import unittest

from asset_library import (
    AssetCatalogError, add_asset, discover_fonts, empty_catalog, load_catalog,
    remove_asset, save_catalog, search_assets, validate_catalog,
)


class AssetLibraryTests(unittest.TestCase):
    def test_round_trip_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog_path = Path(folder) / "settings" / "assets.json"
            asset_path = Path(folder) / "Fonts" / "Example.otf"
            data = add_asset(empty_catalog(), path=asset_path, kind="font",
                             source="Foundry", license="Commercial license",
                             tags=["Persian", "Display"], favorite=True)
            save_catalog(catalog_path, data)
            loaded = load_catalog(catalog_path)
            self.assertEqual(loaded["assets"][0]["license"], "Commercial license")
            self.assertEqual(search_assets(loaded, "persian", kind="font")[0]["name"],
                             "Example")
            self.assertEqual(search_assets(loaded, favorites_only=True)[0]["source"],
                             "Foundry")

    def test_missing_catalog_is_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(load_catalog(Path(folder) / "missing.json"), empty_catalog())

    def test_relative_paths_rejected(self):
        with self.assertRaises(AssetCatalogError):
            add_asset(empty_catalog(), path="relative/font.ttf", kind="font")

    def test_duplicate_asset_rejected(self):
        data = add_asset(empty_catalog(), path="/fonts/a.ttf", kind="font")
        with self.assertRaises(AssetCatalogError):
            add_asset(data, path="/fonts/a.ttf", kind="font")

    def test_duplicate_ids_rejected(self):
        base = {"id": "same", "kind": "font", "path": "/fonts/a.ttf"}
        with self.assertRaises(AssetCatalogError):
            validate_catalog({"format_version": 1, "assets": [base, base]})

    def test_remove_requires_existing_id(self):
        data = add_asset(empty_catalog(), path="/fonts/a.ttf", kind="font")
        asset_id = data["assets"][0]["id"]
        self.assertEqual(remove_asset(data, asset_id)["assets"], [])
        with self.assertRaises(AssetCatalogError):
            remove_asset(data, "not-found")

    def test_font_discovery_is_extension_filtered_and_non_recursive_option_works(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "A.TTF").write_bytes(b"font")
            (root / "ignore.txt").write_text("x")
            nested = root / "nested"
            nested.mkdir()
            (nested / "B.otf").write_bytes(b"font")
            self.assertEqual([p.name for p in discover_fonts([root], recursive=False)],
                             ["A.TTF"])
            self.assertEqual({p.name for p in discover_fonts([root])}, {"A.TTF", "B.otf"})

    def test_invalid_json_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "assets.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(AssetCatalogError):
                load_catalog(path)


if __name__ == "__main__":
    unittest.main()
