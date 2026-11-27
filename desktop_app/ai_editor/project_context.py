"""Build a compact, privacy-local context package for AI editorial planning.

Only metadata is read. Media bytes are not uploaded, decoded, or modified here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
from typing import Any, Callable, Iterable

from ai_editor.contracts import MediaAsset
from media_probe import duration_to_frames, probe_media
from timeline_model import TimelineProject


@dataclass(frozen=True)
class MediaInventoryItem:
    asset: MediaAsset
    exists: bool
    file_size_bytes: int | None
    duration_seconds: float | None
    width: int | None
    height: int | None
    source_fps: float | None
    probe_method: str | None
    warning: str | None = None


@dataclass(frozen=True)
class ProjectContext:
    schema_version: int
    project: dict[str, Any]
    assets: tuple[MediaInventoryItem, ...]
    timeline_clips: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _asset_id(path: Path) -> str:
    normalized = str(path.resolve()).casefold()
    return "media-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def _media_type(metadata: dict[str, Any], path: Path) -> str:
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}:
        return "image"
    if metadata.get("has_video"):
        return "video"
    if metadata.get("has_audio"):
        return "audio"
    raise ValueError("Media stream type could not be identified.")


def build_project_context(
    project: TimelineProject,
    media_paths: Iterable[str | Path] = (),
    *,
    probe_fn: Callable[[str | Path], dict[str, Any]] = probe_media,
) -> ProjectContext:
    """Inventory timeline and optional imported media without decoding media frames."""
    paths: dict[str, Path] = {}
    for raw_path in media_paths:
        path = Path(raw_path).expanduser().resolve()
        paths[str(path).casefold()] = path
    for clip in project.clips:
        path = Path(clip.path).expanduser().resolve()
        paths[str(path).casefold()] = path

    items: list[MediaInventoryItem] = []
    warnings: list[str] = []
    for path in sorted(paths.values(), key=lambda item: str(item).casefold()):
        asset_id = _asset_id(path)
        if not path.is_file():
            warning = "Source file is missing; relink it before AI editing."
            items.append(MediaInventoryItem(
                MediaAsset(asset_id, str(path), "video", 0, project.fps),
                False, None, None, None, None, None, None, warning,
            ))
            warnings.append(f"Missing media: {path.name}")
            continue
        try:
            metadata = probe_fn(path)
            media_type = _media_type(metadata, path)
            duration_seconds = metadata.get("duration_seconds")
            duration_frames = duration_to_frames(duration_seconds, project.fps) or 0
            source_fps = metadata.get("fps")
            asset = MediaAsset(
                asset_id=asset_id,
                path=str(path),
                media_type=media_type,
                duration_frames=duration_frames,
                fps=project.fps,
                width=int(metadata.get("width") or 0),
                height=int(metadata.get("height") or 0),
                has_audio=bool(metadata.get("has_audio")),
            )
            asset.validate()
            warning = None
            if duration_frames == 0 and media_type != "image":
                warning = "Media duration is unknown; source-range validation is limited."
                warnings.append(f"Unknown duration: {path.name}")
            items.append(MediaInventoryItem(
                asset, True, path.stat().st_size, duration_seconds,
                metadata.get("width"), metadata.get("height"), source_fps,
                metadata.get("probe_method"), warning,
            ))
        except Exception as exc:
            warning = f"Metadata probe failed: {exc}"
            warnings.append(f"Could not inspect {path.name}: {exc}")
            # Keep the asset visible to the user, but do not pretend it is editable.
            items.append(MediaInventoryItem(
                MediaAsset(asset_id, str(path), "video", 0, project.fps),
                True, path.stat().st_size, None, None, None, None, None, warning,
            ))

    timeline = tuple({
        "clip_id": clip.clip_id,
        "asset_id": _asset_id(Path(clip.path).expanduser()),
        "name": clip.name,
        "media_type": clip.media_type,
        "track": clip.track,
        "start_frame": clip.start_frame,
        "end_frame": clip.end_frame,
        "source_in": clip.source_in,
        "duration_frames": clip.duration_frames,
        "has_audio": clip.has_audio,
        "volume": clip.volume,
        "color_grade": dict(clip.color_grade),
    } for clip in project.clips)

    return ProjectContext(
        schema_version=1,
        project={
            "fps": project.fps,
            "width": project.width,
            "height": project.height,
            "duration_frames": project.duration_frames,
            "duration_seconds": project.duration_frames / project.fps,
            "video_tracks": list(project.video_tracks),
            "audio_tracks": list(project.audio_tracks),
            "clip_count": len(project.clips),
        },
        assets=tuple(items),
        timeline_clips=timeline,
        warnings=tuple(warnings),
    )
