"""Bounded local audio-energy envelope and transient-candidate analysis.

This is technical signal analysis, not musical beat tracking or speech understanding.
It decodes a capped mono PCM window locally and returns review-only observations.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import shutil
import struct
import subprocess
from typing import Callable


@dataclass(frozen=True)
class AudioEnergyPoint:
    time_seconds: float
    rms: float
    rms_dbfs: float


@dataclass(frozen=True)
class AudioEnergyAnalysis:
    sample_rate: int
    window_seconds: float
    analyzed_duration_seconds: float
    energy_envelope: tuple[AudioEnergyPoint, ...]
    transient_candidates_seconds: tuple[float, ...]
    warnings: tuple[str, ...]
    requires_user_review: bool = True
    analyzer_name: str = "FFmpeg PCM + RMS energy change"


def _ffmpeg_path() -> str:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError("FFmpeg is required for local audio energy analysis.") from exc


def _rms(samples: tuple[int, ...]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768.0


def analyze_audio_energy(
    path: str | Path,
    *,
    sample_rate: int = 4000,
    window_seconds: float = 0.1,
    max_duration_seconds: int = 1800,
    minimum_candidate_spacing_seconds: float = 0.25,
    ffmpeg_executable: str | None = None,
    run: Callable = subprocess.run,
) -> AudioEnergyAnalysis:
    """Measure RMS energy and conservative transient candidates without editing media."""
    media_path = Path(path).expanduser().resolve()
    if not media_path.is_file():
        raise FileNotFoundError(str(media_path))
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or not 1000 <= sample_rate <= 16000:
        raise ValueError("Sample rate must be an integer between 1000 and 16000 Hz.")
    if (isinstance(window_seconds, bool) or not isinstance(window_seconds, (int, float))
            or not math.isfinite(window_seconds) or not 0.05 <= window_seconds <= 1.0):
        raise ValueError("Energy window must be between 0.05 and 1 second.")
    if isinstance(max_duration_seconds, bool) or not isinstance(max_duration_seconds, int) or not 1 <= max_duration_seconds <= 1800:
        raise ValueError("Maximum analysis duration must be between 1 and 1800 seconds.")
    if (isinstance(minimum_candidate_spacing_seconds, bool)
            or not isinstance(minimum_candidate_spacing_seconds, (int, float))
            or not math.isfinite(minimum_candidate_spacing_seconds)
            or not 0.1 <= minimum_candidate_spacing_seconds <= 2.0):
        raise ValueError("Minimum candidate spacing must be between 0.1 and 2 seconds.")

    samples_per_window = max(1, round(sample_rate * window_seconds))
    max_bytes = max_duration_seconds * sample_rate * 2
    executable = ffmpeg_executable or _ffmpeg_path()
    command = [
        executable, "-hide_banner", "-nostats", "-i", str(media_path),
        "-vn", "-sn", "-dn", "-t", str(max_duration_seconds),
        "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "pipe:1",
    ]
    try:
        result = run(command, capture_output=True, text=False, timeout=90, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"FFmpeg PCM decode failed: {exc}") from exc

    raw = getattr(result, "stdout", b"")
    if not isinstance(raw, bytes):
        raise RuntimeError("FFmpeg returned an unexpected PCM payload.")
    if len(raw) > max_bytes:
        raise RuntimeError("Decoded PCM exceeded the configured memory safety limit.")
    if len(raw) < 2:
        raise RuntimeError("The selected media contains no decodable audio samples.")
    if len(raw) % 2:
        raw = raw[:-1]

    sample_count = len(raw) // 2
    envelope: list[AudioEnergyPoint] = []
    rms_values: list[float] = []
    # Decode one short window at a time: never expand the full PCM payload
    # into millions of Python integers on memory-constrained desktop systems.
    for start in range(0, sample_count, samples_per_window):
        end = min(sample_count, start + samples_per_window)
        byte_start, byte_end = start * 2, end * 2
        block = struct.unpack(f"<{end - start}h", raw[byte_start:byte_end])
        level = _rms(block)
        rms_values.append(level)
        dbfs = 20.0 * math.log10(max(level, 1e-8))
        envelope.append(AudioEnergyPoint(
            time_seconds=start / sample_rate,
            rms=level,
            rms_dbfs=max(-160.0, dbfs),
        ))

    candidates: list[float] = []
    for index in range(1, len(rms_values) - 1):
        baseline_start = max(0, index - 5)
        baseline_values = rms_values[baseline_start:index]
        baseline = sum(baseline_values) / len(baseline_values) if baseline_values else 0.0
        current = rms_values[index]
        rise_threshold = max(0.015, baseline * 0.35)
        is_local_peak = current >= rms_values[index - 1] and current > rms_values[index + 1]
        if current >= 0.02 and current - baseline >= rise_threshold and is_local_peak:
            if not candidates or (index * window_seconds - candidates[-1]) >= minimum_candidate_spacing_seconds:
                candidates.append(index * window_seconds)

    warnings = [
        "Transient candidates are energy changes, not verified musical beats.",
        "RMS energy alone cannot identify speech, instruments, tempo, or musical meaning.",
        "Markers are suggestions only; no clips, cuts, sync, or audio are changed.",
    ]
    if sample_count >= max_duration_seconds * sample_rate:
        warnings.append("Analysis reached the configured duration cap; later audio was not analyzed.")

    return AudioEnergyAnalysis(
        sample_rate=sample_rate,
        window_seconds=float(window_seconds),
        analyzed_duration_seconds=sample_count / sample_rate,
        energy_envelope=tuple(envelope),
        transient_candidates_seconds=tuple(candidates),
        warnings=tuple(warnings),
    )
