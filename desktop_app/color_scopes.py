"""Low-cost RGB histogram sampling and Qt display for the Color panel."""
from __future__ import annotations

import subprocess
from pathlib import Path

from proxy_manager import find_ffmpeg
from video_color import build_color_filter


SCOPE_WIDTH = 256
SCOPE_HEIGHT = 144


def build_histogram_command(ffmpeg: str, source: str | Path, timestamp: float, grade: dict[str, float] | None = None) -> list[str]:
    if timestamp < 0:
        raise ValueError("Histogram timestamp cannot be negative")
    video_filters = [
        "scale=256:144:force_original_aspect_ratio=decrease",
        "pad=256:144:(ow-iw)/2:(oh-ih)/2",
        "setsar=1",
    ]
    color_filter = build_color_filter(grade)
    if color_filter:
        video_filters.append(color_filter)
    return [
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-threads", "1", "-filter_threads", "1",
        "-ss", f"{timestamp:.6f}", "-i", str(Path(source)),
        "-frames:v", "1", "-an",
        "-vf", ",".join(video_filters),
        "-threads", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
    ]


def calculate_rgb_histogram(rgb24: bytes) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    expected = SCOPE_WIDTH * SCOPE_HEIGHT * 3
    if len(rgb24) != expected:
        raise ValueError(f"Expected {expected} RGB bytes, received {len(rgb24)}")
    channels = [[0] * 256 for _ in range(3)]
    for offset in range(0, expected, 3):
        channels[0][rgb24[offset]] += 1
        channels[1][rgb24[offset + 1]] += 1
        channels[2][rgb24[offset + 2]] += 1
    return tuple(tuple(channel) for channel in channels)  # type: ignore[return-value]


def extract_rgb_frame(source: str | Path, timestamp: float = 0.0,
                      grade: dict[str, float] | None = None,
                      timeout_seconds: int = 30) -> bytes:
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    command = build_histogram_command(find_ffmpeg(), path, timestamp, grade)
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout_seconds, check=True)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("RGB scope sampling timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"RGB scope sampling failed: {detail[-800:]}") from exc
    expected = SCOPE_WIDTH * SCOPE_HEIGHT * 3
    if len(result.stdout) != expected:
        raise RuntimeError(f"FFmpeg returned {len(result.stdout)} bytes; expected {expected}")
    return result.stdout


def extract_rgb_histogram(source: str | Path, timestamp: float = 0.0,
                          grade: dict[str, float] | None = None,
                          timeout_seconds: int = 30) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    return calculate_rgb_histogram(extract_rgb_frame(source, timestamp, grade, timeout_seconds))

