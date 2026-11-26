"""CPU-conscious multi-layer H.264 timeline renderer."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from audio_render import render_audio_mix
from proxy_manager import find_ffmpeg
from video_color import build_color_filter

RENDER_VERSION = "timeline-h264-v5-wipe-push"
STILL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


def _seconds(frames: int, fps: int) -> float:
    return frames / fps


def _video_clips(clips: Iterable[object]) -> list[object]:
    return sorted(
        (clip for clip in clips if str(getattr(clip, "track", "")).startswith("V")),
        key=lambda clip: (clip.track, clip.start_frame, clip.clip_id),
    )


def _is_still(clip: object) -> bool:
    return Path(clip.path).suffix.lower() in STILL_EXTENSIONS


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
        raise ValueError("برای خروجی MP4 حداقل یک کلیپ تصویری روی V1 تا V4 لازم است.")
    previous_end: dict[str, int] = {}
    previous_clip: dict[str, object] = {}
    for clip in clips:
        if clip.track not in {"V1", "V2", "V3", "V4"}:
            raise ValueError(f"ترک تصویری پشتیبانی‌نشده: {clip.track}")
        if getattr(clip, "media_type", "video") != "video":
            raise ValueError(f"نوع رسانه در خروجی تصویر پشتیبانی نمی‌شود: {clip.name}")
        source = Path(clip.path).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f"فایل رسانه پیدا نشد: {source}")
        if clip.start_frame < 0 or clip.source_in < 0 or clip.duration_frames < 1:
            raise ValueError(f"زمان‌بندی کلیپ معتبر نیست: {clip.name}")
        visual_fades = (int(getattr(clip, "video_fade_in_frames", 0)), int(getattr(clip, "video_fade_out_frames", 0)))
        if min(visual_fades) < 0 or max(visual_fades) > clip.duration_frames:
            raise ValueError(f"مدت Fade تصویری نامعتبر است: {clip.name}")
        transition = int(getattr(clip, "transition_in_frames", 0))
        if transition:
            previous = previous_clip.get(clip.track)
            if previous is None or previous.end_frame != clip.start_frame:
                raise ValueError(f"Cross Dissolve کلیپ {clip.name} به کلیپ قبلی چسبیده در همان ترک نیاز دارد.")
            if transition > previous.duration_frames or transition > clip.duration_frames:
                raise ValueError("مدت Cross Dissolve از طول کلیپ ورودی یا خروجی بیشتر است.")
            if int(getattr(clip, "video_fade_in_frames", 0)):
                raise ValueError("برای یک کلیپ، Cross Dissolve و Video Fade In را هم‌زمان تنظیم نکنید.")
            if not _is_still(clip) and clip.source_in < transition:
                raise ValueError("برای Cross Dissolve به فریم‌های اضافه پیش از نقطه ورود منبع نیاز است؛ نقطه ورود را جلوتر ببرید.")
        if clip.start_frame < previous_end.get(clip.track, 0):
            raise ValueError(
                f"هم‌پوشانی واقعی دو کلیپ روی {clip.track} مجاز نیست؛ "
                "Cross Dissolve از تنظیم جداگانه استفاده می‌کند."
            )
        if _is_still(clip) and clip.source_in:
            raise ValueError("برای عکس ثابت، زمان ورود منبع باید صفر باشد.")
        previous_end[clip.track] = clip.end_frame
        previous_clip[clip.track] = clip
    for track in {"V1", "V2", "V3", "V4"}:
        track_clips = [clip for clip in clips if clip.track == track]
        for left, right in zip(track_clips, track_clips[1:]):
            if int(getattr(left, "transition_in_frames", 0)) + int(getattr(right, "transition_in_frames", 0)) > left.duration_frames:
                raise ValueError("دو Cross Dissolve مجاور بیش از زمان قابل استفاده کلیپ میانی هم‌پوشانی دارند.")
    if int(project.duration_frames) < 1:
        raise ValueError("تایم‌لاین خالی است.")
    if any(c.end_frame > int(project.duration_frames) for c in clips):
        raise ValueError("پایان کلیپ از طول تایم‌لاین پروژه بیشتر است.")
    return clips


def build_video_render_command(ffmpeg: str, project: object,
                               output_path: str | Path) -> list[str]:
    """Composite V1-V4 bottom-to-top; still images loop for their clip duration."""
    clips = validate_render_project(project)
    fps, width, height = int(project.fps), int(project.width), int(project.height)
    duration = _seconds(int(project.duration_frames), fps)
    command = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error"]
    for clip in clips:
        transition = int(getattr(clip, "transition_in_frames", 0))
        clip_duration = _seconds(clip.duration_frames + transition, fps)
        if _is_still(clip):
            command.extend([
                "-loop", "1", "-framerate", str(fps),
                "-t", f"{clip_duration:.6f}",
                "-i", str(Path(clip.path).expanduser().resolve()),
            ])
        else:
            command.extend([
                "-ss", f"{_seconds(max(0, clip.source_in - transition), fps):.6f}",
                "-i", str(Path(clip.path).expanduser().resolve()),
            ])

    filters = [
        f"color=c=black:s={width}x{height}:r={fps}:d={duration:.6f},"
        "format=rgba[base0]"
    ]
    previous = "base0"
    for index, clip in enumerate(clips):
        transition = int(getattr(clip, "transition_in_frames", 0))
        clip_duration = _seconds(clip.duration_frames + transition, fps)
        start = _seconds(clip.start_frame - transition, fps)
        chain = (
            f"[{index}:v:0]trim=duration={clip_duration:.6f},"
            "setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"format=rgba,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:"
            "color=black@0"
        )
        fade_in = int(getattr(clip, "video_fade_in_frames", 0))
        fade_out = int(getattr(clip, "video_fade_out_frames", 0))
        transition_type = str(getattr(clip, "transition_in_type", "dissolve"))
        if transition and transition_type == "dissolve":
            chain += f",fade=t=in:st=0:d={_seconds(transition, fps):.6f}:alpha=1"
        elif transition and transition_type == "wipe_left":
            transition_seconds = _seconds(transition, fps)
            chain += (
                ",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                f"a='if(lte(X,W*min(max(T/{transition_seconds:.6f}\\,0)\\,1))\\,255\\,0)'"
            )
        elif fade_in:
            chain += f",fade=t=in:st=0:d={_seconds(fade_in, fps):.6f}:alpha=1"
        if fade_out:
            fade_start = clip_duration - _seconds(fade_out, fps)
            chain += f",fade=t=out:st={fade_start:.6f}:d={_seconds(fade_out, fps):.6f}:alpha=1"
        chain += f",setpts=PTS+{start:.6f}/TB"
        grade = build_color_filter(getattr(clip, "color_grade", {}))
        if grade:
            chain += "," + grade
        chain += f"[v{index}]"
        filters.append(chain)
        out_label = f"base{index + 1}"
        if transition and transition_type == "push_left":
            transition_seconds = _seconds(transition, fps)
            overlay_x = (
                f"x='-W+W*min(max((t-{start:.6f})/{transition_seconds:.6f}\\,0)\\,1)'"
            )
            overlay_filter = (
                f"[{previous}][v{index}]overlay={overlay_x}:y=0:"
                "eof_action=pass:repeatlast=0:shortest=0:format=auto"
            )
        else:
            overlay_filter = (
                f"[{previous}][v{index}]overlay=0:0:"
                "eof_action=pass:repeatlast=0:shortest=0:format=auto"
            )
        filters.append(f"{overlay_filter}[{out_label}]")
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
    """Render multi-layer picture timeline and optional mixed audio atomically."""
    validate_render_project(project)
    target = Path(output_path).expanduser().resolve()
    if target.suffix.lower() != ".mp4":
        target = target.with_suffix(".mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg()
    has_audio = any(
        getattr(c, "media_type", "") == "audio"
        or (getattr(c, "media_type", "") == "video"
            and getattr(c, "has_audio", False)
            and not _is_still(c))
        for c in project.clips
    )
    with tempfile.TemporaryDirectory(prefix="zenith_render_", dir=str(target.parent)) as work:
        work_dir = Path(work)
        silent_video = work_dir / "picture.mp4"
        _run(build_video_render_command(ffmpeg, project, silent_video),
             timeout_seconds, "رندر تصویر ناموفق بود")
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
