"""Pure geometry helpers for polygon-mask editing; intentionally Qt-free."""
from __future__ import annotations


def fitted_video_rect(width: float, height: float, frame_width: float, frame_height: float) -> tuple[float, float, float, float]:
    if min(width, height, frame_width, frame_height) <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    scale = min(width / frame_width, height / frame_height)
    w, h = frame_width * scale, frame_height * scale
    return ((width - w) / 2.0, (height - h) / 2.0, w, h)


def normalized_point_to_widget(point: list[float], rect: tuple[float, float, float, float]) -> tuple[float, float]:
    x, y, width, height = rect
    return (x + float(point[0]) * width, y + float(point[1]) * height)


def widget_point_to_normalized(point: tuple[float, float], rect: tuple[float, float, float, float]) -> list[float]:
    x, y, width, height = rect
    if width <= 0 or height <= 0:
        return [0.0, 0.0]
    return [max(0.0, min(1.0, (point[0] - x) / width)),
            max(0.0, min(1.0, (point[1] - y) / height))]
