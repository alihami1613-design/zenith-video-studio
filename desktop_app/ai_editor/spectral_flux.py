"""Bounded local spectral-flux onset analysis for music-aware editing.

Uses NumPy FFT on short mono PCM windows. Results are onset/pulse candidates,
not authoritative beat labels; no media is uploaded or modified.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import shutil
import subprocess
from typing import Callable


@dataclass(frozen=True)
class SpectralFluxAnalysis:
    sample_rate: int
    frame_size: int
    hop_size: int
    analyzed_duration_seconds: float
    onset_envelope: tuple[tuple[float, float], ...]
    onset_candidates_seconds: tuple[float, ...]
    estimated_bpm: float | None
    tempo_confidence: float
    pulse_candidates_seconds: tuple[float, ...]
    warnings: tuple[str, ...]
    requires_user_review: bool = True
    analyzer_name: str = "NumPy STFT spectral flux"


def _ffmpeg_path() -> str:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError("FFmpeg is required for spectral-flux analysis.") from exc


def analyze_spectral_flux(
    path: str | Path,
    *,
    sample_rate: int = 8000,
    frame_size: int = 512,
    hop_size: int = 128,
    max_duration_seconds: int = 120,
    minimum_bpm: int = 70,
    maximum_bpm: int = 160,
    minimum_confidence: float = 0.18,
    ffmpeg_executable: str | None = None,
    run: Callable = subprocess.run,
) -> SpectralFluxAnalysis:
    """Compute positive spectral changes and conservative tempo/pulse candidates."""
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("NumPy is required for spectral-flux analysis.") from exc

    media_path = Path(path).expanduser().resolve()
    if not media_path.is_file():
        raise FileNotFoundError(str(media_path))
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or not 4000 <= sample_rate <= 16000:
        raise ValueError("Sample rate must be between 4000 and 16000 Hz.")
    if isinstance(frame_size, bool) or frame_size not in (256, 512, 1024):
        raise ValueError("Frame size must be 256, 512, or 1024.")
    if isinstance(hop_size, bool) or not isinstance(hop_size, int) or not 64 <= hop_size <= frame_size // 2:
        raise ValueError("Hop size must be between 64 and half the frame size.")
    if isinstance(max_duration_seconds, bool) or not isinstance(max_duration_seconds, int) or not 5 <= max_duration_seconds <= 120:
        raise ValueError("Analysis duration must be between 5 and 120 seconds.")
    if (not isinstance(minimum_bpm, int) or isinstance(minimum_bpm, bool)
            or not isinstance(maximum_bpm, int) or isinstance(maximum_bpm, bool)
            or not 40 <= minimum_bpm < maximum_bpm <= 200):
        raise ValueError("BPM bounds must satisfy 40 <= minimum < maximum <= 200.")
    if (isinstance(minimum_confidence, bool) or not isinstance(minimum_confidence, (int, float))
            or not math.isfinite(minimum_confidence) or not 0 <= minimum_confidence <= 1):
        raise ValueError("Minimum confidence must be between 0 and 1.")

    executable = ffmpeg_executable or _ffmpeg_path()
    command = [
        executable, "-hide_banner", "-nostats", "-i", str(media_path),
        "-vn", "-sn", "-dn", "-t", str(max_duration_seconds),
        "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "pipe:1",
    ]
    try:
        result = run(command, capture_output=True, text=False, timeout=90, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"FFmpeg spectral PCM decode failed ({type(exc).__name__}).") from exc
    raw = getattr(result, "stdout", b"")
    maximum_bytes = max_duration_seconds * sample_rate * 2
    if not isinstance(raw, bytes) or len(raw) < frame_size * 2 or len(raw) > maximum_bytes:
        raise RuntimeError("Decoded PCM is empty or exceeds the configured safety bound.")

    samples = np.frombuffer(raw[:len(raw) - (len(raw) % 2)], dtype="<i2").astype(np.float32)
    samples /= 32768.0
    if samples.size < frame_size:
        raise RuntimeError("Audio is too short for spectral analysis.")

    window = np.hanning(frame_size).astype(np.float32)
    flux_parts = []
    previous = None
    # Chunked STFT keeps peak temporary memory bounded on modest desktop PCs.
    frames_per_chunk = 512
    for start in range(0, samples.size - frame_size + 1, hop_size * frames_per_chunk):
        starts = np.arange(start, min(samples.size - frame_size + 1,
                                      start + hop_size * frames_per_chunk), hop_size)
        frames = np.stack([samples[pos:pos + frame_size] for pos in starts])
        magnitude = np.abs(np.fft.rfft(frames * window, axis=1))
        magnitude /= np.maximum(magnitude.sum(axis=1, keepdims=True), 1e-8)
        if previous is not None:
            first_flux = np.maximum(magnitude[0] - previous, 0).sum()
            chunk_flux = np.maximum(magnitude[1:] - magnitude[:-1], 0).sum(axis=1)
            flux_parts.append(np.concatenate(([first_flux], chunk_flux)))
        else:
            flux_parts.append(np.maximum(magnitude[1:] - magnitude[:-1], 0).sum(axis=1))
        previous = magnitude[-1].copy()

    flux = np.concatenate(flux_parts) if flux_parts else np.empty(0, dtype=np.float32)
    if flux.size < 16 or float(flux.max(initial=0.0)) <= 1e-8:
        return SpectralFluxAnalysis(
            sample_rate, frame_size, hop_size, samples.size / sample_rate,
            (), (), None, 0.0, (),
            ("No reliable spectral onsets were found in the analyzed audio.",),
        )

    # Light smoothing and robust normalization; no claim of semantic music understanding.
    if flux.size >= 3:
        flux = np.convolve(flux, np.array([0.25, 0.5, 0.25]), mode="same")
    scale = float(np.percentile(flux, 95))
    normalized = np.clip(flux / max(scale, 1e-8), 0.0, 1.0)
    times = np.arange(normalized.size) * hop_size / sample_rate

    candidates = []
    for i in range(1, len(normalized) - 1):
        if normalized[i] >= 0.35 and normalized[i] >= normalized[i - 1] and normalized[i] > normalized[i + 1]:
            if not candidates or times[i] - candidates[-1] >= 0.12:
                candidates.append(float(times[i]))

    centered = normalized - float(normalized.mean())
    min_lag = max(1, math.floor(60.0 * sample_rate / (maximum_bpm * hop_size)))
    max_lag = min(len(centered) // 2, math.ceil(60.0 * sample_rate / (minimum_bpm * hop_size)))
    best_score, best_lag = 0.0, 0
    if max_lag >= min_lag and float(np.dot(centered, centered)) > 1e-10:
        for lag in range(min_lag, max_lag + 1):
            denom = float(np.dot(centered[:-lag], centered[:-lag]))
            score = float(np.dot(centered[lag:], centered[:-lag])) / denom if denom > 1e-10 else 0.0
            if score > best_score:
                best_score, best_lag = score, lag

    confidence = max(0.0, min(1.0, best_score))
    bpm = round(60.0 * sample_rate / (best_lag * hop_size), 2) if best_lag else None
    pulse_times: tuple[float, ...] = ()
    if best_lag and confidence >= minimum_confidence:
        phase_scores = [float(normalized[p::best_lag].sum()) for p in range(best_lag)]
        phase = int(np.argmax(phase_scores))
        pulse_times = tuple(round(float(times[i]), 3) for i in range(phase, len(times), best_lag))

    warnings = [
        "Spectral flux detects changes in frequency energy; it does not understand musical structure.",
        "Tempo estimates may have half-time/double-time ambiguity; review against the soundtrack.",
        "Onset and pulse markers are suggestions only; no clips, cuts, or synchronization were changed.",
    ]
    if samples.size >= max_duration_seconds * sample_rate:
        warnings.append("Analysis reached the configured duration cap; later audio was not analyzed.")
    envelope = tuple((round(float(times[i]), 3), round(float(normalized[i]), 4))
                     for i in range(0, len(times), max(1, round(0.1 * sample_rate / hop_size))))
    return SpectralFluxAnalysis(
        sample_rate, frame_size, hop_size, samples.size / sample_rate,
        envelope, tuple(round(value, 3) for value in candidates),
        bpm if confidence >= minimum_confidence else None,
        round(confidence, 3), pulse_times, tuple(warnings),
    )
