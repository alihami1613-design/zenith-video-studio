"""Low-overhead media metadata probing for ZENITH Desktop.

Prefer ffprobe JSON when available. If the imageio-ffmpeg package supplies only
an ffmpeg executable, parse ffmpeg's input summary as a compatibility fallback.
No media frames are decoded by this module.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any


def _ffprobe_executable() -> str | None:
    found = shutil.which("ffprobe")
    if found:
        return found
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        sibling = Path(ffmpeg).with_name("ffprobe.exe" if ffmpeg.lower().endswith(".exe") else "ffprobe")
        if sibling.is_file():
            return str(sibling)
    try:
        import imageio_ffmpeg
        ffmpeg_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
        sibling = ffmpeg_path.with_name("ffprobe.exe" if ffmpeg_path.suffix.lower() == ".exe" else "ffprobe")
        if sibling.is_file():
            return str(sibling)
    except Exception:
        pass
    return None


def _fraction(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    try:
        result = float(Fraction(value))
        return result if result > 0 else None
    except (ValueError, ZeroDivisionError):
        try:
            result = float(value)
            return result if result > 0 else None
        except (ValueError, TypeError):
            return None


def _from_ffprobe(path: Path, executable: str) -> dict[str, Any]:
    command = [
        executable, "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,width,height,avg_frame_rate,r_frame_rate,duration,sample_rate,channels",
        "-of", "json", str(path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=True)
    payload = json.loads(completed.stdout or "{}")
    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    raw_duration = (payload.get("format") or {}).get("duration")
    if raw_duration in (None, "N/A"):
        raw_duration = video.get("duration") or audio.get("duration")
    duration = float(raw_duration) if raw_duration not in (None, "N/A") else None
    fps = _fraction(video.get("avg_frame_rate")) or _fraction(video.get("r_frame_rate"))
    return {
        "path": str(path),
        "duration_seconds": duration,
        "width": int(video["width"]) if video.get("width") else None,
        "height": int(video["height"]) if video.get("height") else None,
        "fps": fps,
        "has_video": bool(video),
        "has_audio": bool(audio),
        "sample_rate": int(audio["sample_rate"]) if audio.get("sample_rate") else None,
        "channels": int(audio["channels"]) if audio.get("channels") else None,
        "probe_method": "ffprobe",
        "probe_error": None,
    }


def _from_ffmpeg_summary(path: Path, executable: str) -> dict[str, Any]:
    completed = subprocess.run(
        [executable, "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    summary = completed.stderr or completed.stdout
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", summary)
    duration = None
    if duration_match:
        hours, minutes, seconds = duration_match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    video_match = re.search(
        r"Stream #.*?Video:.*?(\d{2,6})x(\d{2,6}).*?(\d+(?:\.\d+)?)\s*fps",
        summary, re.IGNORECASE,
    )
    audio_match = re.search(r"Stream #.*?Audio:", summary, re.IGNORECASE)
    width = int(video_match.group(1)) if video_match else None
    height = int(video_match.group(2)) if video_match else None
    fps = float(video_match.group(3)) if video_match else None
    has_video = video_match is not None or bool(re.search(r"Video:", summary, re.IGNORECASE))
    has_audio = audio_match is not None
    if duration is None and not has_video and not has_audio:
        raise RuntimeError("FFmpeg نتوانست اطلاعات فایل را تشخیص دهد.")
    return {
        "path": str(path), "duration_seconds": duration,
        "width": width, "height": height, "fps": fps,
        "has_video": has_video, "has_audio": has_audio,
        "sample_rate": None, "channels": None,
        "probe_method": "ffmpeg-summary", "probe_error": None,
    }


def probe_media(path: str | Path) -> dict[str, Any]:
    """Return media metadata without decoding or rendering the media."""
    media_path = Path(path).expanduser().resolve()
    if not media_path.is_file():
        raise FileNotFoundError(str(media_path))
    executable = _ffprobe_executable()
    try:
        if executable:
            return _from_ffprobe(media_path, executable)
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        return _from_ffmpeg_summary(media_path, ffmpeg)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"خواندن مشخصات رسانه ناموفق بود: {exc}") from exc


def duration_to_frames(duration_seconds: float | None, fps: int) -> int | None:
    """Convert a known positive duration to project frames, rounded safely."""
    if duration_seconds is None or duration_seconds <= 0 or fps <= 0:
        return None
    return max(1, round(duration_seconds * fps))
