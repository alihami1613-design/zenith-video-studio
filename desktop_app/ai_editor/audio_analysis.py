"""Local, bounded FFmpeg audio diagnostics for editorial decision support.

This module measures silence intervals and aggregate peak/RMS levels only.
It does not transcribe speech, identify speakers, upload audio, or call an AI model.
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
class SilenceInterval:
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class AudioAnalysis:
    asset_path: str
    silence_intervals: tuple[SilenceInterval, ...]
    peak_db: float | None
    mean_db: float | None
    analyzer_name: str = "FFmpeg silencedetect + volumedetect"


def _ffmpeg_path() -> str:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError("FFmpeg is required for local audio analysis.") from exc


def _decode_stderr(value: bytes | str | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else ""


def _db_value(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    raw = match.group(1).strip().lower()
    if raw in {"-inf", "+inf", "inf", "nan"}:
        return None
    value = float(raw)
    return value if math.isfinite(value) else None


def analyze_audio(
    path: str | Path,
    *,
    silence_threshold_db: float = -35.0,
    minimum_silence_seconds: float = 0.35,
    ffmpeg_executable: str | None = None,
    run: Callable = subprocess.run,
) -> AudioAnalysis:
    """Measure silence and aggregate levels locally; no audio is retained or transmitted."""
    media_path = Path(path).expanduser().resolve()
    if not media_path.is_file():
        raise FileNotFoundError(str(media_path))
    if (isinstance(silence_threshold_db, bool)
            or not isinstance(silence_threshold_db, (int, float))
            or not math.isfinite(silence_threshold_db)
            or not -90.0 <= silence_threshold_db <= -1.0):
        raise ValueError("Silence threshold must be between -90 and -1 dB.")
    if (isinstance(minimum_silence_seconds, bool)
            or not isinstance(minimum_silence_seconds, (int, float))
            or not math.isfinite(minimum_silence_seconds)
            or not 0.05 <= minimum_silence_seconds <= 10.0):
        raise ValueError("Minimum silence duration must be between 0.05 and 10 seconds.")

    executable = ffmpeg_executable or _ffmpeg_path()
    command = [
        executable, "-hide_banner", "-nostats", "-i", str(media_path),
        "-vn", "-sn", "-dn", "-af",
        f"silencedetect=noise={silence_threshold_db:.2f}dB:d={minimum_silence_seconds:.3f},volumedetect",
        "-f", "null", "-",
    ]
    try:
        result = run(command, capture_output=True, text=False, timeout=120, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"FFmpeg audio analysis failed: {exc}") from exc

    output = _decode_stderr(getattr(result, "stderr", ""))
    starts = [float(item) for item in re.findall(
        r"silence_start:\s*(-?\d+(?:\.\d+)?)", output
    )]
    ends = [float(item) for item in re.findall(
        r"silence_end:\s*(-?\d+(?:\.\d+)?)", output
    )]
    intervals: list[SilenceInterval] = []
    end_index = 0
    for start in starts:
        while end_index < len(ends) and ends[end_index] < start:
            end_index += 1
        if end_index < len(ends):
            end = ends[end_index]
            end_index += 1
            if end >= start:
                intervals.append(SilenceInterval(start, end))

    return AudioAnalysis(
        asset_path=str(media_path),
        silence_intervals=tuple(intervals),
        peak_db=_db_value(r"max_volume:\s*([-+]?\w+\.?\w*)\s*dB", output),
        mean_db=_db_value(r"mean_volume:\s*([-+]?\w+\.?\w*)\s*dB", output),
    )
