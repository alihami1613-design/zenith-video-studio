"""Bounded, local-only audio diagnostics for completed MP4 exports.

Transient and clipping observations are review cues, not proof of audible defects.
This module does not claim lip-sync detection; it checks audio stream duration only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
import re
import subprocess


@dataclass(frozen=True)
class AudioTransientCandidate:
    time_seconds: float
    peak: float
    sample_jump: float


@dataclass(frozen=True)
class AudioRenderQualityReport:
    scanned: bool
    analyzed_duration_seconds: float
    expected_duration_seconds: float
    duration_difference_seconds: float
    duration_matches_video: bool
    duration_scan_complete: bool
    transient_candidates: tuple[AudioTransientCandidate, ...]
    clipped_intervals_seconds: tuple[tuple[float, float], ...]
    requires_human_review: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def inspect_rendered_audio(
    output_path: str | Path,
    ffmpeg: str,
    *,
    expected_video_duration_seconds: float,
    fps: int,
    sample_rate: int = 16000,
    max_duration_seconds: int = 1800,
    transient_jump_threshold: int = 18000,
    transient_peak_threshold: int = 10000,
    clipping_threshold: int = 32700,
    minimum_candidate_spacing_seconds: float = 0.08,
    timeout_seconds: int = 900,
) -> AudioRenderQualityReport:
    """Decode bounded mono PCM and flag abrupt sample jumps/clipping for review."""
    path = Path(output_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if path.stat().st_size <= 0:
        raise ValueError("فایل خروجی صوتی خالی است.")
    if not math.isfinite(expected_video_duration_seconds) or expected_video_duration_seconds <= 0:
        raise ValueError("مدت مورد انتظار ویدیو معتبر نیست.")
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 240:
        raise ValueError("نرخ فریم برای کنترل صدا معتبر نیست.")
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or not 8000 <= sample_rate <= 48000:
        raise ValueError("نرخ نمونه‌برداری صوت خارج از محدوده مجاز است.")
    if isinstance(max_duration_seconds, bool) or not isinstance(max_duration_seconds, int) or not 1 <= max_duration_seconds <= 1800:
        raise ValueError("سقف مدت تحلیل صوت خارج از محدوده مجاز است.")
    if not 1 <= transient_jump_threshold <= 32767 or not 1 <= transient_peak_threshold <= 32767:
        raise ValueError("آستانه تشخیص گذرای صوتی معتبر نیست.")
    if not 1000 <= clipping_threshold <= 32767:
        raise ValueError("آستانه کلیپ‌شدن صدا معتبر نیست.")
    if not 0.02 <= minimum_candidate_spacing_seconds <= 2.0:
        raise ValueError("فاصله حداقل نامزدهای صوتی معتبر نیست.")
    if not 1 <= timeout_seconds <= 1800:
        raise ValueError("مهلت بررسی صوتی خارج از محدوده مجاز است.")

    command = [
        str(ffmpeg), "-hide_banner", "-nostats", "-v", "error", "-i", str(path),
        "-map", "0:a:0", "-vn", "-sn", "-dn", "-t", str(max_duration_seconds),
        "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "pipe:1",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=False,
            timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("بررسی صوت خروجی بیش از زمان مجاز طول کشید.") from exc
    except OSError as exc:
        raise RuntimeError("اجرای بررسی صوت خروجی ناموفق بود.") from exc
    if result.returncode != 0:
        raise ValueError("جریان صوتی خروجی قابل رمزگشایی نیست.")
    raw = result.stdout or b""
    max_bytes = max_duration_seconds * sample_rate * 2
    if not isinstance(raw, bytes) or len(raw) < sample_rate * 2 or len(raw) > max_bytes:
        raise ValueError("داده صوتی خروجی خالی یا خارج از محدوده امن است.")
    if len(raw) % 2:
        raw = raw[:-1]

    sample_count = len(raw) // 2
    analyzed_duration = sample_count / sample_rate
    expected_samples = round(expected_video_duration_seconds * sample_rate)
    duration_difference = abs(sample_count - expected_samples) / sample_rate
    tolerance = max(0.15, 2.0 / fps)
    duration_matches = duration_difference <= tolerance
    complete = expected_video_duration_seconds <= max_duration_seconds + tolerance
    warnings = [
        "جهش نمونه و قله‌های ناگهانی فقط نامزد شنیداری هستند؛ ممکن است ضربه ساز، حرف یا افکت عمدی باشند.",
        "این بررسی همگام‌سازی لب/گفتار با تصویر را تشخیص نمی‌دهد؛ فقط طول جریان صوتی را با مدت ویدیو مقایسه می‌کند.",
        "هیچ تغییری در فایل صوتی یا ویدیویی اعمال نمی‌شود.",
    ]
    if not complete:
        warnings.append("برای محدودیت منابع فقط بخش ابتدایی صدا تحلیل شد؛ کنترل کامل مدت جریان انجام نشد.")
    if not duration_matches:
        warnings.append("مدت نمونه‌های صوتی با مدت ویدیوی مورد انتظار اختلاف دارد؛ همگام‌سازی را دستی بررسی کنید.")

    candidates: list[AudioTransientCandidate] = []
    clipped: list[tuple[float, float]] = []
    previous = 0
    last_candidate_sample = -round(minimum_candidate_spacing_seconds * sample_rate)
    clip_start: int | None = None
    clip_last: int | None = None
    # Process directly from bytes in small chunks; avoid expanding the full PCM into Python objects.
    import array
    samples = array.array("h")
    samples.frombytes(raw)
    if samples.itemsize != 2:
        raise RuntimeError("اندازه نمونه صوتی پشتیبانی نمی‌شود.")
    if __import__("sys").byteorder != "little":
        samples.byteswap()

    for index, value in enumerate(samples):
        magnitude = abs(value)
        jump = abs(value - previous)
        if (index > 0 and jump >= transient_jump_threshold
                and magnitude >= transient_peak_threshold
                and index - last_candidate_sample >= round(minimum_candidate_spacing_seconds * sample_rate)):
            candidates.append(AudioTransientCandidate(
                round(index / sample_rate, 4),
                round(magnitude / 32768.0, 4),
                round(jump / 32768.0, 4),
            ))
            last_candidate_sample = index

        if magnitude >= clipping_threshold:
            if clip_start is None:
                clip_start = index
            clip_last = index
        elif clip_start is not None:
            if clip_last is not None and clip_last - clip_start >= 2:
                clipped.append((round(clip_start / sample_rate, 4),
                                round((clip_last + 1) / sample_rate, 4)))
            clip_start = clip_last = None
        previous = value

    if clip_start is not None and clip_last is not None and clip_last - clip_start >= 2:
        clipped.append((round(clip_start / sample_rate, 4),
                        round((clip_last + 1) / sample_rate, 4)))

    return AudioRenderQualityReport(
        scanned=True,
        analyzed_duration_seconds=round(analyzed_duration, 4),
        expected_duration_seconds=round(expected_video_duration_seconds, 4),
        duration_difference_seconds=round(duration_difference, 4),
        duration_matches_video=duration_matches,
        duration_scan_complete=complete,
        transient_candidates=tuple(candidates),
        clipped_intervals_seconds=tuple(clipped),
        requires_human_review=bool(candidates or clipped or not duration_matches or not complete),
        warnings=tuple(warnings),
    )
