"""Frame-based speed-ramp segmentation shared by audio and video renderers."""
from __future__ import annotations

import math


def _rate_at(points: list[dict], frame: float) -> float:
    if not points:
        return 1.0
    if frame <= int(points[0]["frame"]):
        return float(points[0]["rate"])
    if frame >= int(points[-1]["frame"]):
        return float(points[-1]["rate"])
    for left, right in zip(points, points[1:]):
        start, end = int(left["frame"]), int(right["frame"])
        if start <= frame <= end:
            amount = (frame - start) / (end - start)
            return float(left["rate"]) + (float(right["rate"]) - float(left["rate"])) * amount
    return 1.0


def build_speed_segments(
    duration_frames: int,
    fps: int,
    keyframes: list[dict] | None,
    max_segment_frames: int = 6,
) -> list[dict[str, float | int]]:
    """Approximate a linear speed curve with short, constant-rate segments.

    Each segment's average rate preserves the integral (source duration) of the
    linear ramp over that interval. Six frames keeps filter graph size bounded
    while producing a smooth-enough change at normal 25/30 fps.
    """
    if duration_frames < 1 or fps < 1 or max_segment_frames < 1:
        raise ValueError("Speed-ramp duration, FPS and segment size must be positive")
    points = sorted(
        ({"frame": int(item["frame"]), "rate": float(item["rate"])}
         for item in (keyframes or [])),
        key=lambda item: item["frame"],
    )
    previous = -1
    for point in points:
        if (point["frame"] < 0 or point["frame"] >= duration_frames
                or point["frame"] <= previous
                or not math.isfinite(point["rate"])
                or not 0.25 <= point["rate"] <= 4.0):
            raise ValueError("Invalid speed-ramp keyframe")
        previous = point["frame"]

    if not points:
        return [{
            "timeline_start_frame": 0, "timeline_frames": duration_frames,
            "rate": 1.0, "source_start_frames": 0.0,
            "source_duration_frames": float(duration_frames),
        }]
    if all(abs(float(point["rate"]) - float(points[0]["rate"])) < 1e-9 for point in points):
        rate = float(points[0]["rate"])
        return [{
            "timeline_start_frame": 0, "timeline_frames": duration_frames,
            "rate": rate, "source_start_frames": 0.0,
            "source_duration_frames": duration_frames * rate,
        }]

    boundaries = sorted({0, duration_frames, *(point["frame"] for point in points)})
    segments: list[dict[str, float | int]] = []
    source_cursor = 0.0
    for left, right in zip(boundaries, boundaries[1:]):
        span = right - left
        count = max(1, math.ceil(span / max_segment_frames))
        for part in range(count):
            start = left + span * part / count
            end = left + span * (part + 1) / count
            rate_start = _rate_at(points, start)
            rate_end = _rate_at(points, end)
            rate = (rate_start + rate_end) / 2.0
            timeline_frames = end - start
            source_frames = timeline_frames * rate
            segments.append({
                "timeline_start_frame": round(start, 6),
                "timeline_frames": timeline_frames,
                "rate": rate,
                "source_start_frames": source_cursor,
                "source_duration_frames": source_frames,
            })
            source_cursor += source_frames
    return segments
