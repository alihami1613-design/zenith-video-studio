"""Narrative architecture for AI-assisted editorial storytelling.

A story blueprint describes editorial intent before any timeline mutation. It
uses only asset IDs and time ranges from the local project inventory; it never
claims semantic understanding that has not been supplied by an analyzer.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from typing import Any, Mapping, Protocol

from ai_editor.contracts import EditPlanError
from ai_editor.media_analysis import MediaAnalysisReport
from ai_editor.project_context import ProjectContext


STORY_FORMAT_VERSION = 1
BEAT_TYPES = frozenset({
    "hook", "setup", "context", "discovery", "conflict", "escalation",
    "revelation", "climax", "resolution", "call_to_action",
})
ACT_TYPES = frozenset({"opening", "development", "climax", "ending"})
TRANSITION_INTENTS = frozenset({
    "hard_cut", "match_cut", "dissolve", "fade", "motivated_transition",
})


@dataclass(frozen=True)
class StoryBeat:
    beat_id: str
    sequence: int
    beat_type: str
    title: str
    purpose: str
    target_duration_seconds: float
    asset_id: str | None = None
    source_in_seconds: float | None = None
    source_out_seconds: float | None = None
    visual_intent: str = ""
    narration_intent: str = ""
    sound_intent: str = ""
    transition_intent: str = "hard_cut"


@dataclass(frozen=True)
class StoryAct:
    act_id: str
    act_type: str
    title: str
    dramatic_question: str
    beats: tuple[StoryBeat, ...]


@dataclass(frozen=True)
class StoryBlueprint:
    story_id: str
    original_prompt: str
    logline: str
    audience_promise: str
    emotional_arc: str
    estimated_duration_seconds: float
    acts: tuple[StoryAct, ...]
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    format_version: int = STORY_FORMAT_VERSION
    requires_user_approval: bool = True

    @property
    def beats(self) -> tuple[StoryBeat, ...]:
        return tuple(beat for act in self.acts for beat in act.beats)

    def validate(self, context: ProjectContext) -> None:
        if self.format_version != STORY_FORMAT_VERSION:
            raise EditPlanError("Unsupported story-blueprint format version.")
        for name, value, limit in (
            ("story_id", self.story_id, 80),
            ("logline", self.logline, 2_000),
            ("audience_promise", self.audience_promise, 2_000),
            ("emotional_arc", self.emotional_arc, 2_000),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise EditPlanError(f"{name} is required and must be within its length limit.")
        if not isinstance(self.original_prompt, str) or not self.original_prompt.strip():
            raise EditPlanError("Original story prompt is required.")
        if not isinstance(self.requires_user_approval, bool) or not self.requires_user_approval:
            raise EditPlanError("Story blueprints must require explicit user approval.")
        _positive_finite(self.estimated_duration_seconds, "estimated_duration_seconds")
        if not 1 <= len(self.acts) <= 8:
            raise EditPlanError("A story must contain between 1 and 8 acts.")
        known_assets = {
            item.asset.asset_id: item for item in context.assets if item.exists
        }
        act_ids: set[str] = set()
        beat_ids: set[str] = set()
        sequences: list[int] = []
        total_duration = 0.0
        for act in self.acts:
            if act.act_id in act_ids or not act.act_id:
                raise EditPlanError("Act IDs must be non-empty and unique.")
            act_ids.add(act.act_id)
            if act.act_type not in ACT_TYPES:
                raise EditPlanError(f"Unsupported story act type: {act.act_type}")
            if not act.title.strip() or not act.dramatic_question.strip():
                raise EditPlanError("Every act needs a title and dramatic question.")
            if not 1 <= len(act.beats) <= 30:
                raise EditPlanError("Each act must contain between 1 and 30 beats.")
            for beat in act.beats:
                if not beat.beat_id or beat.beat_id in beat_ids:
                    raise EditPlanError("Beat IDs must be non-empty and unique.")
                beat_ids.add(beat.beat_id)
                if isinstance(beat.sequence, bool) or not isinstance(beat.sequence, int) or beat.sequence < 0:
                    raise EditPlanError("Beat sequence must be a non-negative integer.")
                sequences.append(beat.sequence)
                if beat.beat_type not in BEAT_TYPES:
                    raise EditPlanError(f"Unsupported beat type: {beat.beat_type}")
                if not beat.title.strip() or not beat.purpose.strip():
                    raise EditPlanError("Every beat needs a title and narrative purpose.")
                _positive_finite(beat.target_duration_seconds, "beat duration")
                total_duration += beat.target_duration_seconds
                if beat.transition_intent not in TRANSITION_INTENTS:
                    raise EditPlanError("Unsupported transition intent.")
                if beat.asset_id is None:
                    if beat.source_in_seconds is not None or beat.source_out_seconds is not None:
                        raise EditPlanError("Source ranges require an asset_id.")
                else:
                    item = known_assets.get(beat.asset_id)
                    if item is None:
                        raise EditPlanError(f"Beat references unknown media asset: {beat.asset_id}")
                    if item.asset.media_type == "image":
                        if (beat.source_in_seconds is None) != (beat.source_out_seconds is None):
                            raise EditPlanError("Image source ranges must be either fully omitted or complete.")
                        if beat.source_in_seconds is not None:
                            start = _nonnegative_finite(beat.source_in_seconds, "source_in_seconds")
                            end = _positive_finite(beat.source_out_seconds, "source_out_seconds")
                            if end <= start:
                                raise EditPlanError("Beat source out must be after source in.")
                    else:
                        if beat.source_in_seconds is None or beat.source_out_seconds is None:
                            raise EditPlanError("Video/audio beats require a complete source range.")
                        start = _nonnegative_finite(beat.source_in_seconds, "source_in_seconds")
                        end = _positive_finite(beat.source_out_seconds, "source_out_seconds")
                        if end <= start:
                            raise EditPlanError("Beat source out must be after source in.")
                        if item.duration_seconds is not None and end > item.duration_seconds + 0.05:
                            raise EditPlanError("Beat source range exceeds the media duration.")
        if sorted(sequences) != list(range(len(sequences))):
            raise EditPlanError("Beat sequence values must be unique and contiguous from zero.")
        if not math.isclose(total_duration, self.estimated_duration_seconds, rel_tol=0.03, abs_tol=1.0):
            raise EditPlanError("Estimated story duration does not match the sum of beat durations.")
        for collection_name, values in (("assumptions", self.assumptions), ("warnings", self.warnings)):
            if not isinstance(values, tuple) or any(not isinstance(v, str) or len(v) > 2000 for v in values):
                raise EditPlanError(f"{collection_name} must contain bounded text entries.")


def _positive_finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EditPlanError(f"{name} must be numeric.")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise EditPlanError(f"{name} must be a positive finite number.")
    return result


def _nonnegative_finite(value: Any, name: str) -> float:
    result = _positive_finite(value, name) if value != 0 else 0.0
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or result < 0:
        raise EditPlanError(f"{name} must be a non-negative finite number.")
    return result


class StoryBlueprintProvider(Protocol):
    is_remote: bool

    def generate_story_blueprint(self, request: Mapping[str, Any]) -> Mapping[str, Any] | str:
        """Return a JSON story blueprint; this call may contact a configured model."""
        ...


STORY_SYSTEM_INSTRUCTIONS = """You are the narrative architect inside a professional film editor.
Design a compelling, truthful story structure from the user's original brief and
the supplied project inventory and analysis. Return only JSON matching the schema.
Use only supplied asset_id values. Never invent footage, events, visual details,
quotes, facts, or claims of having watched/heard media. Scene boundaries and sample
timestamps are technical evidence, not semantic descriptions. If semantic visual
observations or a transcript are absent, state assumptions and leave asset_id/source
ranges unset rather than guessing. Build a clear opening, development, climax and
ending where appropriate. Every beat must have a narrative purpose, duration, visual
intent, narration intent, sound intent and transition intent. Keep durations coherent.
Do not create or modify a timeline. Every blueprint requires user approval.
"""

STORY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["story_id", "original_prompt", "logline", "audience_promise",
                 "emotional_arc", "estimated_duration_seconds", "acts",
                 "requires_user_approval"],
    "properties": {
        "story_id": {"type": "string"},
        "original_prompt": {"type": "string"},
        "logline": {"type": "string"},
        "audience_promise": {"type": "string"},
        "emotional_arc": {"type": "string"},
        "estimated_duration_seconds": {"type": "number", "exclusiveMinimum": 0},
        "acts": {"type": "array", "minItems": 1, "maxItems": 8, "items": {
            "type": "object",
            "required": ["act_id", "act_type", "title", "dramatic_question", "beats"],
            "properties": {
                "act_id": {"type": "string"},
                "act_type": {"enum": sorted(ACT_TYPES)},
                "title": {"type": "string"},
                "dramatic_question": {"type": "string"},
                "beats": {"type": "array", "minItems": 1, "maxItems": 30, "items": {
                    "type": "object",
                    "required": ["beat_id", "sequence", "beat_type", "title", "purpose",
                                 "target_duration_seconds", "visual_intent",
                                 "narration_intent", "sound_intent", "transition_intent"],
                    "properties": {
                        "beat_id": {"type": "string"},
                        "sequence": {"type": "integer", "minimum": 0},
                        "beat_type": {"enum": sorted(BEAT_TYPES)},
                        "title": {"type": "string"},
                        "purpose": {"type": "string"},
                        "target_duration_seconds": {"type": "number", "exclusiveMinimum": 0},
                        "asset_id": {"type": ["string", "null"]},
                        "source_in_seconds": {"type": ["number", "null"]},
                        "source_out_seconds": {"type": ["number", "null"]},
                        "visual_intent": {"type": "string"},
                        "narration_intent": {"type": "string"},
                        "sound_intent": {"type": "string"},
                        "transition_intent": {"enum": sorted(TRANSITION_INTENTS)},
                    },
                    "additionalProperties": False,
                }},
            },
            "additionalProperties": False,
        }},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "format_version": {"type": "integer"},
        "requires_user_approval": {"const": True},
    },
    "additionalProperties": False,
}


def build_story_request(
    prompt: str,
    context: ProjectContext,
    media_analysis: MediaAnalysisReport | None = None,
) -> dict[str, Any]:
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20_000:
        raise EditPlanError("A non-empty story prompt of at most 20,000 characters is required.")
    inventory = []
    for item in context.assets:
        if item.exists:
            inventory.append({
                "asset_id": item.asset.asset_id,
                "media_type": item.asset.media_type,
                "duration_seconds": item.duration_seconds,
                "width": item.width,
                "height": item.height,
                "has_audio": item.asset.has_audio,
                "warning": item.warning,
            })
    return {
        "system_instructions": STORY_SYSTEM_INSTRUCTIONS,
        "response_schema": STORY_SCHEMA,
        "original_prompt": prompt.strip(),
        "project": dict(context.project),
        "assets": inventory,
        "media_analysis": media_analysis.to_dict() if media_analysis is not None else None,
        "context_warnings": list(context.warnings),
        "privacy": {
            "media_bytes_included": False,
            "local_paths_included": False,
            "remote_analysis_performed": False,
        },
    }


def story_blueprint_from_dict(data: Mapping[str, Any]) -> StoryBlueprint:
    if not isinstance(data, Mapping):
        raise EditPlanError("Story blueprint must be a JSON object.")
    try:
        acts = []
        for raw_act in data["acts"]:
            if not isinstance(raw_act, Mapping):
                raise EditPlanError("Every story act must be an object.")
            beats = tuple(StoryBeat(**dict(raw_beat)) for raw_beat in raw_act["beats"])
            acts.append(StoryAct(
                act_id=raw_act["act_id"], act_type=raw_act["act_type"],
                title=raw_act["title"], dramatic_question=raw_act["dramatic_question"],
                beats=beats,
            ))
        return StoryBlueprint(
            story_id=data["story_id"], original_prompt=data["original_prompt"],
            logline=data["logline"], audience_promise=data["audience_promise"],
            emotional_arc=data["emotional_arc"],
            estimated_duration_seconds=data["estimated_duration_seconds"],
            acts=tuple(acts),
            assumptions=tuple(data.get("assumptions", ())),
            warnings=tuple(data.get("warnings", ())),
            format_version=data.get("format_version", STORY_FORMAT_VERSION),
            requires_user_approval=data.get("requires_user_approval", True),
        )
    except EditPlanError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise EditPlanError(f"Malformed story blueprint: {exc}") from exc


def request_story_blueprint(
    prompt: str,
    context: ProjectContext,
    provider: StoryBlueprintProvider,
    *,
    media_analysis: MediaAnalysisReport | None = None,
    allow_cloud_planning: bool = False,
) -> StoryBlueprint:
    if provider is None or not callable(getattr(provider, "generate_story_blueprint", None)):
        raise EditPlanError("A configured story-blueprint provider is required.")
    is_remote = getattr(provider, "is_remote", True)
    if not isinstance(is_remote, bool):
        raise EditPlanError("Story provider is_remote must be an explicit boolean.")
    if is_remote and allow_cloud_planning is not True:
        raise EditPlanError("Cloud AI story planning requires explicit user permission.")
    request = build_story_request(prompt, context, media_analysis)
    raw = provider.generate_story_blueprint(request)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw.strip())
        except json.JSONDecodeError as exc:
            raise EditPlanError(f"Story provider returned invalid JSON: {exc.msg}") from exc
    if not isinstance(raw, Mapping):
        raise EditPlanError("Story provider must return a JSON object.")
    blueprint = story_blueprint_from_dict(raw)
    if blueprint.original_prompt.strip() != prompt.strip():
        raise EditPlanError("Story provider changed the original user prompt.")
    blueprint.validate(context)
    return blueprint
