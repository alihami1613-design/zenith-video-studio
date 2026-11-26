"""Frame-accurate, UI-independent timeline model for ZENITH Desktop.

The model intentionally stores time as integer frames. It has no Qt dependency,
so timeline editing logic can be tested without opening the GUI.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

PROJECT_SCHEMA_VERSION = 2
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

    def __post_init__(self) -> None:
        if self.fps < 1:
            raise ValueError("FPS must be positive")
        if self.width < 1 or self.height < 1:
            raise ValueError("Project dimensions must be positive")
        if self.playhead_frame < 0:
            self.playhead_frame = 0
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
        clip.source_in += start - clip.start_frame
        clip.start_frame = start
        clip.duration_frames = end - start
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
        )
        original.duration_frames = at_frame - original.start_frame
        self.clips.append(right)
        return original, right

    def remove_clip(self, clip_id: str, ripple: bool = False) -> Clip:
        clip = self.get_clip(clip_id)
        self.clips.remove(clip)
        if ripple:
            for other in self.clips:
                if other.track == clip.track and other.start_frame >= clip.end_frame:
                    other.start_frame = max(0, other.start_frame - clip.duration_frames)
        return clip

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROJECT_SCHEMA_VERSION,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "video_tracks": self.video_tracks,
            "audio_tracks": self.audio_tracks,
            "playhead_frame": self.playhead_frame,
            "clips": [clip.to_dict() for clip in self.clips],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TimelineProject":
        """Load schema v2 and migrate the original path/name/track list format."""
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
            ))
        return cls(
            fps=fps,
            width=int(data.get("width", 1920) or 1920),
            height=int(data.get("height", 1080) or 1080),
            video_tracks=list(data.get("video_tracks") or DEFAULT_VIDEO_TRACKS),
            audio_tracks=list(data.get("audio_tracks") or DEFAULT_AUDIO_TRACKS),
            clips=clips,
            playhead_frame=max(0, int(data.get("playhead_frame", 0) or 0)),
        )
