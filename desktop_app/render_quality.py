"""Bounded, local-only visual diagnostics for rendered video files.

Black and freeze intervals are evidence for human review, not automatic failures:
intentional fades, title cards, still shots, and locked-off shots can be valid.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import subprocess
from pathlib import Path


@dataclass(frozen=True)
class VisualInterval:
    start_seconds: float
    end_seconds: float | None
    duration_seconds: float | None


@dataclass(frozen=True)
class RenderVisualQualityReport:
    black_intervals: tuple[VisualInterval, ...]
    freeze_intervals: tuple[VisualInterval, ...]
    scanned: bool
    requires_human_review: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _intervals(log: str, prefix: str) -> tuple[VisualInterval, ...]:
    """Parse FFmpeg blackdetect/freezedetect metadata without retaining raw logs."""
    if prefix == "black":
        pattern = re.compile(
            r"black_start:\s*(-?\d+(?:\.\d+)?)\s+"
            r"black_end:\s*(-?\d+(?:\.\d+)?)\s+"
            r"black_duration:\s*(\d+(?:\.\d+)?)"
        )
        return tuple(
            VisualInterval(float(a), float(b), float(c))
            for a, b, c in pattern.findall(log)
        )

    starts = list(re.finditer(r"freeze_start:\s*(-?\d+(?:\.\d+)?)", log))
    results: list[VisualInterval] = []
    for index, match in enumerate(starts):
        start = float(match.group(1))
        tail_end = starts[index + 1].start() if index + 1 < len(starts) else len(log)
        tail = log[match.end():tail_end]
        duration_match = re.search(r"freeze_duration:\s*(\d+(?:\.\d+)?)", tail)
        end_match = re.search(r"freeze_end:\s*(-?\d+(?:\.\d+)?)", tail)
        duration = float(duration_match.group(1)) if duration_match else None
        end = float(end_match.group(1)) if end_match else (
            start + duration if duration is not None else None
        )
        results.append(VisualInterval(start, end, duration))
    return tuple(results)


def inspect_rendered_video(
    output_path: str | Path,
    ffmpeg: str,
    *,
    black_min_duration: float = 1.0,
    freeze_min_duration: float = 2.0,
    black_pixel_threshold: float = 0.02,
    freeze_noise_threshold_db: float = -50.0,
    timeout_seconds: int = 900,
) -> RenderVisualQualityReport:
    """Scan a finished video once for sustained black/frozen intervals.

    Findings never invalidate or alter a render; they are review cues only.
    The subprocess is bounded by timeout_seconds and reads no external media.
    """
    path = Path(output_path).expanduser().resolve()
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("فایل خروجی برای بررسی بصری وجود ندارد یا خالی است.")
    if not (0.1 <= black_min_duration <= 30.0):
        raise ValueError("آستانه مدت فریم سیاه خارج از محدوده مجاز است.")
    if not (0.1 <= freeze_min_duration <= 60.0):
        raise ValueError("آستانه مدت فریز خارج از محدوده مجاز است.")
    if not (0.0 <= black_pixel_threshold <= 1.0):
        raise ValueError("آستانه تشخیص سیاهی معتبر نیست.")
    if not (-100.0 <= freeze_noise_threshold_db <= 0.0):
        raise ValueError("آستانه تشخیص فریز معتبر نیست.")
    if not (1 <= timeout_seconds <= 1800):
        raise ValueError("مهلت بررسی بصری خارج از محدوده مجاز است.")

    filters = (
        f"blackdetect=d={black_min_duration:.3f}:pix_th={black_pixel_threshold:.4f},"
        f"freezedetect=n={freeze_noise_threshold_db:.2f}dB:d={freeze_min_duration:.3f}"
    )
    try:
        result = subprocess.run(
            [
                str(ffmpeg), "-hide_banner", "-nostats", "-i", str(path),
                "-vf", filters, "-an", "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("اسکن بصری خروجی بیش از زمان مجاز طول کشید.") from exc
    except OSError as exc:
        raise RuntimeError("اجرای اسکن بصری خروجی ناموفق بود.") from exc

    # FFmpeg returns non-zero for some valid inputs only when decoding fails.
    if result.returncode != 0:
        raise ValueError("اسکن بصری نتوانست جریان ویدیویی خروجی را کامل بخواند.")
    log = result.stderr or ""
    black = _intervals(log, "black")
    frozen = _intervals(log, "freeze")
    return RenderVisualQualityReport(
        black_intervals=black,
        freeze_intervals=frozen,
        scanned=True,
        requires_human_review=bool(black or frozen),
    )
