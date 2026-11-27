"""Post-render MP4 verification using the same FFmpeg binary as the renderer.

The verifier checks container metadata and fully decodes mapped video/audio streams.
It does not modify the rendered file.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import subprocess
from pathlib import Path

from render_quality import RenderVisualQualityReport, inspect_rendered_video


@dataclass(frozen=True)
class RenderValidationReport:
    valid: bool
    file_size_bytes: int
    duration_seconds: float
    width: int
    height: int
    fps: float
    has_video: bool
    has_audio: bool
    video_codec: str
    decode_succeeded: bool
    visual_quality: RenderVisualQualityReport | None
    visual_scan_error: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def _run(command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command, capture_output=True, text=True,
            timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("بررسی فایل خروجی بیش از زمان مجاز طول کشید.") from exc
    except OSError as exc:
        raise RuntimeError("اجرای ابزار بررسی ویدیو ناموفق بود.") from exc


def validate_rendered_mp4(
    output_path: str | Path,
    ffmpeg: str,
    *,
    expected_width: int,
    expected_height: int,
    expected_fps: int,
    expected_duration_seconds: float,
    expect_audio: bool,
    timeout_seconds: int = 900,
) -> RenderValidationReport:
    """Reject incomplete, mismatched, or undecodable exports before finalization."""
    path = Path(output_path).expanduser().resolve()
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("فایل خروجی وجود ندارد یا خالی است.")
    if min(expected_width, expected_height, expected_fps) < 1 or expected_duration_seconds <= 0:
        raise ValueError("مشخصات مورد انتظار برای کنترل خروجی معتبر نیست.")

    probe = _run(
        [str(ffmpeg), "-hide_banner", "-i", str(path)],
        min(timeout_seconds, 30),
    )
    metadata = probe.stderr or probe.stdout or ""
    duration_match = re.search(
        r"Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", metadata
    )
    video_match = re.search(r"Video:\s*([^,\s]+).*?(\d{2,5})x(\d{2,5})", metadata)
    fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", metadata)
    has_audio = re.search(r"Audio:", metadata) is not None
    if duration_match is None or video_match is None or fps_match is None:
        raise ValueError("ساختار MP4 یا اطلاعات جریان ویدیویی خروجی قابل تشخیص نیست.")

    duration = (
        int(duration_match.group(1)) * 3600
        + int(duration_match.group(2)) * 60
        + float(duration_match.group(3))
    )
    codec = video_match.group(1).lower()
    width, height = int(video_match.group(2)), int(video_match.group(3))
    fps = float(fps_match.group(1))
    tolerance = max(0.15, 2.0 / expected_fps)
    mismatches = []
    if (width, height) != (expected_width, expected_height):
        mismatches.append("ابعاد تصویر خروجی با پروژه مطابقت ندارد.")
    if abs(fps - expected_fps) > 0.05:
        mismatches.append("نرخ فریم خروجی با پروژه مطابقت ندارد.")
    if abs(duration - expected_duration_seconds) > tolerance:
        mismatches.append("مدت فایل خروجی با طول تایم‌لاین مطابقت ندارد.")
    if codec not in {"h264", "avc1"}:
        mismatches.append("کدک ویدیویی خروجی H.264 نیست.")
    if expect_audio and not has_audio:
        mismatches.append("ترک صوتی مورد انتظار در فایل خروجی وجود ندارد.")
    if mismatches:
        raise ValueError(" ".join(mismatches))

    decoded = _run(
        [
            str(ffmpeg), "-hide_banner", "-v", "error", "-i", str(path),
            "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-",
        ],
        timeout_seconds,
    )
    if decoded.returncode != 0:
        detail = (decoded.stderr or decoded.stdout or "").strip()
        raise ValueError(
            "فایل MP4 ساخته شده اما رمزگشایی کامل آن ناموفق بود: "
            + detail[-1200:]
        )

    # Visual findings are review cues only. A diagnostic failure must not
    # discard an otherwise structurally valid, fully decoded export.
    visual_quality = None
    visual_scan_error = None
    try:
        visual_quality = inspect_rendered_video(
            path, ffmpeg, timeout_seconds=timeout_seconds
        )
    except (RuntimeError, ValueError):
        visual_scan_error = "اسکن بصری کامل نشد؛ بازبینی چشمی خروجی لازم است."

    return RenderValidationReport(
        True, path.stat().st_size, duration, width, height, fps,
        True, has_audio, codec, True, visual_quality, visual_scan_error,
    )
