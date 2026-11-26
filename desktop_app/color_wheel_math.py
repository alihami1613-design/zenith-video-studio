"""Pure color-wheel coordinate transforms; intentionally Qt-free."""
from __future__ import annotations

import math


def wheel_to_rgb(x: float, y: float) -> tuple[float, float, float]:
    """Map normalized wheel position to balanced RGB offsets in [-1, 1]."""
    length = math.hypot(x, y)
    if length > 1.0:
        x, y = x / length, y / length
    green = -0.5 * x - 0.8660254037844386 * y
    blue = -0.5 * x + 0.8660254037844386 * y
    return (max(-1.0, min(1.0, x)),
            max(-1.0, min(1.0, green)),
            max(-1.0, min(1.0, blue)))


def rgb_to_wheel(red: float, green: float, blue: float) -> tuple[float, float]:
    """Project legacy RGB offsets onto the two-axis color-wheel plane."""
    x = (2.0 * red - green - blue) / 3.0
    y = (blue - green) / 1.7320508075688772
    length = math.hypot(x, y)
    if length > 1.0:
        x, y = x / length, y / length
    return x, y
