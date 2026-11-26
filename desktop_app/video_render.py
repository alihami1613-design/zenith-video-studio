"""Conservative CPU-friendly H.264 render for the supported single-track timeline."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from audio_render import render_audio_mix
from proxy_manager import find_ffmpeg
from video_color import build_color_filter

RENDER_VERSION = "timeline-h264-v1"


def _seconds(frames: int, fps: int) -> float:
    return frames / fps


def _video_clips(clips: Iterable[object]) -> list[object]:
    return sorted(
        (clip for clip in clips if str(getattr(clip, "track", "")).startswith("V")),
        key=lambda clip: (clip.start_frame, clip.track, clip.clip_id),
    )


def validate_render_project(project: object) -> list[object]:
    fps = int(project.fps)
    width, height = int(project.width), int(project.height)
    if fps not in (25, 30):
        raise ValueError("خروجی فعلاً فقط با نرخ ۲۵ یا ۳۰ فریم بر ثانیه پشتیبانی می‌شود.")
    if width < 2 or height < 2 or width % 2 or height % 2:
        raise ValueError("ابعاد خروجی باید زوج و بزرگ‌تر از صفر باشند.")
    if width > 1920 or height > 1920:
        raise ValueError("برای حفظ کارایی، خروجی این نسخه حداکثر ۱۹۲۰ پیکسل در هر ضلع است.")
    clips = _video_clips(project.clips)
    if not clips:
        raise ValueError("برای خروجی MP4 حداقل یک کلیپ ویدیویی روی V1 لازم است.")
    if any(clip.track != "V1" for clip in clips):
        raise ValueError("این نسخه فعلاً فقط ترک تصویر V1 را رندر می‌کند؛ کلیپ‌های V2 تا V4 را موقتاً خارج کنید.")
    previous_end = 0
    for clip in clips:
        if getattr(clip, "media_type", "video") != "video":
            raise ValueError(f"نوع رسانه در خروجی تصویر پشتیبانی نمی‌شود: {clip.name}")
        if Path(clip.path).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
            raise ValueError("تصویر ثابت هنوز در خروجی MP4 پشتیبانی نمی‌شود؛ فقط فایل ویدیویی وارد V1 کنید.")
        source = Path(clip.path).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f"فایل ویدیویی پیدا نشد: {source}")
        if clip.start_frame < previous_end:
            raise ValueError("هم‌پوشانی کلیپ‌های V1 هنوز در موتور خروجی پشتیبانی نمی‌شود؛ کلیپ‌ها را بدون overlap بچینید.")
        if clip.start_frame < 0 or clip.source_in < 0 or clip.duration_frames < 1:
            raise ValueError(f"زمان‌بندی کلیپ معتبر نیست: {clip.name}")
        previous_end = clip.end_frame
    if int(project.duration_frames) < 1:
        raise ValueError("تایم‌لاین خالی است.")
    return clips


def build_video_render_command(ffmpeg: str, project: object,
                               output_path: str | Path) -> list[str]:
    """Build a single-pass V1 render; gaps become black and color grade is baked in."""
    clips = validate_render_project(project)
    fps, width, height = int(project.fps), int(project.width), int(project.height)
    duration = _seconds(int(project.duration_frames), fps)
    command = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error"]
    for clip in clips:
        command.extend(["-ss", f"{_seconds(clip.source_in, fps):.6f}",
                        "-i", str(Path(clip.path).expanduser().resolve())])

    filters = [
        f"color=c=black:s={width}x{height}:r={fps}:d={duration:.6f},format=yuv420p[base0]"
    ]
    previous = "base0"
    for index, clip in enumerate(clips):
        clip_duration = _seconds(clip.duration_frames, fps)
        start = _seconds(clip.start_frame, fps)
        end = _seconds(clip.end_frame, fps)
        chain = (
            f"[{index}:v:0]trim=duration={clip_duration:.6f},"
            "setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"fps={fps},setsar=1,format=yuv420p"
        )
        grade = build_color_filter(getattr(clip, "color_grade", {}))
        if grade:
            chain += "," + grade
        chain += f"[v{index}]"
        filters.append(chain)
        out_label = f"base{index + 1}"
        filters.append(
            f"[{previous}][v{index}]overlay=0:0:"
            f"enable='gte(t,{start:.6f})*lt(t,{end:.6f})':"
            f"eof_action=pass:repeatlast=0[{out_label}]"
        )
        previous = out_label

    command.extend([
        "-filter_complex_threads", "1",
        "-filter_complex", ";".join(filters),
        "-map", f"[{previous}]",
        "-an", "-t", f"{duration:.6f}",
        "-r", str(fps), "-c:v", "libx264", "-preset", "ultrafast",
        "-crf", "22", "-threads", "2", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-sn", str(Path(output_path)),
    ])
    return command


def _run(command: list[str], timeout_seconds: int, description: str) -> None:
    try:
        subprocess.run(command, capture_output=True, text=True,
                       timeout=timeout_seconds, check=True)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{description}: زمان مجاز رندر تمام شد.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"{description}: {(detail[-1400:] or 'خطای ناشناخته FFmpeg')}") from exc


def render_timeline_mp4(project: object, output_path: str | Path,
                        timeout_seconds: int = 14400) -> Path:
    """Render a V1 picture timeline and optional mixed audio, then atomically publish MP4."""
    clips = validate_render_project(project)
    target = Path(output_path).expanduser().resolve()
    if target.suffix.lower() != ".mp4":
        target = target.with_suffix(".mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg()
    has_audio = any(
        getattr(c, "media_type", "") == "audio"
        or (getattr(c, "media_type", "") == "video" and getattr(c, "has_audio", False))
        for c in project.clips
    )
    with tempfile.TemporaryDirectory(prefix="zenith_render_", dir=str(target.parent)) as work:
        work_dir = Path(work)
        silent_video = work_dir / "picture.mp4"
        video_command = build_video_render_command(ffmpeg, project, silent_video)
        _run(video_command, timeout_seconds, "رندر تصویر ناموفق بود")
        if not silent_video.is_file() or silent_video.stat().st_size <= 0:
            raise RuntimeError("FFmpeg فایل ویدیویی معتبر تولید نکرد.")

        partial = target.with_name(target.stem + ".partial.mp4")
        partial.unlink(missing_ok=True)
        try:
            if has_audio:
                mixed_audio = work_dir / "mix.wav"
                render_audio_mix(
                    project.clips, project.fps, mixed_audio,
                    timeline_duration_frames=project.duration_frames,
                    audio_track_settings=project.audio_track_settings,
                    audio_ducking=project.audio_ducking,
                    timeout_seconds=timeout_seconds,
                )
                mux = [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(silent_video), "-i", str(mixed_audio),
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-t", f"{_seconds(project.duration_frames, project.fps):.6f}",
                    "-movflags", "+faststart", str(partial),
                ]
                _run(mux, timeout_seconds, "ترکیب تصویر و صدا ناموفق بود")
            else:
                os.replace(silent_video, partial)
            if not partial.is_file() or partial.stat().st_size <= 0:
                raise RuntimeError("فایل MP4 خروجی معتبر ساخته نشد.")
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
    return target
