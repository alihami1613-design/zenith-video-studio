"""Lightweight, non-destructive audio timeline rendering with FFmpeg."""
from __future__ import annotations

import math
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Iterable

from proxy_manager import find_ffmpeg
from speed_ramp import build_speed_segments


def _seconds(frames: int, fps: int) -> float:
    return frames / fps


def _atempo_chain(rate: float) -> list[str]:
    """Build FFmpeg atempo stages, each within the supported 0.5x-2x range."""
    stages = []
    remaining = float(rate)
    while remaining < 0.5:
        stages.append("atempo=0.5")
        remaining /= 0.5
    while remaining > 2.0:
        stages.append("atempo=2.0")
        remaining /= 2.0
    if abs(remaining - 1.0) > 1e-9:
        stages.append(f"atempo={remaining:.6f}")
    return stages
def build_audio_mix_command(
    ffmpeg: str,
    clips: Iterable[object],
    fps: int,
    output_path: str | Path,
    timeline_duration_frames: int | None = None,
    audio_track_settings: dict[str, dict] | None = None,
    audio_ducking: dict | None = None,
    progress_path: str | Path | None = None,
) -> list[str]:
    """Build an audio-only WAV mix from timeline audio clips.

    Each clip is trimmed in source time, gain/fades are applied, then it is
    delayed to its timeline position. The original media is never modified.
    """
    if fps < 1:
        raise ValueError("FPS must be positive")
    all_clips = list(clips)
    audio_clips = sorted(
        (clip for clip in all_clips
         if getattr(clip, "media_type", "") == "audio"
         or (getattr(clip, "media_type", "") == "video" and getattr(clip, "has_audio", False))),
        key=lambda clip: (clip.start_frame, getattr(clip, "audio_track", clip.track), clip.clip_id),
    )
    if not audio_clips:
        raise ValueError("هیچ کلیپ صوتی روی تایم‌لاین وجود ندارد.")

    settings = audio_track_settings or {}
    solo_tracks = {track for track, value in settings.items() if value.get("solo", False)}
    active_tracks = []
    for track in sorted({getattr(clip, "audio_track", clip.track) for clip in audio_clips}):
        value = settings.get(track, {})
        if value.get("muted", False):
            continue
        if solo_tracks and track not in solo_tracks:
            continue
        active_tracks.append(track)
    audio_clips = [clip for clip in audio_clips if getattr(clip, "audio_track", clip.track) in active_tracks]
    if not audio_clips:
        raise ValueError("همه ترک‌های صوتی Mute هستند یا از حالت Solo خارج شده‌اند.")

    # A video clip's embedded audio follows the picture transition: its
    # incoming audio starts transition_in_frames early, using the matching
    # pre-roll from source media. The preceding video clip fades out over the
    # same interval. This mirrors video_render's clip_start/source trim logic.
    visual_fade_in: dict[str, int] = {}
    visual_fade_out: dict[str, int] = {}
    video_by_track: dict[str, list[object]] = {}
    for clip in all_clips:
        if getattr(clip, "media_type", "") == "video":
            video_by_track.setdefault(str(clip.track), []).append(clip)
    for track_clips in video_by_track.values():
        ordered = sorted(track_clips, key=lambda item: (item.start_frame, item.clip_id))
        for outgoing, incoming in zip(ordered, ordered[1:]):
            transition = int(getattr(incoming, "transition_in_frames", 0) or 0)
            if transition > 0 and outgoing.end_frame == incoming.start_frame:
                visual_fade_out[outgoing.clip_id] = max(
                    visual_fade_out.get(outgoing.clip_id, 0), transition
                )
                visual_fade_in[incoming.clip_id] = max(
                    visual_fade_in.get(incoming.clip_id, 0), transition
                )

    # Overlapping adjacent clips on the same audio track become an equal-power
    # crossfade. Clips on different tracks remain independently mixed.
    crossfade_in: dict[str, int] = {}
    crossfade_out: dict[str, int] = {}
    effective_start: dict[str, int] = {}
    effective_end: dict[str, int] = {}
    for clip in audio_clips:
        pre_roll = visual_fade_in.get(clip.clip_id, 0)
        effective_start[clip.clip_id] = int(clip.start_frame) - pre_roll
        effective_end[clip.clip_id] = int(clip.end_frame)
    by_track: dict[str, list[object]] = {}
    for clip in audio_clips:
        route = getattr(clip, "audio_track", clip.track)
        by_track.setdefault(route, []).append(clip)
    for track_clips in by_track.values():
        ordered = sorted(track_clips, key=lambda item: (effective_start[item.clip_id], item.clip_id))
        for outgoing, incoming in zip(ordered, ordered[1:]):
            overlap = min(effective_end[outgoing.clip_id], effective_end[incoming.clip_id]) - effective_start[incoming.clip_id]
            if overlap > 0:
                crossfade_out[outgoing.clip_id] = max(crossfade_out.get(outgoing.clip_id, 0), overlap)
                crossfade_in[incoming.clip_id] = max(crossfade_in.get(incoming.clip_id, 0), overlap)

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
        is_embedded_video_audio = getattr(clip, "media_type", "") == "video"
        playback_rate = float(getattr(clip, "playback_rate", 1.0)) if is_embedded_video_audio else 1.0
        transition_pre_roll = visual_fade_in.get(clip.clip_id, 0) if is_embedded_video_audio else 0
        effective_duration_frames = int(clip.duration_frames) + transition_pre_roll
        # Match the video renderer: clamp pre-roll to the beginning of
        # the source when a high playback rate consumes more source frames.
        effective_source_in = max(
            0, int(clip.source_in) - round(transition_pre_roll * playback_rate)
        )
        effective_start_frame = int(clip.start_frame) - transition_pre_roll
        duration = _seconds(effective_duration_frames, fps)
        source_start = _seconds(effective_source_in, fps)
        ramp_points = list(getattr(clip, "speed_ramp", []) or []) if is_embedded_video_audio else []
        speed_segments = build_speed_segments(clip.duration_frames, fps, ramp_points) if ramp_points else []
        if speed_segments:
            if bool(getattr(clip, "reverse_playback", False)):
                raise ValueError(f"Speed Ramp و Reverse هم‌زمان فعلاً برای صدای کلیپ پشتیبانی نمی‌شوند: {clip.name}")
            split_labels = "".join(f"[ar{index}_{part}]" for part in range(len(speed_segments)))
            filters.append(f"[{index}:a:0]asplit={len(speed_segments)}{split_labels}")
            segment_outputs = []
            for part, segment in enumerate(speed_segments):
                label = f"arout{index}_{part}"
                segment_outputs.append(f"[{label}]")
                segment_chain = [
                    f"atrim=start={source_start + float(segment['source_start_frames']) / fps:.6f}:"
                    f"duration={float(segment['source_duration_frames']) / fps:.6f}",
                    "asetpts=PTS-STARTPTS",
                    *_atempo_chain(float(segment["rate"])),
                ]
                filters.append(f"[ar{index}_{part}]{','.join(segment_chain)}[{label}]")
            ramp_label = f"audioramp{index}"
            filters.append(
                f"{''.join(segment_outputs)}concat=n={len(speed_segments)}:v=0:a=1[{ramp_label}]"
            )
            audio_source_label = f"[{ramp_label}]"
            chain = [f"volume={clip.volume:.4f}"]
        else:
            source_duration = duration * playback_rate
            audio_source_label = f"[{index}:a:0]"
            chain = [
                f"atrim=start={source_start:.6f}:duration={source_duration:.6f}",
                "asetpts=PTS-STARTPTS",
                *_atempo_chain(playback_rate),
                *(["areverse"] if bool(getattr(clip, "reverse_playback", False)) and is_embedded_video_audio else []),
                f"volume={clip.volume:.4f}",
            ]
        pan = float(getattr(clip, "audio_pan", 0.0))
        if not math.isfinite(pan) or not -1.0 <= pan <= 1.0:
            raise ValueError(f"Audio pan must be between -1 and 1: {clip.name}")
        if abs(pan) > 1e-9:
            left_gain = 1.0 if pan <= 0.0 else 1.0 - pan
            right_gain = 1.0 if pan >= 0.0 else 1.0 + pan
            chain.append(f"pan=stereo|c0={left_gain:.6f}*c0|c1={right_gain:.6f}*c1")
        automatic_fade_in = max(
            crossfade_in.get(clip.clip_id, 0),
            visual_fade_in.get(clip.clip_id, 0),
        )
        automatic_fade_out = max(
            crossfade_out.get(clip.clip_id, 0),
            visual_fade_out.get(clip.clip_id, 0),
        )
        fade_in_frames = max(int(clip.fade_in_frames), automatic_fade_in)
        fade_out_frames = max(int(clip.fade_out_frames), automatic_fade_out)
        if fade_in_frames:
            fade_in = _seconds(fade_in_frames, fps)
            curve_map = {"linear": "lnr", "qsin": "qsin", "hsin": "hsin", "exp": "exp"}
            selected_curve = str(getattr(clip, "audio_fade_curve", "qsin"))
            if selected_curve not in curve_map:
                raise ValueError(f"Unsupported audio fade curve: {selected_curve}")
            manual_curve = curve_map[selected_curve]
            curve = ":curve=qsin" if automatic_fade_in else ":curve=" + manual_curve
            chain.append(f"afade=t=in:st=0:d={fade_in:.6f}{curve}")
        if fade_out_frames:
            fade_out = _seconds(fade_out_frames, fps)
            fade_start = max(0.0, duration - fade_out)
            curve_map = {"linear": "lnr", "qsin": "qsin", "hsin": "hsin", "exp": "exp"}
            selected_curve = str(getattr(clip, "audio_fade_curve", "qsin"))
            if selected_curve not in curve_map:
                raise ValueError(f"Unsupported audio fade curve: {selected_curve}")
            manual_curve = curve_map[selected_curve]
            curve = ":curve=iqsin" if automatic_fade_out else ":curve=" + manual_curve
            chain.append(f"afade=t=out:st={fade_start:.6f}:d={fade_out:.6f}{curve}")
        delay_ms = round(_seconds(effective_start_frame, fps) * 1000)
        chain.append(f"adelay={delay_ms}:all=1")
        label = f"a{index}"
        filters.append(f"{audio_source_label}{','.join(chain)}[{label}]")
        route = getattr(clip, "audio_track", clip.track)
        if route not in {"A1", "A2", "A3", "A4"}:
            raise ValueError(f"مسیر صدای کلیپ معتبر نیست: {clip.name}")
        clip_labels.setdefault(route, []).append(f"[{label}]")

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
        threshold_db = float(duck.get("threshold_db", -32.0))
        if voice_track == music_track or voice_track not in active_tracks or music_track not in active_tracks:
            raise ValueError("برای Ducking باید ترک گویندگی و موسیقی جداگانه فعال و بدون Mute/Solo محدودکننده باشند.")
        if not math.isfinite(reduction_db) or not 0.0 <= reduction_db <= 24.0:
            raise ValueError("شدت Ducking باید بین صفر تا ۲۴ دسی‌بل باشد.")
        if not 1 <= attack_ms <= 500 or not 20 <= release_ms <= 3000:
            raise ValueError("زمان Attack یا Release برای Ducking معتبر نیست.")
        if not math.isfinite(threshold_db) or not -60.0 <= threshold_db <= -6.0:
            raise ValueError("آستانه Ducking باید بین منفی ۶۰ تا منفی ۶ دسی‌بل باشد.")
        threshold_linear = 10 ** (threshold_db / 20.0)
        ratio = max(1.0, 10 ** (reduction_db / 20.0))
        # Pad the sidechain control signal with silence to the timeline end so
        # compressor release is not cut off when the voice track reaches EOF.
        sidechain_label = "duckcontrol"
        filters.append(f"[{track_label_map[voice_track]}]apad[{sidechain_label}]")
        ducked_label = "musicducked"
        filters.append(
            f"[{track_label_map[music_track]}][{sidechain_label}]"
            f"sidechaincompress=threshold={threshold_linear:.6f}:ratio={ratio:.4f}:"
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
    ])
    if progress_path is not None:
        command.extend(["-progress", str(progress_path), "-nostats"])
    command.append(str(Path(output_path)))
    return command


def render_audio_mix(
    clips: Iterable[object],
    fps: int,
    output_path: str | Path,
    timeline_duration_frames: int | None = None,
    timeout_seconds: int = 7200,
    audio_track_settings: dict[str, dict] | None = None,
    audio_ducking: dict | None = None,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> Path:
    """Render a stereo 48 kHz WAV mix with one FFmpeg process."""
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.stem + ".partial" + target.suffix)
    partial.unlink(missing_ok=True)
    progress_path = target.with_name(target.stem + ".audio-progress.txt")
    progress_path.unlink(missing_ok=True)
    duration = (timeline_duration_frames / fps) if timeline_duration_frames else max(
        (_seconds(clip.end_frame, fps) for clip in clips), default=0.0
    )
    command = build_audio_mix_command(
        find_ffmpeg(), clips, fps, partial, timeline_duration_frames,
        audio_track_settings=audio_track_settings,
        audio_ducking=audio_ducking,
        progress_path=progress_path,
    )
    started = time.monotonic()
    try:
        with tempfile.TemporaryFile(mode="w+b") as stderr_file:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=stderr_file)
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise RuntimeError("ساخت میکس صوتی به درخواست کاربر لغو شد.")
                if time.monotonic() - started > timeout_seconds:
                    process.kill()
                    process.wait()
                    raise RuntimeError("ساخت میکس صوتی بیش از زمان مجاز طول کشید.")
                if progress_callback is not None and duration > 0 and progress_path.is_file():
                    try:
                        progress_values = {}
                        for line in progress_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-30:]:
                            if "=" in line:
                                key, value = line.split("=", 1)
                                progress_values[key] = value
                        raw_time = progress_values.get("out_time", "00:00:00")
                        hours, minutes, seconds = raw_time.split(":")
                        elapsed = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                        progress_callback(min(1.0, max(0.0, elapsed / duration)))
                    except (OSError, ValueError):
                        pass
                time.sleep(0.2)
            if process.returncode:
                stderr_file.seek(0, os.SEEK_END)
                size = stderr_file.tell()
                stderr_file.seek(max(0, size - 5000))
                detail = stderr_file.read().decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"ساخت میکس صوتی ناموفق بود: {detail[-1200:]}")
        if not partial.is_file() or partial.stat().st_size <= 44:
            raise RuntimeError("FFmpeg فایل صوتی خروجی معتبر تولید نکرد.")
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("ساخت میکس صوتی به درخواست کاربر لغو شد.")
        partial.replace(target)
        if progress_callback is not None:
            progress_callback(1.0)
    finally:
        partial.unlink(missing_ok=True)
        progress_path.unlink(missing_ok=True)
    return target
