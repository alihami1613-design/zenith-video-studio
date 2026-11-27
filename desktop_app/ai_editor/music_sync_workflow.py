"""Approval-gated orchestration for music-aware story compilation.

This service joins existing local diagnostics and planning modules into one
reviewable draft. It does not mutate a timeline, render, or apply a plan.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_editor.cinematic_edit import CinematicEditDesign, design_cinematic_rhythm
from ai_editor.compiler import compile_story_to_edit_plan
from ai_editor.contracts import EditPlan, EditPlanError
from ai_editor.media_analysis import MediaAnalysisReport, SpectralAudioSummary
from ai_editor.music_sync import MusicSyncDesign, design_music_aware_timing
from ai_editor.narrative import StoryBlueprint
from ai_editor.project_context import ProjectContext


@dataclass(frozen=True)
class MusicAwareEditDraft:
    audio_asset_id: str
    cinematic_design: CinematicEditDesign
    music_sync_design: MusicSyncDesign
    edit_plan: EditPlan
    warnings: tuple[str, ...]
    requires_user_approval: bool = True


def build_music_aware_edit_draft(
    story: StoryBlueprint,
    context: ProjectContext,
    media_analysis: MediaAnalysisReport,
    *,
    audio_asset_id: str,
    story_approved: bool = False,
    shot_selection_approved: bool = False,
    pace_profile: str = "balanced",
) -> MusicAwareEditDraft:
    """Build a real timeline edit-plan draft after explicit editorial approvals.

    The selected audio asset is explicit; no arbitrary soundtrack is chosen.
    If spectral evidence is unavailable or unreliable, narrative timing is
    retained. The resulting EditPlan still requires approval before apply.
    """
    if story_approved is not True or shot_selection_approved is not True:
        raise EditPlanError(
            "Explicit story and shot-selection approvals are required before music-aware compilation."
        )
    if not isinstance(media_analysis, MediaAnalysisReport):
        raise EditPlanError("A valid local media analysis report is required.")
    story.validate(context)

    selected = next(
        (item for item in context.assets if item.asset.asset_id == audio_asset_id),
        None,
    )
    if selected is None or not selected.exists:
        raise EditPlanError("The selected music asset is unavailable in this project.")
    if selected.asset.media_type not in {"audio", "video"}:
        raise EditPlanError("Music sync requires an audio file or a video containing audio.")
    if selected.asset.media_type == "video" and not selected.asset.has_audio:
        raise EditPlanError("The selected video asset has no audio stream.")

    analysis = next(
        (item for item in media_analysis.assets if item.asset_id == audio_asset_id),
        None,
    )
    spectral: SpectralAudioSummary | None = analysis.spectral_audio if analysis else None
    cinematic = design_cinematic_rhythm(
        story, context, pace_profile=pace_profile
    )
    music_sync = design_music_aware_timing(cinematic, spectral)
    plan = compile_story_to_edit_plan(
        story, context,
        cinematic_design=cinematic,
        music_sync_design=music_sync,
    )
    warnings = list(music_sync.warnings)
    if spectral is None:
        warnings.append(
            "No spectral audio analysis was available for the selected asset; the edit uses narrative timing."
        )
    warnings.extend(plan.warnings)
    return MusicAwareEditDraft(
        audio_asset_id=audio_asset_id,
        cinematic_design=cinematic,
        music_sync_design=music_sync,
        edit_plan=plan,
        warnings=tuple(dict.fromkeys(warnings)),
    )
