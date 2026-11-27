"""Reviewable music-aware timing suggestions for narrative edits.

This module aligns selected story-beat boundaries to measured spectral pulse
candidates when confidence and timing evidence are sufficient. It never changes
a timeline or media file; every suggestion requires explicit user approval.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_editor.contracts import EditPlanError
from ai_editor.cinematic_edit import CinematicEditDesign
from ai_editor.media_analysis import SpectralAudioSummary


@dataclass(frozen=True)
class MusicSyncDecision:
    beat_id: str
    sequence: int
    start_frame: int
    duration_frames: int
    original_duration_frames: int
    boundary_frame: int | None
    matched_pulse_seconds: float | None
    adjustment_frames: int
    confidence: str
    reason: str


@dataclass(frozen=True)
class MusicSyncDesign:
    fps: int
    total_frames: int
    estimated_bpm: float | None
    tempo_confidence: float
    decisions: tuple[MusicSyncDecision, ...]
    warnings: tuple[str, ...]
    requires_user_approval: bool = True


def design_music_aware_timing(
    cinematic_design: CinematicEditDesign,
    spectral_audio: SpectralAudioSummary | None,
    *,
    minimum_tempo_confidence: float = 0.30,
    snap_tolerance_seconds: float = 0.18,
    minimum_shot_seconds: float = 1.5,
    maximum_shot_seconds: float = 12.0,
    maximum_adjustment_seconds: float = 0.35,
) -> MusicSyncDesign:
    """Suggest small boundary shifts toward measured pulses without editing.

    Pulse evidence is used only when a tempo estimate and confidence are
    available. Story order and total sequence duration are preserved. The
    final beat is never shortened or extended by sync logic.
    """
    if not isinstance(cinematic_design, CinematicEditDesign):
        raise EditPlanError("A valid cinematic edit design is required.")
    if not cinematic_design.requires_user_approval:
        raise EditPlanError("Music sync requires an approval-gated cinematic design.")
    if isinstance(cinematic_design.fps, bool) or not isinstance(cinematic_design.fps, int) or cinematic_design.fps < 1:
        raise EditPlanError("A valid project frame rate is required.")
    for name, value, upper in (
        ("minimum_tempo_confidence", minimum_tempo_confidence, 1.0),
        ("snap_tolerance_seconds", snap_tolerance_seconds, 1.0),
        ("minimum_shot_seconds", minimum_shot_seconds, 30.0),
        ("maximum_shot_seconds", maximum_shot_seconds, 60.0),
        ("maximum_adjustment_seconds", maximum_adjustment_seconds, 2.0),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= upper:
            raise EditPlanError(f"{name} is outside its supported range.")
    if minimum_shot_seconds <= 0 or maximum_shot_seconds < minimum_shot_seconds:
        raise EditPlanError("Shot duration bounds are inconsistent.")
    if spectral_audio is not None and not isinstance(spectral_audio, SpectralAudioSummary):
        raise EditPlanError("Spectral audio must be a measured SpectralAudioSummary.")

    fps = cinematic_design.fps
    original = cinematic_design.decisions
    if not original:
        return MusicSyncDesign(fps, cinematic_design.total_frames, None, 0.0, (), 
                               ("No story beats are available for music alignment.",))
    cursor = 0
    for decision in original:
        if decision.start_frame != cursor or decision.duration_frames < 1:
            raise EditPlanError("Cinematic beat timings must be contiguous and positive.")
        cursor += decision.duration_frames
    if cursor != cinematic_design.total_frames:
        raise EditPlanError("Cinematic design total duration does not match its beats.")

    warnings = [
        "Music sync uses estimated spectral periodicity, not verified musical downbeats.",
        "Suggested timing changes are review-only; no timeline or source media was modified.",
        "Half-time/double-time ambiguity may affect pulse placement.",
    ]
    usable = (
        spectral_audio is not None
        and spectral_audio.estimated_bpm is not None
        and isinstance(spectral_audio.tempo_confidence, (int, float))
        and not isinstance(spectral_audio.tempo_confidence, bool)
        and minimum_tempo_confidence <= spectral_audio.tempo_confidence <= 1.0
    )
    pulses: list[float] = []
    if usable:
        for raw in spectral_audio.pulse_candidates_seconds:
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            value = float(raw)
            if 0 <= value < cinematic_design.total_frames / fps:
                pulses.append(value)
        pulses = sorted(set(pulses))
        usable = bool(pulses)
    if not usable:
        warnings.append("No sufficiently reliable spectral pulse grid was available; story timing is unchanged.")

    min_frames = max(1, round(minimum_shot_seconds * fps))
    max_frames = max(min_frames, round(maximum_shot_seconds * fps))
    tolerance = round(snap_tolerance_seconds * fps)
    max_adjust = round(maximum_adjustment_seconds * fps)
    adjusted_boundaries: list[tuple[int, float | None, int]] = []
    original_boundary = 0
    for left, right in zip(original, original[1:]):
        original_boundary += left.duration_frames
        chosen = original_boundary
        matched = None
        delta = 0
        if (usable and tolerance > 0 and max_adjust > 0
                and right.rhythm != "hold"):
            candidates = []
            for pulse in pulses:
                pulse_frame = round(pulse * fps)
                shift = pulse_frame - original_boundary
                if abs(shift) > min(tolerance, max_adjust):
                    continue
                left_duration = pulse_frame - left.start_frame
                right_duration = right.start_frame + right.duration_frames - pulse_frame
                if min_frames <= left_duration <= max_frames and min_frames <= right_duration <= max_frames:
                    candidates.append((abs(shift), pulse_frame, pulse))
            if candidates:
                _, chosen, matched = min(candidates, key=lambda item: (item[0], item[1]))
                delta = chosen - original_boundary
        adjusted_boundaries.append((chosen, matched, delta))

    decisions: list[MusicSyncDecision] = []
    current_start = 0
    for index, beat in enumerate(original):
        if index < len(adjusted_boundaries):
            boundary, pulse, delta = adjusted_boundaries[index]
            duration = boundary - current_start
        else:
            boundary, pulse, delta = None, None, 0
            duration = cinematic_design.total_frames - current_start
        if duration < 1:
            raise EditPlanError("Music alignment produced a non-positive shot duration.")
        if pulse is None:
            confidence = "unchanged"
            reason = "Narrative timing retained; no safe nearby pulse match was found."
        else:
            confidence = "candidate"
            reason = (
                f"Boundary moved {delta:+d} frame(s) toward a measured spectral pulse; "
                "verify the musical accent and narrative beat."
            )
        decisions.append(MusicSyncDecision(
            beat_id=beat.beat_id,
            sequence=beat.sequence,
            start_frame=current_start,
            duration_frames=duration,
            original_duration_frames=beat.duration_frames,
            boundary_frame=boundary,
            matched_pulse_seconds=pulse,
            adjustment_frames=delta,
            confidence=confidence,
            reason=reason,
        ))
        current_start += duration

    return MusicSyncDesign(
        fps=fps,
        total_frames=current_start,
        estimated_bpm=spectral_audio.estimated_bpm if usable else None,
        tempo_confidence=float(spectral_audio.tempo_confidence) if usable else 0.0,
        decisions=tuple(decisions),
        warnings=tuple(warnings),
    )
