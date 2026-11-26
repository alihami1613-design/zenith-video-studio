"""Frame-accurate, UI-independent timeline model for ZENITH Desktop.

The model intentionally stores time as integer frames. It has no Qt dependency,
so timeline editing logic can be tested without opening the GUI.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any
from uuid import uuid4

PROJECT_SCHEMA_VERSION = 5
DEFAULT_FPS = 30
DEFAULT_VIDEO_TRACKS = ("V1", "V2", "V3", "V4")
DEFAULT_AUDIO_TRACKS = ("A1", "A2", "A3", "A4")


def _new_id() -> str:
    return uuid4().hex[:12]


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
    volume: float = 1.0
    fade_in_frames: int = 0
    fade_out_frames: int = 0

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
        if not math.isfinite(float(self.volume)) or not 0.0 <= float(self.volume) <= 2.0:
            raise ValueError("Clip volume must be between 0.0 and 2.0")
        if self.fade_in_frames < 0 or self.fade_out_frames < 0:
            raise ValueError("Fade durations cannot be negative")
        if self.fade_in_frames > self.duration_frames or self.fade_out_frames > self.duration_frames:
            raise ValueError("Fade duration cannot exceed clip duration")

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
        clip.source_in += removed_from_left
        clip.start_frame = start
        clip.duration_frames = end - start
        clip.fade_in_frames = max(0, clip.fade_in_frames - removed_from_left)
        clip.fade_in_frames = min(clip.fade_in_frames, clip.duration_frames)
        clip.fade_out_frames = min(clip.fade_out_frames, clip.duration_frames)
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
            source_in=original.source_in + (at_frame - original.start_frame),
            duration_frames=original.end_frame - at_frame,
            media_type=original.media_type,
            volume=original.volume,
            fade_out_frames=original.fade_out_frames,
        )
        original.duration_frames = at_frame - original.start_frame
        original.fade_out_frames = 0
        original.fade_in_frames = min(original.fade_in_frames, original.duration_frames)
        self.clips.append(right)
        return original, right

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
        """Load schema v4 and migrate older path/name/track list projects."""
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
                volume=float(raw.get("volume", 1.0)),
                fade_in_frames=max(0, int(raw.get("fade_in_frames", 0) or 0)),
                fade_out_frames=max(0, int(raw.get("fade_out_frames", 0) or 0)),
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
