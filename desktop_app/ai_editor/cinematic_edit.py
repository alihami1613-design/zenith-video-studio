"""Reviewable cinematic rhythm design for an approved story blueprint.

This layer evaluates pacing and transition intent in frame-accurate terms. It
does not reorder footage, alter a timeline, synthesize sound sync, or render.
Transition durations are editorial recommendations until a renderer-backed
adjacency/overlap implementation is available.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_editor.contracts import EditPlanError
from ai_editor.narrative import StoryBlueprint
from ai_editor.project_context import ProjectContext


PACE_PROFILES = frozenset({"calm", "balanced", "energetic", "trailer"})
TRANSITION_MAP = {
    "hard_cut": "hard_cut",
    "match_cut": "hard_cut",  # visual match must be verified by an analyzer/editor
    "dissolve": "dissolve",
    "fade": "dissolve",
    "motivated_transition": "dissolve",
}
PACE_THRESHOLDS = {
    "calm": (8.0, 4.0),
    "balanced": (6.0, 2.5),
    "energetic": (3.5, 1.5),
    "trailer": (2.5, 1.0),
}


@dataclass(frozen=True)
class CinematicBeatDecision:
    beat_id: str
    sequence: int
    start_frame: int
    duration_frames: int
    duration_seconds: float
    rhythm: str
    transition_type: str
    transition_duration_frames: int
    transition_reason: str
    sound_intent: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CinematicEditDesign:
    pace_profile: str
    fps: int
    total_frames: int
    total_duration_seconds: float
    decisions: tuple[CinematicBeatDecision, ...]
    warnings: tuple[str, ...]
    requires_user_approval: bool = True


def design_cinematic_rhythm(
    story: StoryBlueprint,
    context: ProjectContext,
    *,
    pace_profile: str = "balanced",
    transition_duration_seconds: float = 0.5,
) -> CinematicEditDesign:
    """Create a frame-accurate rhythm/transition review sheet without editing."""
    story.validate(context)
    if pace_profile not in PACE_PROFILES:
        raise EditPlanError("Unsupported pace profile.")
    if (
        isinstance(transition_duration_seconds, bool)
        or not isinstance(transition_duration_seconds, (int, float))
        or transition_duration_seconds < 0
        or transition_duration_seconds > 3
    ):
        raise EditPlanError("Transition duration must be between 0 and 3 seconds.")
    fps = context.project.get("fps")
    if isinstance(fps, bool) or not isinstance(fps, int) or fps < 1:
        raise EditPlanError("Project frame rate is unavailable or invalid.")

    slow_threshold, fast_threshold = PACE_THRESHOLDS[pace_profile]
    transition_frames = round(float(transition_duration_seconds) * fps)
    cursor = 0
    decisions = []
    overall_warnings = []

    for beat in story.beats:
        duration_frames = max(1, round(beat.target_duration_seconds * fps))
        actual_seconds = duration_frames / fps
        if actual_seconds >= slow_threshold:
            rhythm = "hold"
        elif actual_seconds <= fast_threshold:
            rhythm = "quick"
        else:
            rhythm = "moderate"

        transition_type = TRANSITION_MAP[beat.transition_intent]
        local_warnings = []
        if beat.transition_intent == "match_cut":
            local_warnings.append(
                "Match cut is an editorial intention; visual similarity is not verified."
            )
        elif beat.transition_intent == "motivated_transition":
            local_warnings.append(
                "Motivated transition is mapped to a dissolve suggestion pending human review."
            )
        if transition_type == "hard_cut":
            suggested_transition_frames = 0
            reason = "A clean cut preserves pace; no overlap is proposed."
        else:
            suggested_transition_frames = transition_frames
            reason = (
                f"{beat.transition_intent} intent translated to a dissolve suggestion; "
                "not yet applied to adjacent clips."
            )
        if rhythm == "quick" and suggested_transition_frames > duration_frames // 2:
            local_warnings.append(
                "Suggested dissolve is long relative to this short beat; consider a hard cut."
            )
        if beat.asset_id is None:
            local_warnings.append("Beat has no selected media; timing remains a placeholder.")
        if beat.sound_intent.strip():
            local_warnings.append(
                "Sound intent is preserved as editorial metadata; no beat-level audio sync was inferred."
            )

        decisions.append(CinematicBeatDecision(
            beat_id=beat.beat_id,
            sequence=beat.sequence,
            start_frame=cursor,
            duration_frames=duration_frames,
            duration_seconds=actual_seconds,
            rhythm=rhythm,
            transition_type=transition_type,
            transition_duration_frames=suggested_transition_frames,
            transition_reason=reason,
            sound_intent=beat.sound_intent,
            warnings=tuple(local_warnings),
        ))
        cursor += duration_frames
        overall_warnings.extend(f"{beat.beat_id}: {warning}" for warning in local_warnings)

    return CinematicEditDesign(
        pace_profile=pace_profile,
        fps=fps,
        total_frames=cursor,
        total_duration_seconds=cursor / fps,
        decisions=tuple(decisions),
        warnings=tuple(overall_warnings),
    )
