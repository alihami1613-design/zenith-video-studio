"""Frame-accurate, UI-independent timeline model for ZENITH Desktop.

The model intentionally stores time as integer frames. It has no Qt dependency,
so timeline editing logic can be tested without opening the GUI.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

PROJECT_SCHEMA_VERSION = 22
DEFAULT_FPS = 30
DEFAULT_VIDEO_TRACKS = ("V1", "V2", "V3", "V4")
DEFAULT_AUDIO_TRACKS = ("A1", "A2", "A3", "A4")


def _new_id() -> str:
    return uuid4().hex[:12]


def transform_eased_progress(keyframe: dict[str, float], progress: float) -> float:
    """Match the easing curve used by the FFmpeg transform renderer."""
    p = max(0.0, min(1.0, float(progress)))
    easing = str(keyframe.get("ease", "linear"))
    if easing == "ease_in":
        return p * p
    if easing == "ease_out":
        return 1.0 - (1.0 - p) * (1.0 - p)
    if easing == "ease_in_out":
        return p * p * (3.0 - 2.0 * p)
    if easing == "bezier":
        y1 = max(0.0, min(1.0, float(keyframe.get("bezier_y1", 0.0))))
        y2 = max(0.0, min(1.0, float(keyframe.get("bezier_y2", 1.0))))
        inverse = 1.0 - p
        return 3.0 * inverse * inverse * p * y1 + 3.0 * inverse * p * p * y2 + p * p * p
    return p


def _transform_value_at(keyframes: list[dict[str, float]], frame: int) -> dict[str, float]:
    """Evaluate the eased transform curve at a clip-local frame."""
    defaults = {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}
    if not keyframes:
        return defaults
    if frame <= int(keyframes[0]["frame"]):
        return {key: float(keyframes[0].get(key, value)) for key, value in defaults.items()}
    if frame >= int(keyframes[-1]["frame"]):
        return {key: float(keyframes[-1].get(key, value)) for key, value in defaults.items()}
    for left, right in zip(keyframes, keyframes[1:]):
        lf, rf = int(left["frame"]), int(right["frame"])
        if lf <= frame <= rf:
            ratio = transform_eased_progress(left, (frame - lf) / (rf - lf))
            return {key: float(left.get(key, default)) + (float(right.get(key, default)) - float(left.get(key, default))) * ratio for key, default in defaults.items()}
    return defaults



def _speed_rate_at(points: list[dict[str, float]], frame: int) -> float:
    """Evaluate a linear speed curve at a clip-local frame."""
    if not points:
        return 1.0
    if frame <= int(points[0]["frame"]):
        return float(points[0]["rate"])
    if frame >= int(points[-1]["frame"]):
        return float(points[-1]["rate"])
    for left, right in zip(points, points[1:]):
        lf, rf = int(left["frame"]), int(right["frame"])
        if lf <= frame <= rf:
            ratio = (frame - lf) / (rf - lf)
            return float(left["rate"]) + (float(right["rate"]) - float(left["rate"])) * ratio
    return 1.0


@dataclass
class Clip:
    """A timeline clip; all positions and lengths are integer frames."""

    path: str
    name: str
    track: str = "V1"
    start_frame: int = 0
    source_in: int = 0
    duration_frames: int = 150
    clip_id: str = field(default_factory=_new_id)
    media_type: str = "video"
    has_audio: bool = False
    audio_track: str = "A1"
    volume: float = 1.0
    fade_in_frames: int = 0
    fade_out_frames: int = 0
    video_fade_in_frames: int = 0
    video_fade_out_frames: int = 0
    transition_in_frames: int = 0
    transition_in_type: str = "dissolve"
    blend_mode: str = "normal"
    chroma_key_enabled: bool = False
    chroma_key_color: str = "#00FF00"
    chroma_key_similarity: float = 0.25
    chroma_key_blend: float = 0.08
    mask_enabled: bool = False
    mask_x: float = 0.0
    mask_y: float = 0.0
    mask_width: float = 1.0
    mask_height: float = 1.0
    mask_shape: str = "rectangle"
    mask_feather_px: float = 0.0
    mask_points: list[list[float]] = field(default_factory=lambda: [[0.5, 0.1], [0.9, 0.9], [0.1, 0.9]])
    mask_keyframes: list[dict[str, float]] = field(default_factory=list)
    transform_keyframes: list[dict[str, float]] = field(default_factory=list)
    anchor_x: float = 0.5
    anchor_y: float = 0.5
    playback_rate: float = 1.0
    speed_ramp: list[dict[str, float]] = field(default_factory=list)
    motion_blur: bool = False
    reverse_playback: bool = False
    color_grade: dict[str, float] = field(default_factory=lambda: {
        "exposure": 0.0, "contrast": 1.0, "saturation": 1.0,
        "temperature": 0.0, "tint": 0.0,
        "highlights": 0.0, "shadows": 0.0, "whites": 0.0, "blacks": 0.0,
        "wheel_shadows_r": 0.0, "wheel_shadows_g": 0.0, "wheel_shadows_b": 0.0,
        "wheel_midtones_r": 0.0, "wheel_midtones_g": 0.0, "wheel_midtones_b": 0.0,
        "wheel_highlights_r": 0.0, "wheel_highlights_g": 0.0, "wheel_highlights_b": 0.0,
    })

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.duration_frames

    def validate(self) -> None:
        if self.start_frame < 0 or self.source_in < 0:
            raise ValueError("Clip positions cannot be negative")
        if self.duration_frames < 1:
            raise ValueError("Clip duration must be at least one frame")
        if not self.track:
            raise ValueError("Clip track cannot be empty")
        if self.audio_track not in DEFAULT_AUDIO_TRACKS:
            raise ValueError("Clip audio route must be A1-A4")
        if not math.isfinite(float(self.volume)) or not 0.0 <= float(self.volume) <= 2.0:
            raise ValueError("Clip volume must be between 0.0 and 2.0")
        if min(self.fade_in_frames, self.fade_out_frames, self.video_fade_in_frames, self.video_fade_out_frames, self.transition_in_frames) < 0:
            raise ValueError("Fade durations cannot be negative")
        rate = float(self.playback_rate)
        if not math.isfinite(rate) or not 0.25 <= rate <= 4.0:
            raise ValueError('Playback rate must be between 0.25x and 4.0x')
        self.playback_rate = rate
        normalized_ramp = []
        previous_ramp_frame = -1
        for raw_point in self.speed_ramp or []:
            frame = int(raw_point.get("frame", 0))
            ramp_rate = float(raw_point.get("rate", 1.0))
            if frame < 0 or frame >= self.duration_frames or frame <= previous_ramp_frame:
                raise ValueError("Speed-ramp keyframes must be ordered inside clip duration")
            if not math.isfinite(ramp_rate) or not 0.25 <= ramp_rate <= 4.0:
                raise ValueError("Speed-ramp rate must be between 0.25x and 4.0x")
            normalized_ramp.append({"frame": frame, "rate": ramp_rate})
            previous_ramp_frame = frame
        self.speed_ramp = normalized_ramp
        for axis in ('anchor_x', 'anchor_y'):
            value = float(getattr(self, axis))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError('Transform anchor must be between 0 and 1')
            setattr(self, axis, value)
        normalized_keys = []
        previous_frame = -1
        for raw_key in self.transform_keyframes or []:
            frame = int(raw_key.get("frame", 0))
            values = {key: float(raw_key.get(key, default)) for key, default in
                      (("x", 0.0), ("y", 0.0), ("scale", 1.0), ("rotation", 0.0), ("opacity", 1.0))}
            if frame < 0 or frame >= self.duration_frames or frame <= previous_frame:
                raise ValueError("Transform keyframes must be ordered inside clip duration")
            if not all(math.isfinite(value) for value in values.values()):
                raise ValueError("Transform keyframe values must be finite")
            if not -2.0 <= values["x"] <= 2.0 or not -2.0 <= values["y"] <= 2.0:
                raise ValueError("Transform position must be between -2 and 2 frame sizes")
            if not 0.1 <= values["scale"] <= 4.0 or not -3600.0 <= values["rotation"] <= 3600.0:
                raise ValueError("Transform scale or rotation is outside supported limits")
            if not 0.0 <= values["opacity"] <= 1.0:
                raise ValueError("Transform opacity must be between 0 and 1")
            easing = str(raw_key.get("ease", "linear"))
            if easing not in {"linear", "ease_in", "ease_out", "ease_in_out", "bezier"}:
                raise ValueError("Unsupported keyframe easing")
            bezier_y1 = float(raw_key.get("bezier_y1", 0.0))
            bezier_y2 = float(raw_key.get("bezier_y2", 1.0))
            if not math.isfinite(bezier_y1) or not math.isfinite(bezier_y2) or not 0.0 <= bezier_y1 <= 1.0 or not 0.0 <= bezier_y2 <= 1.0:
                raise ValueError("Bezier handles must be between 0 and 1")
            normalized_keys.append({"frame": frame, **values, "ease": easing,
                                    "bezier_y1": bezier_y1, "bezier_y2": bezier_y2})
            previous_frame = frame
        self.transform_keyframes = normalized_keys
        if self.transition_in_type not in {"dissolve", "wipe_left", "push_left"}:
            raise ValueError("Unsupported video transition type")
        if self.blend_mode not in {"normal", "multiply", "screen", "addition", "overlay"}:
            raise ValueError("Unsupported video blend mode")
        key_color = str(self.chroma_key_color).strip().upper()
        if len(key_color) != 7 or not key_color.startswith("#") or any(
            char not in "0123456789ABCDEF" for char in key_color[1:]
        ):
            raise ValueError("Chroma key color must be a #RRGGBB hex value")
        self.chroma_key_color = key_color
        for name in ("chroma_key_similarity", "chroma_key_blend"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
            setattr(self, name, value)
        for name in ("mask_x", "mask_y", "mask_width", "mask_height"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
            setattr(self, name, value)
        if self.mask_x + self.mask_width > 1.0 + 1e-9 or self.mask_y + self.mask_height > 1.0 + 1e-9:
            raise ValueError("Mask rectangle must remain inside the frame")
        if self.mask_width <= 0.0 or self.mask_height <= 0.0:
            raise ValueError("Mask width and height must be greater than zero")
        if self.mask_shape not in {"rectangle", "ellipse", "polygon"}:
            raise ValueError("Unsupported mask shape")
        feather = float(self.mask_feather_px)
        if not math.isfinite(feather) or not 0.0 <= feather <= 40.0:
            raise ValueError("Mask feather must be between 0 and 40 pixels")
        self.mask_feather_px = feather
        normalized_points = []
        for point in self.mask_points or []:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError("Each polygon point must contain X and Y")
            px, py = float(point[0]), float(point[1])
            if not math.isfinite(px) or not math.isfinite(py) or not 0.0 <= px <= 1.0 or not 0.0 <= py <= 1.0:
                raise ValueError("Polygon points must be normalized between 0 and 1")
            normalized_points.append([px, py])
        if self.mask_shape == "polygon" and not 3 <= len(normalized_points) <= 8:
            raise ValueError("Polygon masks require 3 to 8 points")
        self.mask_points = normalized_points
        normalized_mask_keys = []
        previous_mask_frame = -1
        for raw_key in self.mask_keyframes or []:
            frame = int(raw_key.get("frame", 0))
            values = {key: float(raw_key.get(key, default)) for key, default in
                      (("x", self.mask_x), ("y", self.mask_y), ("width", self.mask_width), ("height", self.mask_height))}
            if frame < 0 or frame >= self.duration_frames or frame <= previous_mask_frame:
                raise ValueError("Mask keyframes must be ordered inside clip duration")
            if not all(math.isfinite(value) for value in values.values()):
                raise ValueError("Mask keyframe values must be finite")
            if not (0.0 <= values["x"] < 1.0 and 0.0 <= values["y"] < 1.0
                    and 0.0 < values["width"] <= 1.0 and 0.0 < values["height"] <= 1.0
                    and values["x"] + values["width"] <= 1.0 + 1e-9
                    and values["y"] + values["height"] <= 1.0 + 1e-9):
                raise ValueError("Mask keyframe rectangle must remain inside the frame")
            easing = str(raw_key.get("ease", "linear"))
            if easing not in {"linear", "ease_in", "ease_out", "ease_in_out", "bezier"}:
                raise ValueError("Unsupported mask keyframe easing")
            normalized_mask_keys.append({"frame": frame, **values, "ease": easing})
            previous_mask_frame = frame
        self.mask_keyframes = normalized_mask_keys
        if any(value > self.duration_frames for value in (self.fade_in_frames, self.fade_out_frames, self.video_fade_in_frames, self.video_fade_out_frames, self.transition_in_frames)):
            raise ValueError("Fade duration cannot exceed clip duration")
        grade = dict(self.color_grade or {})
        defaults = {"exposure": 0.0, "contrast": 1.0, "saturation": 1.0,
                    "temperature": 0.0, "tint": 0.0, "highlights": 0.0, "shadows": 0.0,
                    "whites": 0.0, "blacks": 0.0,
                    "wheel_shadows_r": 0.0, "wheel_shadows_g": 0.0, "wheel_shadows_b": 0.0,
                    "wheel_midtones_r": 0.0, "wheel_midtones_g": 0.0, "wheel_midtones_b": 0.0,
                    "wheel_highlights_r": 0.0, "wheel_highlights_g": 0.0, "wheel_highlights_b": 0.0}
        bounds = {"exposure": (-4.0, 4.0), "contrast": (0.0, 2.0),
                  "saturation": (0.0, 3.0), "temperature": (-1.0, 1.0),
                  "tint": (-1.0, 1.0), "highlights": (-1.0, 1.0),
                  "shadows": (-1.0, 1.0), "whites": (-1.0, 1.0),
                  "blacks": (-1.0, 1.0),
                  "wheel_shadows_r": (-1.0, 1.0), "wheel_shadows_g": (-1.0, 1.0), "wheel_shadows_b": (-1.0, 1.0),
                  "wheel_midtones_r": (-1.0, 1.0), "wheel_midtones_g": (-1.0, 1.0), "wheel_midtones_b": (-1.0, 1.0),
                  "wheel_highlights_r": (-1.0, 1.0), "wheel_highlights_g": (-1.0, 1.0), "wheel_highlights_b": (-1.0, 1.0)}
        normalized = {}
        for key, default in defaults.items():
            value = float(grade.get(key, default))
            low, high = bounds[key]
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"Invalid color grade value: {key}")
            normalized[key] = value
        self.color_grade = normalized

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TimelineProject:
    fps: int = DEFAULT_FPS
    width: int = 1920
    height: int = 1080
    video_tracks: list[str] = field(default_factory=lambda: list(DEFAULT_VIDEO_TRACKS))
    audio_tracks: list[str] = field(default_factory=lambda: list(DEFAULT_AUDIO_TRACKS))
    clips: list[Clip] = field(default_factory=list)
    playhead_frame: int = 0
    audio_track_settings: dict[str, dict[str, Any]] = field(default_factory=lambda: {
        track: {"volume": 1.0, "muted": False, "solo": False}
        for track in DEFAULT_AUDIO_TRACKS
    })
    audio_ducking: dict[str, Any] = field(default_factory=lambda: {
        "enabled": False, "voice_track": "A1", "music_track": "A2",
        "reduction_db": 12.0, "attack_ms": 20, "release_ms": 500,
    })

    def __post_init__(self) -> None:
        if self.fps < 1:
            raise ValueError("FPS must be positive")
        if self.width < 1 or self.height < 1:
            raise ValueError("Project dimensions must be positive")
        if self.playhead_frame < 0:
            self.playhead_frame = 0
        for track in self.audio_tracks:
            raw = self.audio_track_settings.get(track, {})
            volume = float(raw.get("volume", 1.0))
            if not math.isfinite(volume) or not 0.0 <= volume <= 2.0:
                raise ValueError(f"Invalid audio track volume: {track}")
            self.audio_track_settings[track] = {
                "volume": volume,
                "muted": bool(raw.get("muted", False)),
                "solo": bool(raw.get("solo", False)),
            }
        duck = dict(self.audio_ducking or {})
        voice_track = str(duck.get("voice_track", "A1"))
        music_track = str(duck.get("music_track", "A2"))
        reduction = float(duck.get("reduction_db", 12.0))
        attack = int(duck.get("attack_ms", 20))
        release = int(duck.get("release_ms", 500))
        if voice_track not in self.audio_tracks or music_track not in self.audio_tracks:
            raise ValueError("Ducking tracks must be valid audio tracks")
        if voice_track == music_track:
            raise ValueError("Voice and music tracks must be different")
        if not math.isfinite(reduction) or not 0.0 <= reduction <= 24.0:
            raise ValueError("Ducking reduction must be between 0 and 24 dB")
        if not 1 <= attack <= 500 or not 20 <= release <= 3000:
            raise ValueError("Ducking attack/release values are out of range")
        self.audio_ducking = {
            "enabled": bool(duck.get("enabled", False)),
            "voice_track": voice_track, "music_track": music_track,
            "reduction_db": reduction, "attack_ms": attack, "release_ms": release,
        }
        for clip in self.clips:
            clip.validate()

    @property
    def duration_frames(self) -> int:
        return max((clip.end_frame for clip in self.clips), default=0)

    def clips_on_track(self, track: str) -> list[Clip]:
        return sorted(
            (clip for clip in self.clips if clip.track == track),
            key=lambda clip: (clip.start_frame, clip.clip_id),
        )

    def add_clip(
        self,
        path: str,
        name: str,
        track: str = "V1",
        start_frame: int | None = None,
        duration_frames: int = 150,
        media_type: str = "video",
        has_audio: bool = False,
        audio_track: str | None = None,
    ) -> Clip:
        if track not in self.video_tracks + self.audio_tracks:
            raise ValueError(f"Unknown track: {track}")
        clip = Clip(
            path=path,
            name=name,
            track=track,
            start_frame=self.playhead_frame if start_frame is None else start_frame,
            duration_frames=duration_frames,
            media_type=media_type,
            has_audio=bool(has_audio),
            audio_track=audio_track or ("A1" if track.startswith("V") else track),
        )
        clip.validate()
        self.clips.append(clip)
        return clip

    def get_clip(self, clip_id: str) -> Clip:
        for clip in self.clips:
            if clip.clip_id == clip_id:
                return clip
        raise KeyError(f"Clip not found: {clip_id}")

    def move_clip(self, clip_id: str, start_frame: int, track: str | None = None) -> Clip:
        clip = self.get_clip(clip_id)
        if start_frame < 0:
            raise ValueError("Clip cannot start before frame zero")
        if track is not None:
            if track not in self.video_tracks + self.audio_tracks:
                raise ValueError(f"Unknown track: {track}")
            clip.track = track
        clip.start_frame = start_frame
        return clip

    def trim_clip(
        self,
        clip_id: str,
        *,
        new_start_frame: int | None = None,
        new_end_frame: int | None = None,
    ) -> Clip:
        clip = self.get_clip(clip_id)
        old_end = clip.end_frame
        start = clip.start_frame if new_start_frame is None else new_start_frame
        end = old_end if new_end_frame is None else new_end_frame
        if start < 0 or end <= start:
            raise ValueError("Trim must leave a positive clip duration")
        removed_from_left = start - clip.start_frame
        if clip.reverse_playback:
            removed_from_right = old_end - end
            clip.source_in += round(removed_from_right * clip.playback_rate)
        else:
            clip.source_in += round(removed_from_left * clip.playback_rate)
        clip.start_frame = start
        clip.duration_frames = end - start
        clip.fade_in_frames = max(0, clip.fade_in_frames - removed_from_left)
        clip.fade_in_frames = min(clip.fade_in_frames, clip.duration_frames)
        clip.fade_out_frames = min(clip.fade_out_frames, clip.duration_frames)
        clip.video_fade_in_frames = max(0, clip.video_fade_in_frames - removed_from_left)
        clip.video_fade_in_frames = min(clip.video_fade_in_frames, clip.duration_frames)
        clip.video_fade_out_frames = min(clip.video_fade_out_frames, clip.duration_frames)
        clip.transition_in_frames = min(clip.transition_in_frames, clip.duration_frames)
        original_keys = [dict(key) for key in clip.transform_keyframes]
        retained_keys = [
            dict(key, frame=int(key["frame"]) - removed_from_left)
            for key in original_keys
            if removed_from_left <= int(key["frame"]) < removed_from_left + clip.duration_frames
        ]
        if removed_from_left > 0 and original_keys and (
            not retained_keys or retained_keys[0]["frame"] > 0
        ):
            retained_keys.insert(0, {"frame": 0, **_transform_value_at(original_keys, removed_from_left)})
        clip.transform_keyframes = retained_keys
        original_ramp = [dict(point) for point in clip.speed_ramp]
        retained_ramp = [
            dict(point, frame=int(point["frame"]) - removed_from_left)
            for point in original_ramp
            if removed_from_left <= int(point["frame"]) < removed_from_left + clip.duration_frames
        ]
        if removed_from_left > 0 and original_ramp and (
            not retained_ramp or retained_ramp[0]["frame"] > 0
        ):
            retained_ramp.insert(0, {
                "frame": 0,
                "rate": _speed_rate_at(original_ramp, removed_from_left),
            })
        clip.speed_ramp = retained_ramp
        clip.validate()
        return clip

    def split_clip(self, clip_id: str, at_frame: int) -> tuple[Clip, Clip]:
        original = self.get_clip(clip_id)
        if not original.start_frame < at_frame < original.end_frame:
            raise ValueError("Split point must be inside the clip")
        right = Clip(
            path=original.path,
            name=original.name,
            track=original.track,
            start_frame=at_frame,
            source_in=original.source_in + (0 if original.reverse_playback else round((at_frame - original.start_frame) * original.playback_rate)),
            duration_frames=original.end_frame - at_frame,
            media_type=original.media_type,
            has_audio=original.has_audio,
            audio_track=original.audio_track,
            color_grade=dict(original.color_grade),
            anchor_x=original.anchor_x,
            anchor_y=original.anchor_y,
            playback_rate=original.playback_rate,
            motion_blur=original.motion_blur,
            speed_ramp=(
                [{"frame": 0, "rate": _speed_rate_at(original.speed_ramp, at_frame - original.start_frame)}]
                if original.speed_ramp else []
            ) + [
                dict(point, frame=int(point["frame"]) - (at_frame - original.start_frame))
                for point in original.speed_ramp
                if int(point["frame"]) > (at_frame - original.start_frame)
            ],
            reverse_playback=original.reverse_playback,
            volume=original.volume,
            fade_out_frames=original.fade_out_frames,
            video_fade_out_frames=original.video_fade_out_frames,
            transition_in_frames=0,
            blend_mode=original.blend_mode,
            chroma_key_enabled=original.chroma_key_enabled,
            chroma_key_color=original.chroma_key_color,
            chroma_key_similarity=original.chroma_key_similarity,
            chroma_key_blend=original.chroma_key_blend,
            mask_enabled=original.mask_enabled,
            mask_x=original.mask_x,
            mask_y=original.mask_y,
            mask_width=original.mask_width,
            mask_height=original.mask_height,
            mask_shape=original.mask_shape,
            mask_feather_px=original.mask_feather_px,
            mask_points=[list(point) for point in original.mask_points],
            mask_keyframes=[
                dict(key, frame=int(key["frame"]) - (at_frame - original.start_frame))
                for key in original.mask_keyframes
                if int(key["frame"]) >= (at_frame - original.start_frame)
            ],
            transform_keyframes=[
                dict(key, frame=int(key["frame"]) - (at_frame - original.start_frame))
                for key in original.transform_keyframes
                if int(key["frame"]) >= (at_frame - original.start_frame)
            ],
        )
        original.duration_frames = at_frame - original.start_frame
        if original.reverse_playback:
            original.source_in += round(right.duration_frames * original.playback_rate)
        original.fade_out_frames = 0
        original.video_fade_out_frames = 0
        original.video_fade_in_frames = min(original.video_fade_in_frames, original.duration_frames)
        original.transition_in_frames = min(original.transition_in_frames, original.duration_frames)
        original.transform_keyframes = [dict(k) for k in original.transform_keyframes if k["frame"] < original.duration_frames]
        original.mask_keyframes = [dict(k) for k in original.mask_keyframes if k["frame"] < original.duration_frames]
        original.speed_ramp = [dict(point) for point in original.speed_ramp if point["frame"] < original.duration_frames]
        original.fade_in_frames = min(original.fade_in_frames, original.duration_frames)
        self.clips.append(right)
        return original, right

    def set_clip_transform_keyframes(self, clip_id: str, keyframes: list[dict[str, float]]) -> Clip:
        """Set frame-relative transform keyframes; values are normalized to frame dimensions."""
        clip = self.get_clip(clip_id)
        if clip.media_type != "video" or not clip.track.startswith("V"):
            raise ValueError("Transform animation requires a video-track clip")
        clip.transform_keyframes = [dict(item) for item in keyframes]
        clip.validate()
        return clip

    def set_clip_color(self, clip_id: str, **values: float) -> Clip:
        """Set validated, non-destructive per-clip color grading controls."""
        clip = self.get_clip(clip_id)
        allowed = {"exposure", "contrast", "saturation", "temperature", "tint",
                   "highlights", "shadows", "whites", "blacks",
                   "wheel_shadows_r", "wheel_shadows_g", "wheel_shadows_b",
                   "wheel_midtones_r", "wheel_midtones_g", "wheel_midtones_b",
                   "wheel_highlights_r", "wheel_highlights_g", "wheel_highlights_b"}
        if set(values) - allowed:
            raise ValueError("Unknown color grading control")
        grade = dict(clip.color_grade)
        grade.update({key: float(value) for key, value in values.items()})
        clip.color_grade = grade
        clip.validate()
        return clip

    def set_clip_audio(self, clip_id: str, *, volume: float | None = None,
                        fade_in_frames: int | None = None,
                        fade_out_frames: int | None = None) -> Clip:
        """Set non-destructive clip gain and frame-accurate audio fades."""
        clip = self.get_clip(clip_id)
        if volume is not None:
            clip.volume = float(volume)
        if fade_in_frames is not None:
            clip.fade_in_frames = int(fade_in_frames)
        if fade_out_frames is not None:
            clip.fade_out_frames = int(fade_out_frames)
        clip.validate()
        return clip

    def set_clip_reverse(self, clip_id: str, enabled: bool) -> Clip:
        """Reverse video and its embedded audio in the final render."""
        clip = self.get_clip(clip_id)
        if clip.media_type != "video" or not clip.track.startswith("V"):
            raise ValueError("Reverse requires a video-track clip")
        clip.reverse_playback = bool(enabled)
        clip.validate()
        return clip

    def set_clip_speed_ramp(self, clip_id: str, keyframes: list[dict[str, float]]) -> Clip:
        """Set clip-local speed-ramp points; rendering support is handled by the render pipeline."""
        clip = self.get_clip(clip_id)
        if clip.media_type != "video" or not clip.track.startswith("V"):
            raise ValueError("Speed Ramp requires a video-track clip")
        clip.speed_ramp = [dict(point) for point in keyframes]
        clip.validate()
        return clip

    def set_clip_motion_blur(self, clip_id: str, enabled: bool) -> Clip:
        """Enable a lightweight three-frame temporal blend on a video clip."""
        clip = self.get_clip(clip_id)
        if clip.media_type != "video" or not clip.track.startswith("V"):
            raise ValueError("Motion Blur requires a video-track clip")
        clip.motion_blur = bool(enabled)
        clip.validate()
        return clip

    def set_clip_speed(self, clip_id: str, playback_rate: float) -> Clip:
        """Change playback rate while preserving the source-media span."""
        clip = self.get_clip(clip_id)
        if clip.media_type != "video" or not clip.track.startswith("V"):
            raise ValueError("Playback speed control requires a video-track clip")
        rate = float(playback_rate)
        if not math.isfinite(rate) or not 0.25 <= rate <= 4.0:
            raise ValueError("Playback rate must be between 0.25x and 4.0x")
        old_duration = clip.duration_frames
        new_duration = max(1, round(old_duration * clip.playback_rate / rate))
        ratio = new_duration / old_duration
        clip.transform_keyframes = [
            dict(key, frame=min(new_duration - 1, round(int(key["frame"]) * ratio)))
            for key in clip.transform_keyframes
        ]
        clip.transform_keyframes.sort(key=lambda item: int(item["frame"]))
        clip.speed_ramp = [
            dict(point, frame=min(new_duration - 1, round(int(point["frame"]) * ratio)))
            for point in clip.speed_ramp
        ]
        clip.speed_ramp.sort(key=lambda item: int(item["frame"]))
        clip.speed_ramp = [
            point for index, point in enumerate(clip.speed_ramp)
            if index == 0 or point["frame"] > clip.speed_ramp[index - 1]["frame"]
        ]
        clip.transform_keyframes = [
            key for index, key in enumerate(clip.transform_keyframes)
            if index == 0 or key["frame"] > clip.transform_keyframes[index - 1]["frame"]
        ]
        for field_name in ("fade_in_frames", "fade_out_frames", "video_fade_in_frames",
                           "video_fade_out_frames", "transition_in_frames"):
            setattr(clip, field_name, min(new_duration, round(getattr(clip, field_name) * ratio)))
        clip.duration_frames = new_duration
        clip.playback_rate = rate
        clip.validate()
        return clip
    def set_clip_video_fade(self, clip_id: str, *, fade_in_frames: int | None = None,
                            fade_out_frames: int | None = None) -> Clip:
        """Set non-destructive visual fades, measured in timeline frames."""
        clip = self.get_clip(clip_id)
        if clip.media_type != "video" or not clip.track.startswith("V"):
            raise ValueError("Visual fades require a video-track clip")
        if fade_in_frames is not None:
            clip.video_fade_in_frames = int(fade_in_frames)
        if fade_out_frames is not None:
            clip.video_fade_out_frames = int(fade_out_frames)
        clip.validate()
        return clip

    def set_clip_transition(self, clip_id: str, *, dissolve_in_frames: int, transition_type: str = "dissolve") -> Clip:
        """Set a pre-roll cross dissolve on an incoming video clip."""
        clip = self.get_clip(clip_id)
        if clip.media_type != "video" or not clip.track.startswith("V"):
            raise ValueError("Cross Dissolve requires a video-track clip")
        frames = int(dissolve_in_frames)
        if transition_type not in {"dissolve", "wipe_left", "push_left"}:
            raise ValueError("Unsupported video transition type")
        if frames < 0 or frames > clip.duration_frames:
            raise ValueError("Cross Dissolve duration must be within clip duration")
        if frames:
            previous = next((item for item in reversed(self.clips_on_track(clip.track))
                             if item.start_frame < clip.start_frame), None)
            if previous is None or previous.end_frame != clip.start_frame:
                raise ValueError("Cross Dissolve requires an adjacent previous clip on the same track")
            if frames > previous.duration_frames:
                raise ValueError("Cross Dissolve duration exceeds the previous clip")
            still_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
            if Path(clip.path).suffix.lower() not in still_extensions and clip.source_in < round(frames * clip.playback_rate):
                raise ValueError("Cross Dissolve needs source handle frames before the incoming clip in-point")
            before_previous = next((item for item in reversed(self.clips_on_track(clip.track))
                                     if item.start_frame < previous.start_frame), None)
            if before_previous and previous.transition_in_frames + frames > previous.duration_frames:
                raise ValueError("Adjacent Cross Dissolves exceed the middle clip duration")
        clip.transition_in_frames = frames
        clip.transition_in_type = transition_type
        clip.validate()
        return clip

    def remove_clip(self, clip_id: str, ripple: bool = False) -> Clip:
        clip = self.get_clip(clip_id)
        self.clips.remove(clip)
        if ripple:
            for other in self.clips:
                if other.track == clip.track and other.start_frame >= clip.end_frame:
                    other.start_frame = max(0, other.start_frame - clip.duration_frames)
        return clip

    def set_audio_track(self, track: str, *, volume: float | None = None,
                        muted: bool | None = None, solo: bool | None = None) -> dict[str, Any]:
        if track not in self.audio_tracks:
            raise ValueError(f"Unknown audio track: {track}")
        settings = self.audio_track_settings.setdefault(
            track, {"volume": 1.0, "muted": False, "solo": False}
        )
        if volume is not None:
            value = float(volume)
            if not math.isfinite(value) or not 0.0 <= value <= 2.0:
                raise ValueError("Track volume must be between 0.0 and 2.0")
            settings["volume"] = value
        if muted is not None:
            settings["muted"] = bool(muted)
        if solo is not None:
            settings["solo"] = bool(solo)
        return dict(settings)

    def set_audio_ducking(self, *, enabled: bool | None = None,
                          voice_track: str | None = None,
                          music_track: str | None = None,
                          reduction_db: float | None = None,
                          attack_ms: int | None = None,
                          release_ms: int | None = None) -> dict[str, Any]:
        values = dict(self.audio_ducking)
        for key, value in {
            "enabled": enabled, "voice_track": voice_track,
            "music_track": music_track, "reduction_db": reduction_db,
            "attack_ms": attack_ms, "release_ms": release_ms,
        }.items():
            if value is not None:
                values[key] = value
        # Reuse project validation to keep the persisted settings canonical.
        previous = dict(self.audio_ducking)
        self.audio_ducking = values
        try:
            self.__post_init__()
        except (TypeError, ValueError):
            self.audio_ducking = previous
            raise
        return dict(self.audio_ducking)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROJECT_SCHEMA_VERSION,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "video_tracks": self.video_tracks,
            "audio_tracks": self.audio_tracks,
            "playhead_frame": self.playhead_frame,
            "audio_track_settings": self.audio_track_settings,
            "audio_ducking": self.audio_ducking,
            "clips": [clip.to_dict() for clip in self.clips],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TimelineProject":
        """Load schema v1-v6 and migrate older path/name/track list projects."""
        fps = int(data.get("fps", DEFAULT_FPS) or DEFAULT_FPS)
        raw_clips = data.get("clips")
        if raw_clips is None:
            raw_clips = data.get("timeline", [])

        clips: list[Clip] = []
        legacy_track_cursor: dict[str, int] = {}
        for raw in raw_clips:
            path = str(raw.get("path", ""))
            name = str(raw.get("name") or path.replace(chr(92), "/").rsplit("/", 1)[-1] or "Untitled")
            track = str(raw.get("track", "V1"))
            if track not in DEFAULT_VIDEO_TRACKS + DEFAULT_AUDIO_TRACKS:
                track = "V1"
            # Legacy projects stored no timing. Place those clips sequentially
            # on their track using a five-second editable placeholder.
            duration = max(1, int(raw.get("duration_frames", 150) or 150))
            if "start_frame" in raw:
                start_frame = max(0, int(raw.get("start_frame", 0) or 0))
            else:
                start_frame = legacy_track_cursor.get(track, 0)
            legacy_track_cursor[track] = max(
                legacy_track_cursor.get(track, 0), start_frame + duration
            )
            clips.append(Clip(
                path=path,
                name=name,
                track=track,
                start_frame=start_frame,
                source_in=max(0, int(raw.get("source_in", 0) or 0)),
                duration_frames=duration,
                clip_id=str(raw.get("clip_id") or _new_id()),
                media_type=str(raw.get("media_type", "audio" if track.startswith("A") else "video")),
                has_audio=bool(raw.get("has_audio", raw.get("media_type", "audio" if track.startswith("A") else "video") == "audio")),
                audio_track=str(raw.get("audio_track") or (track if track.startswith("A") else "A1")),
                volume=float(raw.get("volume", 1.0)),
                fade_in_frames=max(0, int(raw.get("fade_in_frames", 0) or 0)),
                fade_out_frames=max(0, int(raw.get("fade_out_frames", 0) or 0)),
                video_fade_in_frames=max(0, int(raw.get("video_fade_in_frames", 0) or 0)),
                video_fade_out_frames=max(0, int(raw.get("video_fade_out_frames", 0) or 0)),
                transition_in_frames=max(0, int(raw.get("transition_in_frames", 0) or 0)),
                transition_in_type=str(raw.get("transition_in_type", "dissolve") or "dissolve"),
                blend_mode=str(raw.get("blend_mode", "normal") or "normal"),
                chroma_key_enabled=bool(raw.get("chroma_key_enabled", False)),
                chroma_key_color=str(raw.get("chroma_key_color", "#00FF00") or "#00FF00"),
                chroma_key_similarity=float(raw.get("chroma_key_similarity", 0.25)),
                chroma_key_blend=float(raw.get("chroma_key_blend", 0.08)),
                mask_enabled=bool(raw.get("mask_enabled", False)),
                mask_x=float(raw.get("mask_x", 0.0)),
                mask_y=float(raw.get("mask_y", 0.0)),
                mask_width=float(raw.get("mask_width", 1.0)),
                mask_height=float(raw.get("mask_height", 1.0)),
                mask_shape=str(raw.get("mask_shape", "rectangle") or "rectangle"),
                mask_feather_px=float(raw.get("mask_feather_px", 0.0)),
                mask_points=[list(point) for point in raw.get("mask_points", [[0.5, 0.1], [0.9, 0.9], [0.1, 0.9]])],
                mask_keyframes=[dict(k) for k in raw.get("mask_keyframes", [])],
                transform_keyframes=[dict(k) for k in raw.get("transform_keyframes", [])],
                anchor_x=float(raw.get("anchor_x", 0.5)),
                anchor_y=float(raw.get("anchor_y", 0.5)),
                playback_rate=float(raw.get("playback_rate", 1.0)),
                speed_ramp=[dict(point) for point in raw.get("speed_ramp", [])],
                motion_blur=bool(raw.get("motion_blur", False)),
                reverse_playback=bool(raw.get("reverse_playback", False)),
                color_grade=dict(raw.get("color_grade") or {}),
            ))
        return cls(
            fps=fps,
            width=int(data.get("width", 1920) or 1920),
            height=int(data.get("height", 1080) or 1080),
            video_tracks=list(data.get("video_tracks") or DEFAULT_VIDEO_TRACKS),
            audio_tracks=list(data.get("audio_tracks") or DEFAULT_AUDIO_TRACKS),
            clips=clips,
            playhead_frame=max(0, int(data.get("playhead_frame", 0) or 0)),
            audio_track_settings=dict(data.get("audio_track_settings") or {}),
            audio_ducking=dict(data.get("audio_ducking") or {}),
        )
