"""Safe, non-executing discovery for ZENITH Desktop extensions.

Discovery reads JSON manifests only. It never imports, loads, or executes plugin
code. Trust and enablement are explicit user decisions stored by the host app.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import json
import re
from typing import Any

PLUGIN_MANIFEST = "zenith-plugin.json"
PLUGIN_API_VERSION = 1
PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
VERSION_RE = re.compile(r"^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(?:[-+][0-9A-Za-z.-]+)?$")
ALLOWED_CAPABILITIES = frozenset({
    "video_effect", "audio_effect", "transition", "title_generator",
    "media_importer", "exporter", "workflow",
})


class PluginRegistryError(ValueError):
    """Raised when plugin registry settings are malformed."""


def empty_registry() -> dict[str, Any]:
    return {"format_version": 1, "trusted_ids": [], "enabled_ids": []}


def validate_registry(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("format_version") != 1:
        raise PluginRegistryError("Unsupported plugin registry format.")
    trusted = data.get("trusted_ids", [])
    enabled = data.get("enabled_ids", [])
    if (not isinstance(trusted, list) or not isinstance(enabled, list)
            or any(not isinstance(x, str) for x in trusted + enabled)):
        raise PluginRegistryError("Plugin IDs must be lists of strings.")
    if len(set(trusted)) != len(trusted) or len(set(enabled)) != len(enabled):
        raise PluginRegistryError("Duplicate plugin IDs are not allowed.")
    if not set(enabled).issubset(set(trusted)):
        raise PluginRegistryError("Only trusted plugins may be enabled.")
    return {"format_version": 1, "trusted_ids": sorted(trusted),
            "enabled_ids": sorted(enabled)}


def load_registry(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return empty_registry()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PluginRegistryError(f"Cannot read plugin registry: {exc}") from exc
    return validate_registry(data)


def save_registry(path: str | Path, data: dict[str, Any]) -> Path:
    import os
    target = Path(path)
    registry = validate_registry(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\\n") as stream:
            json.dump(registry, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def _read_manifest(folder: Path, registry: dict[str, Any]) -> dict[str, Any]:
    manifest_path = folder / PLUGIN_MANIFEST
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Manifest root must be an object.")
        plugin_id = str(raw.get("id", "")).strip()
        if not PLUGIN_ID_RE.fullmatch(plugin_id):
            raise ValueError("Invalid plugin ID.")
        version = str(raw.get("version", "")).strip()
        if not VERSION_RE.fullmatch(version):
            raise ValueError("Version must use MAJOR.MINOR.PATCH.")
        api_version = raw.get("api_version")
        if not isinstance(api_version, int) or isinstance(api_version, bool):
            raise ValueError("api_version must be an integer.")
        entrypoint = str(raw.get("entrypoint", "")).strip()
        relative = PurePosixPath(entrypoint.replace("\\", "/"))
        if (not entrypoint or relative.is_absolute()
                or any(part in {"", ".", ".."} for part in relative.parts)):
            raise ValueError("Entrypoint must be a safe relative path.")
        resolved_folder = folder.resolve(strict=True)
        resolved_entry = (folder / Path(*relative.parts)).resolve(strict=True)
        if not resolved_entry.is_file() or not resolved_entry.is_relative_to(resolved_folder):
            raise ValueError("Entrypoint must be a file inside the plugin folder.")
        capabilities = raw.get("capabilities", [])
        if (not isinstance(capabilities, list)
                or any(not isinstance(item, str) or item not in ALLOWED_CAPABILITIES
                       for item in capabilities)):
            raise ValueError("Plugin requests an unsupported capability.")
        status = "ready"
        if api_version != PLUGIN_API_VERSION:
            status = "incompatible"
        elif plugin_id not in registry["trusted_ids"]:
            status = "untrusted"
        elif plugin_id not in registry["enabled_ids"]:
            status = "disabled"
        return {
            "id": plugin_id, "name": str(raw.get("name") or plugin_id),
            "version": version, "api_version": api_version,
            "vendor": str(raw.get("vendor", "")),
            "license": str(raw.get("license", "")),
            "description": str(raw.get("description", "")),
            "capabilities": sorted(set(capabilities)),
            "entrypoint": str(resolved_entry), "folder": str(resolved_folder),
            "status": status, "error": "",
        }
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {"id": folder.name, "name": folder.name, "version": "",
                "api_version": None, "vendor": "", "license": "",
                "description": "", "capabilities": [], "entrypoint": "",
                "folder": str(folder), "status": "invalid", "error": str(exc)}


def discover_plugins(folders: list[str | Path],
                     registry: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Inspect immediate plugin folders without importing or executing code."""
    settings = validate_registry(registry or empty_registry())
    found: dict[str, dict[str, Any]] = {}
    for root_value in folders:
        root = Path(root_value).expanduser()
        if not root.is_dir():
            continue
        try:
            children = sorted((p for p in root.iterdir() if p.is_dir()),
                              key=lambda p: p.name.casefold())
        except OSError:
            continue
        for folder in children:
            if not (folder / PLUGIN_MANIFEST).is_file():
                continue
            item = _read_manifest(folder, settings)
            key = item["id"].casefold()
            if key in found:
                found[key] = {**item, "status": "invalid",
                              "error": "Duplicate plugin ID discovered."}
            else:
                found[key] = item
    return sorted(found.values(), key=lambda item: item["name"].casefold())


def set_plugin_trust(registry: dict[str, Any], plugin_id: str,
                     trusted: bool) -> dict[str, Any]:
    settings = validate_registry(registry)
    if not PLUGIN_ID_RE.fullmatch(plugin_id):
        raise PluginRegistryError("Invalid plugin ID.")
    trusted_ids = set(settings["trusted_ids"])
    enabled_ids = set(settings["enabled_ids"])
    if trusted:
        trusted_ids.add(plugin_id)
    else:
        trusted_ids.discard(plugin_id)
        enabled_ids.discard(plugin_id)
    return validate_registry({"format_version": 1,
                              "trusted_ids": sorted(trusted_ids),
                              "enabled_ids": sorted(enabled_ids)})


def set_plugin_enabled(registry: dict[str, Any], plugin_id: str,
                       enabled: bool) -> dict[str, Any]:
    settings = validate_registry(registry)
    if plugin_id not in settings["trusted_ids"]:
        raise PluginRegistryError("Trust the plugin before enabling it.")
    enabled_ids = set(settings["enabled_ids"])
    if enabled:
        enabled_ids.add(plugin_id)
    else:
        enabled_ids.discard(plugin_id)
    return validate_registry({**settings, "enabled_ids": sorted(enabled_ids)})
