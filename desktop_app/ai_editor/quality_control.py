"""Pre-export quality checks for AI-generated and manually edited timelines."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from ai_editor.project_context import ProjectContext
from timeline_model import TimelineProject


@dataclass(frozen=True)
class QCIssue:
    check_id: str
    severity: str
    message: str
    clip_id: str | None = None


@dataclass(frozen=True)
class QCReport:
    ready_for_export: bool
    error_count: int
    warning_count: int
    issues: tuple[QCIssue, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def run_quality_checks(project: TimelineProject,
                       context: ProjectContext | None = None) -> QCReport:
    """Inspect structural, source-media, and basic editorial risks without rendering."""
    issues: list[QCIssue] = []

    def add(check_id: str, severity: str, message: str,
            clip_id: str | None = None) -> None:
        issues.append(QCIssue(check_id, severity, message, clip_id))

    if project.fps < 1 or project.width < 1 or project.height < 1:
        add("project_format", "error", "Project frame rate or dimensions are invalid.")

    try:
        project.__post_init__()
        for clip in project.clips:
            clip.validate()
    except (TypeError, ValueError, AttributeError) as exc:
        add("timeline_integrity", "error", f"Timeline validation failed: {exc}")

    inventory = {}
    if context is not None:
        inventory = {
            str(Path(item.asset.path).expanduser().resolve()).casefold(): item
            for item in context.assets
        }

    for clip in project.clips:
        source = Path(clip.path).expanduser()
        if not source.is_file():
            add("missing_media", "error",
                f"Source media is missing: {source.name}", clip.clip_id)
            continue
        item = inventory.get(str(source.resolve()).casefold())
        if item is not None and item.asset.duration_frames > 0:
            used_frames = round(clip.duration_frames * clip.playback_rate)
            if clip.source_in + used_frames > item.asset.duration_frames:
                add("source_overrun", "error",
                    "Clip uses frames beyond the available source duration.", clip.clip_id)
        if clip.media_type == "audio" and clip.track.startswith("V"):
            add("track_media_mismatch", "error",
                "Audio-only media is placed on a video track.", clip.clip_id)
        if clip.media_type == "video" and clip.track.startswith("A"):
            add("track_media_mismatch", "error",
                "Video media is placed on an audio-only track.", clip.clip_id)
        if clip.volume > 1.0:
            add("audio_gain", "warning",
                "Clip gain is above unity; check for clipping in the final mix.", clip.clip_id)

    primary = sorted(
        (clip for clip in project.clips
         if clip.track == "V1" and clip.media_type == "video"),
        key=lambda clip: (clip.start_frame, clip.clip_id),
    )
    for previous, current in zip(primary, primary[1:]):
        if current.start_frame > previous.end_frame:
            add("primary_track_gap", "warning",
                f"Primary video track has a {current.start_frame - previous.end_frame}-frame gap.",
                current.clip_id)

    errors = sum(issue.severity == "error" for issue in issues)
    warnings = sum(issue.severity == "warning" for issue in issues)
    return QCReport(errors == 0, errors, warnings, tuple(issues))
