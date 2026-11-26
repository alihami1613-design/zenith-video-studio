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
    audio_track_settings: dict[str, dict] | None = None,
    audio_ducking: dict | None = None,
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

    settings = audio_track_settings or {}
    solo_tracks = {track for track, value in settings.items() if value.get("solo", False)}
    active_tracks = []
    for track in sorted({clip.track for clip in audio_clips}):
        value = settings.get(track, {})
        if value.get("muted", False):
            continue
        if solo_tracks and track not in solo_tracks:
            continue
        active_tracks.append(track)
    audio_clips = [clip for clip in audio_clips if clip.track in active_tracks]
    if not audio_clips:
        raise ValueError("همه ترک‌های صوتی Mute هستند یا از حالت Solo خارج شده‌اند.")

    command = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error"]
    filters: list[str] = []
    clip_labels: dict[str, list[str]] = {}
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
        clip_labels.setdefault(clip.track, []).append(f"[{label}]")

    if timeline_duration_frames is not None:
        if timeline_duration_frames < 1:
            raise ValueError("Timeline duration must be positive")
        output_duration = _seconds(timeline_duration_frames, fps)
    else:
        output_duration = max(
            _seconds(clip.end_frame, fps) for clip in audio_clips
        )
    track_labels: list[str] = []
    track_label_map: dict[str, str] = {}
    for track_index, track in enumerate(active_tracks):
        labels = clip_labels.get(track, [])
        if not labels:
            continue
        track_settings = settings.get(track, {})
        track_volume = float(track_settings.get("volume", 1.0))
        if not math.isfinite(track_volume) or not 0.0 <= track_volume <= 2.0:
            raise ValueError(f"تنظیم حجم ترک {track} معتبر نیست.")
        track_label = f"track{track_index}"
        if len(labels) == 1:
            filters.append(f"{labels[0]}volume={track_volume:.4f}[{track_label}]")
        else:
            filters.append(
                f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:"
                f"dropout_transition=0:normalize=0,volume={track_volume:.4f}[{track_label}]"
            )
        track_labels.append(f"[{track_label}]")
        track_label_map[track] = track_label

    duck = audio_ducking or {}
    if duck.get("enabled", False):
        voice_track = str(duck.get("voice_track", "A1"))
        music_track = str(duck.get("music_track", "A2"))
        reduction_db = float(duck.get("reduction_db", 12.0))
        attack_ms = int(duck.get("attack_ms", 20))
        release_ms = int(duck.get("release_ms", 500))
        if voice_track == music_track or voice_track not in active_tracks or music_track not in active_tracks:
            raise ValueError("برای Ducking باید ترک گویندگی و موسیقی جداگانه فعال و بدون Mute/Solo محدودکننده باشند.")
        if not math.isfinite(reduction_db) or not 0.0 <= reduction_db <= 24.0:
            raise ValueError("شدت Ducking باید بین صفر تا ۲۴ دسی‌بل باشد.")
        if not 1 <= attack_ms <= 500 or not 20 <= release_ms <= 3000:
            raise ValueError("زمان Attack یا Release برای Ducking معتبر نیست.")
        ratio = max(1.0, 10 ** (reduction_db / 20.0))
        ducked_label = "musicducked"
        filters.append(
            f"[{track_label_map[music_track]}][{track_label_map[voice_track]}]"
            f"sidechaincompress=threshold=0.025:ratio={ratio:.4f}:"
            f"attack={attack_ms}:release={release_ms}[{ducked_label}]"
        )
        track_labels = [
            f"[{ducked_label}]" if track == f"[{track_label_map[music_track]}]" else track
            for track in track_labels
        ]

    mix_inputs = "".join(track_labels)
    filters.append(
        f"{mix_inputs}amix=inputs={len(track_labels)}:duration=longest:"
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
    audio_track_settings: dict[str, dict] | None = None,
    audio_ducking: dict | None = None,
) -> Path:
    """Render a stereo 48 kHz WAV mix with one FFmpeg process."""
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.stem + ".partial" + target.suffix)
    partial.unlink(missing_ok=True)
    command = build_audio_mix_command(
        find_ffmpeg(), clips, fps, partial, timeline_duration_frames,
        audio_track_settings=audio_track_settings,
        audio_ducking=audio_ducking,
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
