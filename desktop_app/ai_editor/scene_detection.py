"""Bounded local shot-boundary detection using FFmpeg's scene-change metric.

This identifies visual cuts/shot changes; it does not infer semantic scene meaning.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re
import shutil
import subprocess
from typing import Callable


@dataclass(frozen=True)
class SceneBoundary:
    timestamp_seconds: float


@dataclass(frozen=True)
class SceneDetection:
    asset_path: str
    duration_seconds: float
    threshold: float
    boundaries: tuple[SceneBoundary, ...]
    analyzer_name: str = "FFmpeg scene-change detector"


def _ffmpeg_path() -> str:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError("FFmpeg is required for scene detection.") from exc


def detect_scene_changes(
    path: str | Path,
    duration_seconds: float,
    *,
    threshold: float = 0.35,
    minimum_spacing_seconds: float = 0.35,
    max_boundaries: int = 500,
    ffmpeg_executable: str | None = None,
    run: Callable = subprocess.run,
) -> SceneDetection:
    """Find likely shot transitions locally with bounded frame size and output count."""
    media_path = Path(path).expanduser().resolve()
    if not media_path.is_file():
        raise FileNotFoundError(str(media_path))
    if (isinstance(duration_seconds, bool)
            or not isinstance(duration_seconds, (int, float))
            or not math.isfinite(duration_seconds)
            or not 0 < duration_seconds <= 86400):
        raise ValueError("Duration must be greater than zero and no more than 24 hours.")
    if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold) or not 0.05 <= threshold <= 0.95):
        raise ValueError("Scene threshold must be between 0.05 and 0.95.")
    if (isinstance(minimum_spacing_seconds, bool)
            or not isinstance(minimum_spacing_seconds, (int, float))
            or not math.isfinite(minimum_spacing_seconds)
            or not 0.05 <= minimum_spacing_seconds <= 30):
        raise ValueError("Minimum spacing must be between 0.05 and 30 seconds.")
    if isinstance(max_boundaries, bool) or not isinstance(max_boundaries, int) or not 1 <= max_boundaries <= 5000:
        raise ValueError("Maximum boundaries must be between 1 and 5000.")

    executable = ffmpeg_executable or _ffmpeg_path()
    video_filter = (
        f"scale=320:-2,format=gray,select='gt(scene,{threshold:.3f})',showinfo"
    )
    command = [
        executable, "-hide_banner", "-nostats", "-loglevel", "info",
        "-i", str(media_path), "-t", f"{duration_seconds:.3f}",
        "-vf", video_filter, "-an", "-sn", "-dn", "-f", "null", "-",
    ]
    try:
        result = run(command, capture_output=True, text=False, timeout=300, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"FFmpeg scene detection failed: {exc}") from exc

    stderr = getattr(result, "stderr", "")
    if isinstance(stderr, bytes):
        log = stderr.decode("utf-8", errors="replace")
    else:
        log = stderr if isinstance(stderr, str) else ""
    timestamps = sorted({
        float(value) for value in re.findall(
            r"\bpts_time:([0-9]+(?:\.[0-9]+)?)", log
        )
        if 0 < float(value) < duration_seconds
    })

    boundaries: list[SceneBoundary] = []
    for timestamp in timestamps:
        if not boundaries or timestamp - boundaries[-1].timestamp_seconds >= minimum_spacing_seconds:
            boundaries.append(SceneBoundary(timestamp))
        if len(boundaries) >= max_boundaries:
            break

    return SceneDetection(
        asset_path=str(media_path),
        duration_seconds=float(duration_seconds),
        threshold=float(threshold),
        boundaries=tuple(boundaries),
    )
