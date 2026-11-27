"""Provider-agnostic contracts for ZENITH's autonomous editing agent.

This module defines plans, not an LLM integration. Plans are untrusted input until
validated against the current project and media inventory. No code execution,
filesystem mutation, or timeline mutation happens in this module.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import re
from typing import Any, Mapping


PLAN_FORMAT_VERSION = 1
PLAN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")
OPERATION_KINDS = frozenset({
    "add_clip", "move_clip", "trim_clip", "set_clip_grade",
    "set_clip_volume", "set_transition",
})
VIDEO_TRACKS = frozenset({"V1", "V2", "V3", "V4"})
AUDIO_TRACKS = frozenset({"A1", "A2", "A3", "A4"})
GRADE_BOUNDS = {
    "exposure": (-4.0, 4.0), "contrast": (0.0, 2.0),
    "saturation": (0.0, 3.0), "temperature": (-1.0, 1.0),
    "tint": (-1.0, 1.0), "highlights": (-1.0, 1.0),
    "shadows": (-1.0, 1.0), "whites": (-1.0, 1.0),
    "blacks": (-1.0, 1.0),
    **{f"wheel_{zone}_{channel}": (-1.0, 1.0)
       for zone in ("shadows", "midtones", "highlights")
       for channel in ("r", "g", "b")},
}


class EditPlanError(ValueError):
    """An AI-generated edit plan is malformed, unsafe, or incompatible."""


@dataclass(frozen=True)
class ProjectBrief:
    prompt: str
    target_duration_frames: int | None = None
    style: str = ""
    audience: str = ""
    language: str = ""
    output_width: int | None = None
    output_height: int | None = None
    output_fps: int | None = None
    allow_online_asset_search: bool = False
    allow_cloud_media_analysis: bool = False

    def validate(self) -> None:
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise EditPlanError("A non-empty natural-language prompt is required.")
        if len(self.prompt) > 20_000:
            raise EditPlanError("Prompt exceeds the 20,000-character limit.")
        if self.target_duration_frames is not None and (
            isinstance(self.target_duration_frames, bool)
            or not isinstance(self.target_duration_frames, int)
            or self.target_duration_frames < 1
        ):
            raise EditPlanError("Target duration must be a positive frame count.")
        for name in ("output_width", "output_height", "output_fps"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise EditPlanError(f"{name} must be a positive integer.")


@dataclass(frozen=True)
class MediaAsset:
    asset_id: str
    path: str
    media_type: str
    duration_frames: int
    fps: int
    width: int = 0
    height: int = 0
    has_audio: bool = False

    def validate(self) -> None:
        if not self.asset_id or not isinstance(self.asset_id, str):
            raise EditPlanError("Every media asset needs a stable asset_id.")
        if not self.path or not isinstance(self.path, str):
            raise EditPlanError(f"Asset {self.asset_id} has no path.")
        if self.media_type not in {"video", "audio", "image"}:
            raise EditPlanError(f"Asset {self.asset_id} has an unsupported media type.")
        if isinstance(self.duration_frames, bool) or not isinstance(self.duration_frames, int) or self.duration_frames < 0:
            raise EditPlanError(f"Asset {self.asset_id} has an invalid duration.")
        if isinstance(self.fps, bool) or not isinstance(self.fps, int) or self.fps < 1:
            raise EditPlanError(f"Asset {self.asset_id} has an invalid frame rate.")


@dataclass(frozen=True)
class EditOperation:
    operation_id: str
    kind: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    rationale: str = ""

    def validate_shape(self) -> None:
        if not PLAN_ID_RE.fullmatch(self.operation_id or ""):
            raise EditPlanError("Operation IDs must be 3-80 safe characters.")
        if self.kind not in OPERATION_KINDS:
            raise EditPlanError(f"Unsupported edit operation: {self.kind}")
        if not isinstance(self.parameters, Mapping):
            raise EditPlanError("Operation parameters must be an object.")
        if not isinstance(self.rationale, str) or len(self.rationale) > 2_000:
            raise EditPlanError("Operation rationale is invalid.")


@dataclass(frozen=True)
class EditPlan:
    plan_id: str
    brief: ProjectBrief
    summary: str
    operations: tuple[EditOperation, ...]
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    format_version: int = PLAN_FORMAT_VERSION
    requires_user_approval: bool = True

    def validate(self, assets: tuple[MediaAsset, ...] | list[MediaAsset],
                 existing_clip_ids: set[str] | None = None) -> None:
        if self.format_version != PLAN_FORMAT_VERSION:
            raise EditPlanError("Unsupported edit-plan format version.")
        if not PLAN_ID_RE.fullmatch(self.plan_id or ""):
            raise EditPlanError("Plan ID must be 3-80 safe characters.")
        self.brief.validate()
        if not isinstance(self.summary, str) or not self.summary.strip() or len(self.summary) > 8_000:
            raise EditPlanError("Plan summary is required and must be at most 8,000 characters.")
        if not isinstance(self.requires_user_approval, bool) or not self.requires_user_approval:
            raise EditPlanError("AI edit plans must require explicit user approval.")
        if len(self.operations) > 10_000:
            raise EditPlanError("Edit plan contains too many operations.")
        asset_map: dict[str, MediaAsset] = {}
        for asset in assets:
            asset.validate()
            if asset.asset_id in asset_map:
                raise EditPlanError(f"Duplicate media asset ID: {asset.asset_id}")
            asset_map[asset.asset_id] = asset
        clip_ids = set(existing_clip_ids or ())
        operation_ids: set[str] = set()
        for operation in self.operations:
            operation.validate_shape()
            if operation.operation_id in operation_ids:
                raise EditPlanError(f"Duplicate operation ID: {operation.operation_id}")
            operation_ids.add(operation.operation_id)
            p = dict(operation.parameters)
            if operation.kind == "add_clip":
                _only_keys(p, {"asset_id", "track", "start_frame", "source_in",
                               "duration_frames", "audio_track"})
                asset_id = p.get("asset_id")
                if asset_id not in asset_map:
                    raise EditPlanError(f"Unknown media asset: {asset_id}")
                asset = asset_map[asset_id]
                track = p.get("track", "V1")
                allowed_tracks = AUDIO_TRACKS if asset.media_type == "audio" else VIDEO_TRACKS
                if track not in allowed_tracks:
                    raise EditPlanError(f"Track {track} is incompatible with {asset.media_type}.")
                start = _int(p, "start_frame", minimum=0)
                source_in = _int(p, "source_in", minimum=0, default=0)
                duration = _int(p, "duration_frames", minimum=1)
                if asset.duration_frames and source_in + duration > asset.duration_frames:
                    raise EditPlanError(f"Operation {operation.operation_id} exceeds source duration.")
                if asset.media_type == "audio" and "audio_track" in p and p["audio_track"] not in AUDIO_TRACKS:
                    raise EditPlanError("Audio clips must route to A1-A4.")
            elif operation.kind in {"move_clip", "trim_clip", "set_clip_grade",
                                    "set_clip_volume", "set_transition"}:
                clip_id = p.get("clip_id")
                if not isinstance(clip_id, str) or not clip_id:
                    raise EditPlanError(f"{operation.kind} requires clip_id.")
                if clip_id not in clip_ids:
                    raise EditPlanError(f"Unknown existing clip ID: {clip_id}")
                if operation.kind == "move_clip":
                    _only_keys(p, {"clip_id", "start_frame", "track"})
                    _int(p, "start_frame", minimum=0)
                    if "track" in p and p["track"] not in VIDEO_TRACKS | AUDIO_TRACKS:
                        raise EditPlanError("Move operation targets an unknown track.")
                elif operation.kind == "trim_clip":
                    _only_keys(p, {"clip_id", "new_start_frame", "new_end_frame"})
                    start = _int(p, "new_start_frame", minimum=0)
                    end = _int(p, "new_end_frame", minimum=1)
                    if end <= start:
                        raise EditPlanError("Trim end must be after trim start.")
                elif operation.kind == "set_clip_grade":
                    _only_keys(p, {"clip_id", "grade"})
                    grade = p.get("grade")
                    if not isinstance(grade, Mapping) or not grade:
                        raise EditPlanError("Grade operation requires a non-empty grade object.")
                    for key, value in grade.items():
                        if key not in GRADE_BOUNDS:
                            raise EditPlanError(f"Unsupported color parameter: {key}")
                        _bounded_number(value, key, *GRADE_BOUNDS[key])
                elif operation.kind == "set_clip_volume":
                    _only_keys(p, {"clip_id", "volume"})
                    _bounded_number(p.get("volume"), "volume", 0.0, 2.0)
                else:
                    _only_keys(p, {"clip_id", "duration_frames", "transition_type"})
                    _int(p, "duration_frames", minimum=0)
                    if p.get("transition_type", "dissolve") not in {"dissolve", "wipe_left", "push_left"}:
                        raise EditPlanError("Unsupported transition type.")


def _only_keys(parameters: Mapping[str, Any], allowed: set[str]) -> None:
    extra = set(parameters) - allowed
    if extra:
        raise EditPlanError(f"Unexpected operation parameters: {', '.join(sorted(extra))}")


def _int(parameters: Mapping[str, Any], key: str, *, minimum: int,
         default: int | None = None) -> int:
    value = parameters.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise EditPlanError(f"{key} must be an integer greater than or equal to {minimum}.")
    return value


def _bounded_number(value: Any, name: str, minimum: float, maximum: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EditPlanError(f"{name} must be numeric.")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise EditPlanError(f"{name} must be between {minimum} and {maximum}.")


def plan_to_dict(plan: EditPlan) -> dict[str, Any]:
    """Return a JSON-serializable representation suitable for provider exchange."""
    return asdict(plan)


def plan_from_dict(data: Mapping[str, Any]) -> EditPlan:
    """Parse provider output without executing it; call validate() before use."""
    if not isinstance(data, Mapping):
        raise EditPlanError("Edit plan must be a JSON object.")
    try:
        brief_data = data["brief"]
        operations_data = data["operations"]
        if not isinstance(brief_data, Mapping) or not isinstance(operations_data, (list, tuple)):
            raise EditPlanError("Plan brief and operations have invalid shapes.")
        brief = ProjectBrief(**dict(brief_data))
        operations = tuple(EditOperation(
            operation_id=item["operation_id"], kind=item["kind"],
            parameters=item.get("parameters", {}), rationale=item.get("rationale", "")
        ) for item in operations_data if isinstance(item, Mapping))
        if len(operations) != len(operations_data):
            raise EditPlanError("Every operation must be an object.")
        return EditPlan(
            plan_id=data["plan_id"], brief=brief, summary=data["summary"],
            operations=operations,
            assumptions=tuple(data.get("assumptions", ())),
            warnings=tuple(data.get("warnings", ())),
            format_version=data.get("format_version", PLAN_FORMAT_VERSION),
            requires_user_approval=data.get("requires_user_approval", True),
        )
    except EditPlanError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise EditPlanError(f"Malformed edit plan: {exc}") from exc
