"""Low-resolution, short-range Speed Ramp previews with a bounded cache key."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from proxy_manager import find_ffmpeg
from speed_ramp import build_speed_segments

PREVIEW_VERSION = "speed-ramp-preview-v1-480w-15fps"


def default_speed_ramp_cache() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ZENITH" / "SpeedRampPreviews"
    return Path.home() / ".cache" / "zenith" / "speed_ramp_previews"


def speed_ramp_preview_key(source: str | Path, source_in_frame: int,
                           duration_frames: int, fps: int,
                           points: list[dict]) -> str:
    path = Path(source).expanduser().resolve()
    stat = path.stat()
    identity = {
        "path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
        "source_in_frame": int(source_in_frame), "duration_frames": int(duration_frames),
        "fps": int(fps), "points": points, "version": PREVIEW_VERSION,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()


def _preview_segments(duration_frames: int, fps: int, points: list[dict],
                      start_frame: int, end_frame: int) -> list[dict]:
    all_segments = build_speed_segments(duration_frames, fps, points)
    result = []
    source_cursor = 0.0
    for segment in all_segments:
        seg_start = float(segment["timeline_start_frame"])
        seg_end = seg_start + float(segment["timeline_frames"])
        overlap_start = max(seg_start, float(start_frame))
        overlap_end = min(seg_end, float(end_frame))
        if overlap_end <= overlap_start:
            source_cursor += float(segment["source_duration_frames"])
            continue
        rate = float(segment["rate"])
        source_at_overlap = source_cursor + (overlap_start - seg_start) * rate
        result.append({
            "source_start_frames": source_at_overlap,
            "source_duration_frames": (overlap_end - overlap_start) * rate,
            "rate": rate,
            "timeline_frames": overlap_end - overlap_start,
        })
        source_cursor += float(segment["source_duration_frames"])
    cursor = 0.0
    for segment in result:
        segment["preview_start_frames"] = cursor
        cursor += float(segment["timeline_frames"])
    return result


def build_speed_ramp_preview_command(ffmpeg: str, source: str | Path,
                                     destination: str | Path, source_in_frame: int,
                                     duration_frames: int, fps: int,
                                     points: list[dict], preview_start_frame: int,
                                     preview_duration_frames: int) -> list[str]:
    if fps < 1 or duration_frames < 1 or preview_duration_frames < 1:
        raise ValueError("Invalid Speed Ramp preview frame range")
    if preview_start_frame < 0 or preview_start_frame >= duration_frames:
        raise ValueError("Preview start must be inside the clip")
    preview_end = min(duration_frames, preview_start_frame + preview_duration_frames)
    segments = _preview_segments(duration_frames, fps, points, preview_start_frame, preview_end)
    if not segments:
        raise ValueError("No Speed Ramp frames available for preview")
    labels = "".join(f"[v{index}]" for index in range(len(segments)))
    filters = [f"[0:v:0]split={len(segments)}{labels}"]
    outputs = []
    for index, segment in enumerate(segments):
        label = f"p{index}"
        outputs.append(f"[{label}]")
        source_start = (source_in_frame / fps) + float(segment["source_start_frames"]) / fps
        source_duration = float(segment["source_duration_frames"]) / fps
        rate = float(segment["rate"])
        filters.append(
            f"[v{index}]trim=start={source_start:.6f}:duration={source_duration:.6f},"
            f"setpts=(PTS-STARTPTS)/{rate:.6f}[{label}]"
        )
    filters.append(
        f"{''.join(outputs)}concat=n={len(segments)}:v=1:a=0,"
        f"fps=15,scale='min(480,iw)':-2,format=yuv420p[outv]"
    )
    graph = ";".join(filters)
    return [
        str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(Path(source)), "-filter_complex", graph,
        "-map", "[outv]", "-an", "-c:v", "libx264", "-preset", "ultrafast",
        "-crf", "32", "-threads", "1", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(Path(destination)),
    ]


def create_speed_ramp_preview(source: str | Path, source_in_frame: int,
                              duration_frames: int, fps: int, points: list[dict],
                              preview_start_frame: int, preview_duration_frames: int,
                              cache_dir: str | Path | None = None,
                              timeout_seconds: int = 300) -> Path:
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(str(source_path))
    preview_duration_frames = min(preview_duration_frames, duration_frames - preview_start_frame)
    key = speed_ramp_preview_key(
        source_path, source_in_frame, duration_frames, fps, points
    )
    root = Path(cache_dir) if cache_dir is not None else default_speed_ramp_cache()
    target = root / f"{key}-{preview_start_frame}-{preview_duration_frames}.mp4"
    if target.is_file() and target.stat().st_size > 0:
        return target
    root.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.stem + ".partial.mp4")
    partial.unlink(missing_ok=True)
    command = build_speed_ramp_preview_command(
        find_ffmpeg(), source_path, partial, source_in_frame, duration_frames,
        fps, points, preview_start_frame, preview_duration_frames,
    )
    try:
        subprocess.run(command, capture_output=True, text=True,
                       timeout=timeout_seconds, check=True)
        if not partial.is_file() or partial.stat().st_size == 0:
            raise RuntimeError("FFmpeg did not create a Speed Ramp preview.")
        os.replace(partial, target)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Speed Ramp preview exceeded the allowed time.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"Speed Ramp preview failed: {detail[-1200:]}") from exc
    finally:
        partial.unlink(missing_ok=True)
    return target
