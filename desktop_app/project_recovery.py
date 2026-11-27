"""Crash-safe session recovery storage for ZENITH Desktop."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any


RECOVERY_FORMAT_VERSION = 1


def default_recovery_path() -> Path:
    """Return the per-user recovery file location without creating directories."""
    root = os.environ.get("LOCALAPPDATA")
    if root:
        base = Path(root)
    else:
        base = Path.home() / ".local" / "share"
    return base / "ZENITH" / "Recovery" / "session_recovery.json"


def write_recovery(path: str | Path, project_data: dict[str, Any],
                   project_path: str | None = None) -> Path:
    """Atomically persist a self-contained recovery snapshot."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": RECOVERY_FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_path": str(project_path) if project_path else None,
        "project_data": project_data,
    }
    temporary = target.with_name(target.name + ".tmp")
    try:
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def read_recovery(path: str | Path) -> dict[str, Any] | None:
    """Read and validate a recovery envelope; ignore incomplete/unknown files."""
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("format_version") != RECOVERY_FORMAT_VERSION:
        return None
    project_data = payload.get("project_data")
    if not isinstance(project_data, dict):
        return None
    if not isinstance(project_data.get("media", []), list):
        return None
    if not isinstance(project_data.get("timeline_project", project_data), dict):
        return None
    return payload


def clear_recovery(path: str | Path) -> None:
    """Remove the recovery snapshot after an explicit restore/discard or clean exit."""
    target = Path(path)
    try:
        target.unlink(missing_ok=True)
    except OSError:
        # A stale recovery file is safer than turning a successful close into data loss.
        pass
    try:
        target.with_name(target.name + ".tmp").unlink(missing_ok=True)
    except OSError:
        pass
