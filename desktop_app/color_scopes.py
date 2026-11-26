"""Low-cost RGB histogram sampling and Qt display for the Color panel."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from proxy_manager import find_ffmpeg


SCOPE_WIDTH = 256
SCOPE_HEIGHT = 144


def build_histogram_command(ffmpeg: str, source: str | Path, timestamp: float) -> list[str]:
    if timestamp < 0:
        raise ValueError("Histogram timestamp cannot be negative")
    return [
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-threads", "1",
        "-ss", f"{timestamp:.6f}", "-i", str(Path(source)),
        "-frames:v", "1", "-an",
        "-vf", "scale=256:144:force_original_aspect_ratio=decrease,"
               "pad=256:144:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
    ]


def calculate_rgb_histogram(rgb24: bytes) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    expected = SCOPE_WIDTH * SCOPE_HEIGHT * 3
    if len(rgb24) != expected:
        raise ValueError(f"Expected {expected} RGB bytes, received {len(rgb24)}")
    channels = [[0] * 256 for _ in range(3)]
    for offset in range(0, expected, 3):
        channels[0][rgb24[offset]] += 1
        channels[1][rgb24[offset + 1]] += 1
        channels[2][rgb24[offset + 2]] += 1
    return tuple(tuple(channel) for channel in channels)  # type: ignore[return-value]


def extract_rgb_histogram(source: str | Path, timestamp: float = 0.0,
                          timeout_seconds: int = 30) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    command = build_histogram_command(find_ffmpeg(), path, timestamp)
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout_seconds, check=True)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("RGB histogram sampling timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"RGB histogram sampling failed: {detail[-800:]}") from exc
    return calculate_rgb_histogram(result.stdout)


class RGBHistogramWidget(QWidget):
    """Compact RGB histogram; receives already-computed data from a worker."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._histogram: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]] | None = None
        self.setMinimumHeight(132)
        self.setMaximumHeight(160)
        self.setToolTip("هیستوگرام RGB از یک فریم نمونه‌برداری‌شده؛ مقیاس نمایش نرمال شده است")

    def set_histogram(self, histogram: Sequence[Sequence[int]] | None) -> None:
        if histogram is None:
            self._histogram = None
        else:
            if len(histogram) != 3 or any(len(channel) != 256 for channel in histogram):
                raise ValueError("RGB histogram must contain three 256-bin channels")
            self._histogram = tuple(tuple(int(value) for value in channel) for channel in histogram)  # type: ignore[assignment]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#101114"))
        area = self.rect().adjusted(8, 8, -8, -20)
        painter.setPen(QPen(QColor("#34363b"), 1))
        for fraction in (0.25, 0.5, 0.75):
            y = area.bottom() - round(area.height() * fraction)
            painter.drawLine(area.left(), y, area.right(), y)
        if self._histogram is None:
            painter.setPen(QColor("#9a9ca3"))
            painter.drawText(area, Qt.AlignCenter, "برای تحلیل، دکمه «تحلیل هیستوگرام RGB» را بزنید")
            return
        maximum = max((max(channel) for channel in self._histogram), default=0) or 1
        colors = (QColor(235, 85, 85, 190), QColor(90, 205, 125, 190), QColor(90, 145, 245, 190))
        for channel, color in zip(self._histogram, colors):
            path = QPainterPath()
            for index, value in enumerate(channel):
                x = area.left() + (index / 255) * area.width()
                y = area.bottom() - (value / maximum) * area.height()
                if index == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            painter.setPen(QPen(color, 1.25))
            painter.drawPath(path)
        painter.setPen(QColor("#9a9ca3"))
        painter.drawText(8, self.height() - 4, "0")
        painter.drawText(self.width() - 20, self.height() - 4, "255")
