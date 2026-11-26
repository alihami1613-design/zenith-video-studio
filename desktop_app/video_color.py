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
    if temperature != 0 or tint != 0:
        red = temperature * 0.15
        blue = -temperature * 0.15
        green_magenta = -tint * 0.15
        filters.append(
            "colorbalance="
            f"rs={red:.3f}:gs={green_magenta:.3f}:bs={blue:.3f}:"
            f"rm={red:.3f}:gm={green_magenta:.3f}:bm={blue:.3f}:"
            f"rh={red:.3f}:gh={green_magenta:.3f}:bh={blue:.3f}"
        )
    return ",".join(filters)
