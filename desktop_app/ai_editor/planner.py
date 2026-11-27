"""Provider-neutral orchestration for turning a brief into a validated edit plan.

This module deliberately does not choose or contact an AI provider. The caller
supplies a provider adapter, making network use explicit and testable. Local
filesystem paths are never included in the planning request.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Protocol

from ai_editor.contracts import EditPlan, EditPlanError, MediaAsset, plan_from_dict
from ai_editor.project_context import ProjectContext, build_project_context
from timeline_model import TimelineProject


class EditPlanProvider(Protocol):
    """Adapter contract implemented by a configured model provider."""

    def generate_edit_plan(self, request: Mapping[str, Any]) -> Mapping[str, Any] | str:
        """Return one JSON object (or JSON text) matching the edit-plan contract."""
        ...


SYSTEM_INSTRUCTIONS = """You are the editorial planning engine for a professional video editor.
Create a coherent, practical edit plan from the user's brief and supplied project
metadata. Return ONLY one JSON object matching the requested schema.
Use only supplied asset_id values and existing clip_id values. Never invent paths,
assets, clip IDs, media facts, or unsupported operations. Use integer frame counts.
Keep all operations non-destructive. Every plan must set requires_user_approval=true.
If information is insufficient, state assumptions and warnings instead of guessing.
Do not claim to have viewed or heard media: this request contains metadata only.
For an edit built from imported assets, use add_clip operations with exact asset IDs.
Respect source duration, track type, project frame rate, target duration, and output
format. Prefer clear story structure, purposeful pacing, restrained transitions,
consistent color, and intelligible audio over excessive effects.
"""

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["plan_id", "brief", "summary", "operations", "requires_user_approval"],
    "properties": {
        "plan_id": {"type": "string"},
        "brief": {"type": "object"},
        "summary": {"type": "string"},
        "operations": {"type": "array", "items": {
            "type": "object",
            "required": ["operation_id", "kind", "parameters"],
            "properties": {
                "operation_id": {"type": "string"},
                "kind": {"enum": ["add_clip", "move_clip", "trim_clip",
                                  "set_clip_grade", "set_clip_volume", "set_transition"]},
                "parameters": {"type": "object"},
                "rationale": {"type": "string"},
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


def build_planning_request(
    brief: str,
    context: ProjectContext,
) -> dict[str, Any]:
    """Build a privacy-minimized provider request from a local project context."""
    if not isinstance(brief, str) or not brief.strip():
        raise EditPlanError("A non-empty editing brief is required.")
    if len(brief) > 20_000:
        raise EditPlanError("Editing brief exceeds the 20,000-character limit.")

    assets = []
    for item in context.assets:
        if not item.exists:
            continue
        asset = item.asset
        assets.append({
            "asset_id": asset.asset_id,
            "media_type": asset.media_type,
            "duration_frames": asset.duration_frames,
            "fps": asset.fps,
            "width": asset.width,
            "height": asset.height,
            "has_audio": asset.has_audio,
            "file_size_bytes": item.file_size_bytes,
            "warning": item.warning,
        })

    # Only editorially relevant timeline metadata is sent; never include paths.
    clips = [{
        "clip_id": clip["clip_id"],
        "asset_id": clip["asset_id"],
        "media_type": clip["media_type"],
        "track": clip["track"],
        "start_frame": clip["start_frame"],
        "end_frame": clip["end_frame"],
        "source_in": clip["source_in"],
        "duration_frames": clip["duration_frames"],
        "has_audio": clip["has_audio"],
        "volume": clip["volume"],
        "color_grade": dict(clip["color_grade"]),
    } for clip in context.timeline_clips]

    return {
        "system_instructions": SYSTEM_INSTRUCTIONS,
        "response_schema": PLAN_SCHEMA,
        "user_brief": brief.strip(),
        "project": dict(context.project),
        "assets": assets,
        "timeline_clips": clips,
        "context_warnings": list(context.warnings),
        "privacy": {
            "media_bytes_included": False,
            "local_paths_included": False,
            "cloud_media_analysis_performed": False,
        },
    }


def _decode_provider_result(result: Mapping[str, Any] | str) -> Mapping[str, Any]:
    if isinstance(result, Mapping):
        return result
    if not isinstance(result, str):
        raise EditPlanError("AI provider must return a JSON object or JSON text.")
    text = result.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EditPlanError(f"AI provider returned invalid JSON: {exc.msg}") from exc
    if not isinstance(decoded, Mapping):
        raise EditPlanError("AI provider response must be a JSON object.")
    return decoded


def request_edit_plan(
    brief: str,
    project: TimelineProject,
    provider: EditPlanProvider,
    media_paths: tuple[str, ...] | list[str] = (),
) -> EditPlan:
    """Ask an explicitly supplied provider for a plan, then validate it locally.

    The provider is responsible for any network transport and credentials. This
    function never performs network access itself and never applies the plan.
    """
    if provider is None or not callable(getattr(provider, "generate_edit_plan", None)):
        raise EditPlanError("A configured edit-plan provider is required.")
    context = build_project_context(project, media_paths)
    request = build_planning_request(brief, context)
    raw = provider.generate_edit_plan(request)
    plan = plan_from_dict(_decode_provider_result(raw))
    assets = tuple(item.asset for item in context.assets if item.exists and item.warning is None)
    plan.validate(assets, {clip.clip_id for clip in project.clips})
    if plan.brief.prompt.strip() != brief.strip():
        raise EditPlanError("Provider changed the original user brief.")
    return plan
