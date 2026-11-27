"""Bounded, opt-in visual frame sampling for AI-assisted editorial analysis.

Frames are extracted locally with FFmpeg. This module does not upload media or
call a vision model; a separate analyzer adapter may consume the returned frames.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Callable, Protocol, Sequence

from ai_editor.contracts import EditPlanError


@dataclass(frozen=True)
class SampledFrame:
    timestamp_seconds: float
    jpeg_bytes: bytes
    width: int
    height: int


@dataclass(frozen=True)
class VisualAnalysis:
    asset_path: str
    frames: tuple[SampledFrame, ...]
    observations: tuple[str, ...]
    analyzer_name: str


class VisionAnalyzer(Protocol):
    name: str
    is_remote: bool

    def describe_frames(self, frames: Sequence[SampledFrame]) -> Sequence[str]:
        """Describe sampled frames; remote implementations may transmit image data."""
        ...


def _ffmpeg_path() -> str:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError("FFmpeg is required for visual frame sampling.") from exc


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Read JPEG SOF dimensions without requiring an imaging dependency."""
    if len(data) < 4 or data[:2] != b"\\xff\\xd8":
        raise RuntimeError("FFmpeg output is not a valid JPEG image.")
    index = 2
    while index + 4 <= len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            break
        marker = data[index]
        index += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            break
        segment_length = int.from_bytes(data[index:index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            break
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if segment_length < 7:
                break
            height = int.from_bytes(data[index + 3:index + 5], "big")
            width = int.from_bytes(data[index + 5:index + 7], "big")
            if width > 0 and height > 0:
                return width, height
            break
        index += segment_length
    raise RuntimeError("Could not read JPEG frame dimensions.")


def sample_video_frames(
    path: str | Path,
    duration_seconds: float,
    *,
    sample_count: int = 6,
    max_dimension: int = 768,
    ffmpeg_executable: str | None = None,
    run: Callable = subprocess.run,
) -> tuple[SampledFrame, ...]:
    """Extract evenly spaced, low-resolution JPEG samples with strict resource bounds."""
    media_path = Path(path).expanduser().resolve()
    if not media_path.is_file():
        raise FileNotFoundError(str(media_path))
    if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, (int, float)) or duration_seconds <= 0:
        raise EditPlanError("Video duration must be a positive number of seconds.")
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or not 1 <= sample_count <= 24:
        raise EditPlanError("Sample count must be between 1 and 24.")
    if isinstance(max_dimension, bool) or not isinstance(max_dimension, int) or not 64 <= max_dimension <= 1280:
        raise EditPlanError("Maximum frame dimension must be between 64 and 1280 pixels.")

    executable = ffmpeg_executable or _ffmpeg_path()
    timestamps = (
        [duration_seconds / 2.0]
        if sample_count == 1
        else [duration_seconds * (index + 0.5) / sample_count for index in range(sample_count)]
    )
    frames: list[SampledFrame] = []
    with tempfile.TemporaryDirectory(prefix="zenith-visual-") as folder:
        for index, timestamp in enumerate(timestamps):
            output = Path(folder) / f"frame-{index:02d}.jpg"
            command = [
                executable, "-hide_banner", "-loglevel", "error", "-ss",
                f"{timestamp:.3f}", "-i", str(media_path), "-frames:v", "1",
                "-vf", f"scale='min({max_dimension},iw)':'min({max_dimension},ih)':force_original_aspect_ratio=decrease",
                "-q:v", "5", "-y", str(output),
            ]
            try:
                run(command, capture_output=True, timeout=30, check=True)
                data = output.read_bytes()
            except (OSError, subprocess.SubprocessError) as exc:
                raise RuntimeError(f"Could not sample frame at {timestamp:.2f}s: {exc}") from exc
            if not data:
                raise RuntimeError(f"FFmpeg produced an empty frame at {timestamp:.2f}s.")
            width, height = _jpeg_dimensions(data)
            frames.append(SampledFrame(timestamp, data, width, height))
    return tuple(frames)


def analyze_video_visuals(
    path: str | Path,
    duration_seconds: float,
    analyzer: VisionAnalyzer,
    *,
    allow_cloud_media_analysis: bool = False,
    sample_count: int = 6,
    max_dimension: int = 768,
) -> VisualAnalysis:
    """Sample locally, then invoke an explicitly supplied local or consented remote analyzer."""
    if analyzer is None or not callable(getattr(analyzer, "describe_frames", None)):
        raise EditPlanError("A configured visual analyzer is required.")
    if getattr(analyzer, "is_remote", False) and allow_cloud_media_analysis is not True:
        raise EditPlanError("Cloud visual analysis requires explicit user permission.")
    frames = sample_video_frames(
        path, duration_seconds, sample_count=sample_count, max_dimension=max_dimension
    )
    descriptions = analyzer.describe_frames(frames)
    if isinstance(descriptions, (str, bytes)) or not isinstance(descriptions, Sequence):
        raise EditPlanError("Visual analyzer must return a sequence of observations.")
    observations = tuple(
        item.strip() for item in descriptions
        if isinstance(item, str) and item.strip()
    )
    if len(observations) != len(frames):
        raise EditPlanError("Visual analyzer must return one observation per sampled frame.")
    return VisualAnalysis(
        asset_path=str(Path(path).expanduser().resolve()),
        frames=frames,
        observations=observations,
        analyzer_name=str(getattr(analyzer, "name", type(analyzer).__name__)),
    )
