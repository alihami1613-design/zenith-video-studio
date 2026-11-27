"""User-owned asset catalog for ZENITH Desktop.

The catalog stores references and provenance; it never redistributes or copies
third-party fonts, LUTs, templates, or media into the application package.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid
from typing import Any


ASSET_CATALOG_VERSION = 1
ASSET_KINDS = frozenset({"font", "lut", "preset", "template", "graphic", "audio", "video", "other"})
FONT_EXTENSIONS = frozenset({".ttf", ".otf", ".ttc", ".otc"})


class AssetCatalogError(ValueError):
    """Raised when catalog data or an asset reference is invalid."""


def _normalise_asset(asset: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(asset, dict):
        raise AssetCatalogError("Asset entry must be an object.")
    kind = str(asset.get("kind", "other")).strip().lower()
    if kind not in ASSET_KINDS:
        raise AssetCatalogError(f"Unsupported asset kind: {kind}")
    raw_path = str(asset.get("path", "")).strip()
    if not raw_path:
        raise AssetCatalogError("Asset path is required.")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise AssetCatalogError("Asset path must be absolute.")
    name = str(asset.get("name") or path.stem).strip()
    if not name:
        raise AssetCatalogError("Asset name is required.")
    tags = asset.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise AssetCatalogError("Asset tags must be a list of strings.")
    return {
        "id": str(asset.get("id") or uuid.uuid4()),
        "kind": kind,
        "name": name,
        "path": str(path.resolve(strict=False)),
        "source": str(asset.get("source", "")).strip(),
        "license": str(asset.get("license", "")).strip(),
        "license_url": str(asset.get("license_url", "")).strip(),
        "notes": str(asset.get("notes", "")).strip(),
        "tags": sorted({tag.strip() for tag in tags if tag.strip()}, key=str.casefold),
        "favorite": bool(asset.get("favorite", False)),
        "created_at": str(asset.get("created_at") or datetime.now(timezone.utc).isoformat()),
    }


def empty_catalog() -> dict[str, Any]:
    return {"format_version": ASSET_CATALOG_VERSION, "assets": []}


def validate_catalog(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("format_version") != ASSET_CATALOG_VERSION:
        raise AssetCatalogError("Unsupported asset catalog format.")
    entries = data.get("assets")
    if not isinstance(entries, list):
        raise AssetCatalogError("Catalog assets must be a list.")
    normalised = [_normalise_asset(item) for item in entries]
    ids = [item["id"] for item in normalised]
    if len(ids) != len(set(ids)):
        raise AssetCatalogError("Duplicate asset IDs are not allowed.")
    return {"format_version": ASSET_CATALOG_VERSION, "assets": normalised}


def load_catalog(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return empty_catalog()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AssetCatalogError(f"Cannot read asset catalog: {exc}") from exc
    return validate_catalog(raw)


def save_catalog(path: str | Path, data: dict[str, Any]) -> Path:
    target = Path(path)
    catalog = validate_catalog(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(catalog, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def add_asset(data: dict[str, Any], *, path: str | Path, kind: str = "other",
              name: str | None = None, source: str = "", license: str = "",
              license_url: str = "", notes: str = "", tags: list[str] | None = None,
              favorite: bool = False) -> dict[str, Any]:
    catalog = validate_catalog(data)
    candidate = _normalise_asset({
        "path": str(path), "kind": kind, "name": name, "source": source,
        "license": license, "license_url": license_url, "notes": notes,
        "tags": tags or [], "favorite": favorite,
    })
    duplicate = next((item for item in catalog["assets"]
                      if item["path"].casefold() == candidate["path"].casefold()
                      and item["kind"] == candidate["kind"]), None)
    if duplicate:
        raise AssetCatalogError("This asset is already registered.")
    catalog["assets"].append(candidate)
    return catalog


def remove_asset(data: dict[str, Any], asset_id: str) -> dict[str, Any]:
    catalog = validate_catalog(data)
    remaining = [item for item in catalog["assets"] if item["id"] != asset_id]
    if len(remaining) == len(catalog["assets"]):
        raise AssetCatalogError("Asset ID was not found.")
    return {"format_version": ASSET_CATALOG_VERSION, "assets": remaining}


def search_assets(data: dict[str, Any], query: str = "", *, kind: str | None = None,
                  favorites_only: bool = False) -> list[dict[str, Any]]:
    catalog = validate_catalog(data)
    needle = query.strip().casefold()
    selected = []
    for item in catalog["assets"]:
        if kind and item["kind"] != kind:
            continue
        if favorites_only and not item["favorite"]:
            continue
        searchable = " ".join([item["name"], item["source"], item["license"],
                               item["notes"], *item["tags"]]).casefold()
        if needle and needle not in searchable:
            continue
        selected.append(item)
    return sorted(selected, key=lambda item: (not item["favorite"], item["name"].casefold()))


def discover_fonts(folders: list[str | Path], *, recursive: bool = True) -> list[Path]:
    """Discover font files in user-selected folders; does not install or copy them."""
    found: dict[str, Path] = {}
    for folder in folders:
        root = Path(folder).expanduser()
        if not root.is_dir():
            continue
        iterator = root.rglob("*") if recursive else root.iterdir()
        for candidate in iterator:
            try:
                if candidate.is_file() and candidate.suffix.casefold() in FONT_EXTENSIONS:
                    resolved = candidate.resolve(strict=True)
                    found[str(resolved).casefold()] = resolved
            except OSError:
                continue
    return sorted(found.values(), key=lambda item: (item.name.casefold(), str(item).casefold()))
