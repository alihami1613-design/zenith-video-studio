"""Safe, transactional application of validated AI edit plans.

Preview always runs against a detached project copy. Committing requires an explicit
approval flag and swaps the staged state into the live project only after every
operation succeeds. Original media files are never modified.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ai_editor.contracts import EditPlan, MediaAsset, EditPlanError
from timeline_model import TimelineProject


@dataclass(frozen=True)
class ExecutionPreview:
    project: TimelineProject
    operation_count: int
    created_clip_ids: tuple[str, ...]
    summary: str


def _clone_project(project: TimelineProject) -> TimelineProject:
    return TimelineProject.from_dict(project.to_dict())


def _apply_operations(project: TimelineProject, plan: EditPlan,
                      assets: Iterable[MediaAsset]) -> tuple[str, ...]:
    asset_map = {asset.asset_id: asset for asset in assets}
    created: list[str] = []
    for operation in plan.operations:
        p = dict(operation.parameters)
        kind = operation.kind
        if kind == "add_clip":
            asset = asset_map[p["asset_id"]]
            track = p.get("track", "V1")
            clip = project.add_clip(
                path=asset.path,
                name=asset.path.replace("\\", "/").rsplit("/", 1)[-1] or asset.asset_id,
                track=track,
                start_frame=p["start_frame"],
                duration_frames=p["duration_frames"],
                media_type=asset.media_type,
                has_audio=asset.has_audio,
                audio_track=p.get("audio_track"),
            )
            clip.source_in = p.get("source_in", 0)
            clip.validate()
            created.append(clip.clip_id)
        elif kind == "move_clip":
            project.move_clip(p["clip_id"], p["start_frame"], p.get("track"))
        elif kind == "trim_clip":
            project.trim_clip(
                p["clip_id"],
                new_start_frame=p.get("new_start_frame"),
                new_end_frame=p.get("new_end_frame"),
            )
        elif kind == "set_clip_grade":
            project.set_clip_color(p["clip_id"], **dict(p["grade"]))
        elif kind == "set_clip_volume":
            project.set_clip_audio(p["clip_id"], volume=p["volume"])
        elif kind == "set_transition":
            project.set_clip_transition(
                p["clip_id"],
                dissolve_in_frames=p["duration_frames"],
                transition_type=p.get("transition_type", "dissolve"),
            )
        else:  # Defensive: contracts should have rejected this already.
            raise EditPlanError(f"Unsupported operation at execution: {kind}")
    return tuple(created)


def preview_edit_plan(project: TimelineProject, plan: EditPlan,
                      assets: Iterable[MediaAsset]) -> ExecutionPreview:
    """Validate and apply a plan to a detached copy; the live project is untouched."""
    assets = tuple(assets)
    plan.validate(assets, {clip.clip_id for clip in project.clips})
    staged = _clone_project(project)
    created = _apply_operations(staged, plan, assets)
    staged.__post_init__()
    return ExecutionPreview(
        project=staged,
        operation_count=len(plan.operations),
        created_clip_ids=created,
        summary=plan.summary,
    )


def apply_edit_plan(project: TimelineProject, plan: EditPlan,
                    assets: Iterable[MediaAsset], *, approved: bool = False) -> ExecutionPreview:
    """Commit atomically after explicit approval; failures leave the live project intact."""
    if approved is not True:
        raise EditPlanError("Explicit user approval is required before applying an AI edit plan.")
    preview = preview_edit_plan(project, plan, assets)
    # Commit only after the entire detached execution and validation succeeded.
    project.__dict__.clear()
    project.__dict__.update(preview.project.__dict__)
    return ExecutionPreview(
        project=project,
        operation_count=preview.operation_count,
        created_clip_ids=preview.created_clip_ids,
        summary=preview.summary,
    )
