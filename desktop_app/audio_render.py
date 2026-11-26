"""Lightweight, non-destructive audio timeline rendering with FFmpeg."""
from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Iterable

from proxy_manager import find_ffmpeg


def _seconds(frames: int, fps: int) -> float:
    return frames / fps


def build_audio_mix_command(
    ffmpeg: str,
    clips: Iterable[object],
    fps: int,
    output_path: str | Path,
    timeline_duration_frames: int | None = None,
) -> list[str]:
    """Build an audio-only WAV mix from timeline audio clips.

    Each clip is trimmed in source time, gain/fades are applied, then it is
    delayed to its timeline position. The original media is never modified.
    """
    if fps < 1:
        raise ValueError("FPS must be positive")
    audio_clips = sorted(
        (clip for clip in clips if getattr(clip, "media_type", "") == "audio"),
        key=lambda clip: (clip.start_frame, clip.track, clip.clip_id),
    )
    if not audio_clips:
        raise ValueError("هیچ کلیپ صوتی روی تایم‌لاین وجود ندارد.")

    command = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error"]
    filters: list[str] = []
    labels: list[str] = []
    for index, clip in enumerate(audio_clips):
        source = Path(clip.path)
        if not source.is_file():
            raise FileNotFoundError(f"فایل صوتی پیدا نشد: {source}")
        if clip.duration_frames < 1 or clip.start_frame < 0 or clip.source_in < 0:
            raise ValueError(f"زمان‌بندی کلیپ معتبر نیست: {clip.name}")
        if not math.isfinite(float(clip.volume)) or not 0.0 <= clip.volume <= 2.0:
            raise ValueError(f"Gain کلیپ معتبر نیست: {clip.name}")
        if clip.fade_in_frames < 0 or clip.fade_out_frames < 0:
            raise ValueError(f"Fade کلیپ معتبر نیست: {clip.name}")
        if clip.fade_in_frames > clip.duration_frames or clip.fade_out_frames > clip.duration_frames:
            raise ValueError(f"مدت Fade از طول کلیپ بیشتر است: {clip.name}")

        command.extend(["-i", str(source)])
        duration = _seconds(clip.duration_frames, fps)
        source_start = _seconds(clip.source_in, fps)
        chain = [
            f"atrim=start={source_start:.6f}:duration={duration:.6f}",
            "asetpts=PTS-STARTPTS",
            f"volume={clip.volume:.4f}",
        ]
        if clip.fade_in_frames:
            fade_in = _seconds(clip.fade_in_frames, fps)
            chain.append(f"afade=t=in:st=0:d={fade_in:.6f}")
        if clip.fade_out_frames:
            fade_out = _seconds(clip.fade_out_frames, fps)
            fade_start = max(0.0, duration - fade_out)
            chain.append(f"afade=t=out:st={fade_start:.6f}:d={fade_out:.6f}")
        delay_ms = round(_seconds(clip.start_frame, fps) * 1000)
        chain.append(f"adelay={delay_ms}:all=1")
        label = f"a{index}"
        filters.append(f"[{index}:a:0]{','.join(chain)}[{label}]")
        labels.append(f"[{label}]")

    if timeline_duration_frames is not None:
        if timeline_duration_frames < 1:
            raise ValueError("Timeline duration must be positive")
        output_duration = _seconds(timeline_duration_frames, fps)
    else:
        output_duration = max(
            _seconds(clip.end_frame, fps) for clip in audio_clips
        )
    mix_inputs = "".join(labels)
    filters.append(
        f"{mix_inputs}amix=inputs={len(labels)}:duration=longest:"
        "dropout_transition=0:normalize=0,alimiter=limit=0.95,"
        f"apad,atrim=duration={output_duration:.6f}[mixout]"
    )
    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[mixout]",
        "-ar", "48000", "-ac", "2",
        "-c:a", "pcm_s16le",
        "-t", f"{output_duration:.6f}",
        "-rf64", "auto",
        str(Path(output_path)),
    ])
    return command


def render_audio_mix(
    clips: Iterable[object],
    fps: int,
    output_path: str | Path,
    timeline_duration_frames: int | None = None,
    timeout_seconds: int = 7200,
) -> Path:
    """Render a stereo 48 kHz WAV mix with one FFmpeg process."""
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.stem + ".partial" + target.suffix)
    partial.unlink(missing_ok=True)
    command = build_audio_mix_command(
        find_ffmpeg(), clips, fps, partial, timeline_duration_frames
    )
    try:
        subprocess.run(command, capture_output=True, text=True,
                       timeout=timeout_seconds, check=True)
        if not partial.is_file() or partial.stat().st_size <= 44:
            raise RuntimeError("FFmpeg فایل صوتی خروجی معتبر تولید نکرد.")
        partial.replace(target)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ساخت میکس صوتی بیش از زمان مجاز طول کشید.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"ساخت میکس صوتی ناموفق بود: {detail[-1200:]}") from exc
    finally:
        partial.unlink(missing_ok=True)
    return target
