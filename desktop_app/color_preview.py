"""Cached, low-resolution graded clip previews built with FFmpeg."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Mapping

from proxy_manager import find_ffmpeg
from video_color import build_color_filter


PREVIEW_VERSION = "graded-preview-v3-three-way-wheels-960w"


def default_color_preview_cache() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ZENITH" / "ColorPreviews"
    return Path.home() / ".cache" / "zenith" / "color_previews"


def color_preview_key(source: str | Path, source_in: float, duration: float,
                      grade: Mapping[str, float]) -> str:
    path = Path(source).expanduser().resolve()
    stat = path.stat()
    identity = {
        "path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
        "source_in": round(float(source_in), 6), "duration": round(float(duration), 6),
        "grade": {key: round(float(value), 6) for key, value in sorted(grade.items())},
        "version": PREVIEW_VERSION,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()


def color_preview_path(source: str | Path, source_in: float, duration: float,
                       grade: Mapping[str, float],
                       cache_dir: str | Path | None = None) -> Path:
    root = Path(cache_dir) if cache_dir is not None else default_color_preview_cache()
    return root / f"{color_preview_key(source, source_in, duration, grade)}.mp4"


def build_color_preview_command(ffmpeg: str, source: str | Path, destination: str | Path,
                                source_in: float, duration: float,
                                grade: Mapping[str, float]) -> list[str]:
    if source_in < 0 or duration <= 0:
        raise ValueError("Invalid source range for color preview")
    color_filter = build_color_filter(grade)
    filters = ["scale='min(960,iw)':-2"]
    if color_filter:
        filters.append(color_filter)
    return [
        str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{source_in:.6f}", "-i", str(Path(source)),
        "-t", f"{duration:.6f}", "-map", "0:v:0", "-map", "0:a?",
        "-vf", ",".join(filters), "-c:v", "libx264", "-preset", "ultrafast",
        "-crf", "28", "-threads", "2", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
        "-sn", str(Path(destination)),
    ]


def create_color_preview(source: str | Path, source_in: float, duration: float,
                         grade: Mapping[str, float],
                         cache_dir: str | Path | None = None,
                         timeout_seconds: int = 3600) -> Path:
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(str(source_path))
    target = color_preview_path(source_path, source_in, duration, grade, cache_dir)
    if target.is_file() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.stem + ".partial.mp4")
    partial.unlink(missing_ok=True)
    command = build_color_preview_command(
        find_ffmpeg(), source_path, partial, source_in, duration, grade
    )
    try:
        subprocess.run(command, capture_output=True, text=True,
                       timeout=timeout_seconds, check=True)
        if not partial.is_file() or partial.stat().st_size == 0:
            raise RuntimeError("FFmpeg did not create a valid color preview.")
        os.replace(partial, target)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Color preview exceeded the allowed time.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"Color preview failed: {detail[-1200:]}") from exc
    finally:
        partial.unlink(missing_ok=True)
    return target
