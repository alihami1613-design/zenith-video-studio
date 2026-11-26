"""Lightweight FFmpeg filter-chain builder for per-clip color grading."""
from __future__ import annotations

import math
from typing import Mapping


DEFAULT_GRADE = {
    "exposure": 0.0,
    "contrast": 1.0,
    "saturation": 1.0,
    "temperature": 0.0,
    "tint": 0.0,
    "highlights": 0.0,
    "shadows": 0.0,
    "whites": 0.0,
    "blacks": 0.0,
    "wheel_shadows_r": 0.0, "wheel_shadows_g": 0.0, "wheel_shadows_b": 0.0,
    "wheel_midtones_r": 0.0, "wheel_midtones_g": 0.0, "wheel_midtones_b": 0.0,
    "wheel_highlights_r": 0.0, "wheel_highlights_g": 0.0, "wheel_highlights_b": 0.0,
}


def build_color_filter(grade: Mapping[str, float] | None) -> str:
    """Build a low-cost SDR filter chain; empty string means no grade."""
    values = dict(DEFAULT_GRADE)
    values.update(grade or {})
    bounds = {
        "exposure": (-4.0, 4.0),
        "contrast": (0.0, 2.0),
        "saturation": (0.0, 3.0),
        "temperature": (-1.0, 1.0),
        "tint": (-1.0, 1.0),
        "highlights": (-1.0, 1.0),
        "shadows": (-1.0, 1.0),
        "whites": (-1.0, 1.0),
        "blacks": (-1.0, 1.0),
        "wheel_shadows_r": (-1.0, 1.0), "wheel_shadows_g": (-1.0, 1.0), "wheel_shadows_b": (-1.0, 1.0),
        "wheel_midtones_r": (-1.0, 1.0), "wheel_midtones_g": (-1.0, 1.0), "wheel_midtones_b": (-1.0, 1.0),
        "wheel_highlights_r": (-1.0, 1.0), "wheel_highlights_g": (-1.0, 1.0), "wheel_highlights_b": (-1.0, 1.0),
    }
    for key, (low, high) in bounds.items():
        value = float(values[key])
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"Invalid color grade value: {key}")
        values[key] = value

    filters = []
    if values["exposure"] != 0:
        filters.append(f"exposure=exposure={values['exposure']:.3f}")
    if values["contrast"] != 1 or values["saturation"] != 1:
        filters.append(
            f"eq=contrast={values['contrast']:.3f}:saturation={values['saturation']:.3f}"
        )
    temperature = values["temperature"]
    tint = values["tint"]
    wheel_keys = (
        "wheel_shadows_r", "wheel_shadows_g", "wheel_shadows_b",
        "wheel_midtones_r", "wheel_midtones_g", "wheel_midtones_b",
        "wheel_highlights_r", "wheel_highlights_g", "wheel_highlights_b",
    )
    if temperature != 0 or tint != 0 or any(values[key] != 0 for key in wheel_keys):
        # Global temperature/tint are layered on top of the three tonal wheels.
        red = temperature * 0.15
        blue = -temperature * 0.15
        green_magenta = -tint * 0.15
        channels = {
            "rs": values["wheel_shadows_r"] * 0.15 + red,
            "gs": values["wheel_shadows_g"] * 0.15 + green_magenta,
            "bs": values["wheel_shadows_b"] * 0.15 + blue,
            "rm": values["wheel_midtones_r"] * 0.15 + red,
            "gm": values["wheel_midtones_g"] * 0.15 + green_magenta,
            "bm": values["wheel_midtones_b"] * 0.15 + blue,
            "rh": values["wheel_highlights_r"] * 0.15 + red,
            "gh": values["wheel_highlights_g"] * 0.15 + green_magenta,
            "bh": values["wheel_highlights_b"] * 0.15 + blue,
        }
        filters.append("colorbalance=" + ":".join(
            f"{key}={value:.3f}" for key, value in channels.items()
        ))
    # Five-point master curve adds inexpensive luma-oriented tonal controls.
    # Keep output points strictly increasing for extreme combined slider values.
    tonal = {key: values[key] for key in ("highlights", "shadows", "whites", "blacks")}
    if any(value != 0 for value in tonal.values()):
        points = [
            (0.0, tonal["blacks"] * 0.08),
            (0.25, 0.25 + tonal["shadows"] * 0.07 + tonal["blacks"] * 0.025),
            (0.5, 0.5 + tonal["shadows"] * 0.015 + tonal["highlights"] * 0.015),
            (0.75, 0.75 + tonal["highlights"] * 0.07 + tonal["whites"] * 0.025),
            (1.0, 1.0 + tonal["whites"] * 0.08),
        ]
        adjusted = []
        for index, (x, y) in enumerate(points):
            lower = adjusted[-1][1] + 0.001 if adjusted else 0.0
            upper = 1.0 - (len(points) - index - 1) * 0.001
            adjusted.append((x, min(upper, max(lower, y))))
        curve = " ".join(f"{x:.3f}/{y:.3f}" for x, y in adjusted)
        filters.append(f"curves=master='{curve}'")
    return ",".join(filters)
