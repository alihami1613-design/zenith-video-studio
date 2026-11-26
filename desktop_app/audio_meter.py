"""Lightweight, waveform-cache-based audio peak estimates for mixer UI."""
from __future__ import annotations

import math
from typing import Iterable, Mapping


POINTS_PER_SECOND = 20


def estimate_track_peaks(
    clips: Iterable[object],
    waveforms: Mapping[str, list[float]],
    fps: int,
    track_settings: Mapping[str, dict] | None = None,
    tracks: Iterable[str] = ("A1", "A2", "A3", "A4"),
) -> dict[str, float]:
    """Return conservative 0..1.5 peak estimates; these are not live meters."""
    if fps < 1:
        raise ValueError("FPS must be positive")
    settings = track_settings or {}
    solo = {name for name, value in settings.items() if value.get("solo", False)}
    result = {track: 0.0 for track in tracks}
    for clip in clips:
        if getattr(clip, "media_type", "") != "audio" or clip.track not in result:
            continue
        track_setting = settings.get(clip.track, {})
        if track_setting.get("muted", False) or (solo and clip.track not in solo):
            continue
        values = waveforms.get(clip.path, [])
        if not values:
            continue
        start = max(0, round(clip.source_in / fps * POINTS_PER_SECOND))
        end = min(len(values), start + max(1, round(clip.duration_frames / fps * POINTS_PER_SECOND)))
        peak = max((float(v) for v in values[start:end]), default=0.0)
        clip_gain = float(getattr(clip, "volume", 1.0))
        track_gain = float(track_setting.get("volume", 1.0))
        if not math.isfinite(clip_gain) or not 0 <= clip_gain <= 2:
            raise ValueError("Invalid clip gain")
        if not math.isfinite(track_gain) or not 0 <= track_gain <= 2:
            raise ValueError("Invalid track gain")
        # Sum clip peaks to avoid hiding possible overlap; cap at 150% for display.
        result[clip.track] = min(1.5, result[clip.track] + peak * clip_gain * track_gain)
    return result


def peak_to_dbfs(peak: float) -> str:
    value = max(0.0, float(peak))
    if value <= 1e-6:
        return "-∞ dBFS"
    return f"{20 * math.log10(value):.1f} dBFS"
