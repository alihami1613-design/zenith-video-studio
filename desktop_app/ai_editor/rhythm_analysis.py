"""Conservative tempo/pulse candidates derived from local RMS energy envelopes.

This is not spectral-flux beat tracking. It estimates periodic energy pulses and
reports confidence/warnings so an editor can review them against the actual music.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from ai_editor.audio_energy import AudioEnergyAnalysis


@dataclass(frozen=True)
class RhythmAnalysis:
    estimated_bpm: float | None
    confidence: float
    pulse_period_seconds: float | None
    pulse_candidates_seconds: tuple[float, ...]
    analyzed_duration_seconds: float
    warnings: tuple[str, ...]
    requires_user_review: bool = True
    analyzer_name: str = "RMS envelope autocorrelation"


def analyze_music_rhythm(
    energy: AudioEnergyAnalysis,
    *,
    minimum_bpm: int = 70,
    maximum_bpm: int = 160,
    minimum_confidence: float = 0.18,
) -> RhythmAnalysis:
    """Estimate recurring energy pulses from an existing RMS envelope."""
    if not isinstance(energy, AudioEnergyAnalysis):
        raise TypeError("A measured AudioEnergyAnalysis is required.")
    if (isinstance(minimum_bpm, bool) or not isinstance(minimum_bpm, int)
            or isinstance(maximum_bpm, bool) or not isinstance(maximum_bpm, int)
            or not 40 <= minimum_bpm < maximum_bpm <= 200):
        raise ValueError("BPM bounds must satisfy 40 <= minimum < maximum <= 200.")
    if (isinstance(minimum_confidence, bool)
            or not isinstance(minimum_confidence, (int, float))
            or not math.isfinite(minimum_confidence)
            or not 0.0 <= minimum_confidence <= 1.0):
        raise ValueError("Minimum confidence must be between 0 and 1.")

    points = energy.energy_envelope
    if len(points) < 32 or energy.window_seconds <= 0:
        return RhythmAnalysis(
            None, 0.0, None, (), energy.analyzed_duration_seconds,
            ("Not enough audio envelope data for a stable pulse estimate.",),
        )

    levels = [float(point.rms) for point in points]
    if any(not math.isfinite(value) or value < 0 for value in levels):
        raise ValueError("Energy envelope contains invalid RMS values.")

    # Positive energy changes form a simple onset-strength proxy.
    novelty = [0.0]
    novelty.extend(max(0.0, levels[i] - levels[i - 1]) for i in range(1, len(levels)))
    mean = sum(novelty) / len(novelty)
    centered = [value - mean for value in novelty]
    variance = sum(value * value for value in centered)
    if variance <= 1e-12:
        return RhythmAnalysis(
            None, 0.0, None, (), energy.analyzed_duration_seconds,
            ("Audio energy has no meaningful periodic rises.",),
        )

    window = float(energy.window_seconds)
    min_lag = max(1, math.floor(60.0 / (maximum_bpm * window)))
    max_lag = min(len(centered) // 2, math.ceil(60.0 / (minimum_bpm * window)))
    if max_lag < min_lag:
        return RhythmAnalysis(
            None, 0.0, None, (), energy.analyzed_duration_seconds,
            ("Audio is too short for the configured tempo range.",),
        )

    scores: list[tuple[float, int]] = []
    for lag in range(min_lag, max_lag + 1):
        numerator = sum(centered[i] * centered[i - lag] for i in range(lag, len(centered)))
        denominator = sum(centered[i] * centered[i] for i in range(lag, len(centered)))
        score = numerator / denominator if denominator > 1e-12 else 0.0
        scores.append((score, lag))
    best_score, best_lag = max(scores, key=lambda item: item[0])
    confidence = max(0.0, min(1.0, best_score))
    bpm = 60.0 / (best_lag * window)

    if confidence < minimum_confidence:
        return RhythmAnalysis(
            None, confidence, None, (), energy.analyzed_duration_seconds,
            ("No sufficiently reliable recurring energy pulse was found; no beat markers were emitted.",
             "RMS periodicity is only a tempo hint, not verified musical beat tracking."),
        )

    # Select the phase with the strongest accumulated onset energy.
    phase_scores = []
    for phase in range(best_lag):
        score = sum(max(0.0, novelty[index]) for index in range(phase, len(novelty), best_lag))
        phase_scores.append((score, phase))
    _, best_phase = max(phase_scores, key=lambda item: item[0])
    pulse_times = tuple(
        round(index * window, 3)
        for index in range(best_phase, len(points), best_lag)
        if index * window < energy.analyzed_duration_seconds
    )
    warnings = (
        "Estimated tempo is inferred from RMS energy periodicity, not spectral beat tracking.",
        "Half-time/double-time ambiguity and syncopation may shift the estimated BPM.",
        "Pulse candidates are review markers only; no media or timeline edits were made.",
    )
    return RhythmAnalysis(
        estimated_bpm=round(bpm, 2),
        confidence=round(confidence, 3),
        pulse_period_seconds=round(best_lag * window, 4),
        pulse_candidates_seconds=pulse_times,
        analyzed_duration_seconds=energy.analyzed_duration_seconds,
        warnings=warnings,
    )
