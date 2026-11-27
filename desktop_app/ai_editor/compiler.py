"""Compile an approved narrative blueprint into a non-mutating edit-plan draft.

This compiler creates validated add-clip and supported transition operations.
It never edits a TimelineProject, renders media, or applies the resulting plan.
"""
from __future__ import annotations

import hashlib

from ai_editor.contracts import (
    EditOperation, EditPlan, EditPlanError, ProjectBrief,
)
from ai_editor.narrative import StoryBlueprint
from ai_editor.project_context import ProjectContext


def compile_story_to_edit_plan(
    story: StoryBlueprint,
    context: ProjectContext,
) -> EditPlan:
    """Turn asset-backed story beats into a reviewable timeline plan.

    Beats without a selected source asset remain intentional placeholders and
    are reported as warnings. Video/image sources go to V1; audio sources go
    to A1. No source file is changed and no timeline mutation occurs.
    """
    story.validate(context)
    fps = context.project.get("fps")
    if isinstance(fps, bool) or not isinstance(fps, int) or fps < 1:
        raise EditPlanError("Project frame rate is unavailable or invalid.")

    assets = {
        item.asset.asset_id: item
        for item in context.assets if item.exists
    }
    operations: list[EditOperation] = []
    warnings = list(story.warnings)
    cursor_frame = 0
    last_visual_clip: tuple[str, int, int, str, int] | None = None
    story_digest = hashlib.sha256(story.story_id.encode("utf-8")).hexdigest()[:10]

    for beat in story.beats:
        target_frames = max(1, round(beat.target_duration_seconds * fps))
        if beat.asset_id is None:
            warnings.append(
                f"{beat.beat_id}: no source asset selected; left as a timeline placeholder."
            )
            cursor_frame += target_frames
            last_visual_clip = None
            continue

        item = assets[beat.asset_id]
        if item.warning is not None:
            warnings.append(
                f"{beat.beat_id}: source metadata is unreliable; beat left as a placeholder."
            )
            cursor_frame += target_frames
            last_visual_clip = None
            continue
        media_type = item.asset.media_type
        if media_type not in {"video", "image", "audio"}:
            warnings.append(
                f"{beat.beat_id}: unsupported source type {media_type}; skipped."
            )
            cursor_frame += target_frames
            if media_type not in {"audio"}:
                last_visual_clip = None
            continue

        if media_type == "image":
            source_in = 0
            duration_frames = target_frames
            track = "V1"
        else:
            source_in = round(float(beat.source_in_seconds) * fps)
            source_out = round(float(beat.source_out_seconds) * fps)
            duration_frames = source_out - source_in
            if duration_frames < 1:
                raise EditPlanError(f"{beat.beat_id}: source range is shorter than one frame.")
            if abs(duration_frames - target_frames) > 1:
                raise EditPlanError(
                    f"{beat.beat_id}: source range and target beat duration differ; "
                    "time-remapping must be designed before compilation."
                )
            track = "A1" if media_type == "audio" else "V1"

        planned_clip_id = f"ai-{story_digest}-{beat.sequence:04d}"
        params = {
            "clip_id": planned_clip_id,
            "asset_id": beat.asset_id,
            "track": track,
            "start_frame": cursor_frame,
            "source_in": source_in,
            "duration_frames": duration_frames,
        }
        operations.append(EditOperation(
            operation_id=f"beat-{beat.sequence:04d}-clip",
            kind="add_clip",
            parameters=params,
            rationale=f"{beat.title}: {beat.purpose}",
        ))
        if media_type == "video":
            transition_frames = min(round(0.5 * fps), duration_frames)
            if beat.transition_intent in {"dissolve", "fade", "motivated_transition"} and last_visual_clip is not None:
                previous_id, previous_end, previous_duration, previous_type, _previous_source_in = last_visual_clip
                transition_allowed = (
                    previous_end == cursor_frame
                    and transition_frames > 0
                    and transition_frames <= previous_duration
                    and (media_type == "image" or source_in >= transition_frames)
                )
                if transition_allowed:
                    operations.append(EditOperation(
                        operation_id=f"beat-{beat.sequence:04d}-transition",
                        kind="set_transition",
                        parameters={
                            "clip_id": planned_clip_id,
                            "duration_frames": transition_frames,
                            "transition_type": "dissolve",
                        },
                        rationale=f"Apply approved {beat.transition_intent} intent at the incoming visual cut.",
                    ))
                else:
                    warnings.append(
                        f"{beat.beat_id}: dissolve not compiled because adjacent clips or source handles do not support it; hard cut retained."
                    )
            last_visual_clip = (planned_clip_id, cursor_frame + duration_frames,
                                duration_frames, media_type, source_in)
        else:
            if media_type == "image" and beat.transition_intent in {"dissolve", "fade", "motivated_transition"}:
                warnings.append(
                    f"{beat.beat_id}: image transition intent retained for review; this compiler only emits video cross-dissolves."
                )
            last_visual_clip = None
        cursor_frame += target_frames

    digest = hashlib.sha256(story.story_id.encode("utf-8")).hexdigest()[:12]
    clip_operation_count = sum(operation.kind == "add_clip" for operation in operations)
    transition_operation_count = sum(operation.kind == "set_transition" for operation in operations)
    plan = EditPlan(
        plan_id=f"story-plan-{digest}",
        brief=ProjectBrief(
            prompt=story.original_prompt,
            target_duration_frames=max(1, cursor_frame),
            output_width=context.project.get("width"),
            output_height=context.project.get("height"),
            output_fps=fps,
        ),
        summary=(
            f"{story.logline} Narrative: {story.emotional_arc} "
            f"Generated {clip_operation_count} source-backed clip(s) and "
            f"{transition_operation_count} supported transition(s); "
            "unassigned beats remain placeholders."
        ),
        operations=tuple(operations),
        assumptions=tuple(story.assumptions),
        warnings=tuple(warnings),
        requires_user_approval=True,
    )
    valid_assets = tuple(
        item.asset for item in context.assets
        if item.exists
    )
    plan.validate(valid_assets, set())
    return plan
