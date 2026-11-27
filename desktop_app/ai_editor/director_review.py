"""Evidence-backed, review-only editorial director diagnostics.

Findings are recommendations, not edits. This module never mutates the
timeline, reads media bytes, uploads assets, or claims semantic understanding.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable

from timeline_model import TimelineProject
from ai_editor.project_context import ProjectContext
from ai_editor.quality_control import run_quality_checks
from ai_editor.narrative import StoryBlueprint
from ai_editor.shot_selection import ShotSelectionReport
from ai_editor.audio_cues import AudioCueMap


PACE_LIMITS = {
    "calm": (0.75, 14.0),
    "balanced": (0.50, 9.0),
    "energetic": (0.35, 6.0),
    "trailer": (0.25, 4.5),
}


@dataclass(frozen=True)
class DirectorFinding:
    finding_id: str
    category: str
    severity: str
    title: str
    evidence: tuple[str, ...]
    recommendation: str
    clip_id: str | None = None
    beat_id: str | None = None
    requires_user_approval: bool = True


@dataclass(frozen=True)
class DirectorReviewReport:
    findings: tuple[DirectorFinding, ...]
    error_count: int
    warning_count: int
    advisory_count: int
    project_fingerprint: tuple[tuple[Any, ...], ...]
    requires_user_review: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fingerprint(project: TimelineProject) -> tuple[tuple[Any, ...], ...]:
    return tuple(sorted((
        clip.clip_id, clip.path, clip.track, clip.start_frame,
        clip.source_in, clip.duration_frames, clip.playback_rate,
        clip.transition_in_frames, clip.transition_in_type,
    ) for clip in project.clips))


def review_is_current(report: DirectorReviewReport, project: TimelineProject) -> bool:
    """Return False when timeline structure changed after the review was made."""
    return isinstance(report, DirectorReviewReport) and report.project_fingerprint == _fingerprint(project)


def review_edit(
    project: TimelineProject,
    context: ProjectContext | None = None,
    *,
    story: StoryBlueprint | None = None,
    shot_selection: ShotSelectionReport | None = None,
    audio_cue_maps: Iterable[AudioCueMap] = (),
    pace_profile: str = "balanced",
) -> DirectorReviewReport:
    """Create a conservative director's review from measured project evidence."""
    if not isinstance(project, TimelineProject):
        raise TypeError("project must be a TimelineProject")
    if pace_profile not in PACE_LIMITS:
        raise ValueError("Unsupported pace profile")
    if context is not None and not isinstance(context, ProjectContext):
        raise TypeError("context must be a ProjectContext")
    if story is not None and not isinstance(story, StoryBlueprint):
        raise TypeError("story must be a StoryBlueprint")
    if shot_selection is not None and not isinstance(shot_selection, ShotSelectionReport):
        raise TypeError("shot_selection must be a ShotSelectionReport")

    findings: list[DirectorFinding] = []

    def add(fid: str, category: str, severity: str, title: str,
            evidence: tuple[str, ...], recommendation: str,
            clip_id: str | None = None, beat_id: str | None = None) -> None:
        findings.append(DirectorFinding(
            fid, category, severity, title, evidence, recommendation,
            clip_id, beat_id, True,
        ))

    # Structural and source-media findings are grounded in the existing QC engine.
    qc = run_quality_checks(project, context)
    for index, issue in enumerate(qc.issues):
        severity = "error" if issue.severity == "error" else "warning"
        add(
            f"qc-{issue.check_id}-{index + 1}", "technical", severity,
            issue.message, (f"Quality-control check: {issue.check_id}",),
            "Resolve this technical issue, then run the review again.",
            clip_id=issue.clip_id,
        )

    # Inspect every video track; gaps and overlaps are measured in frames.
    video_tracks = sorted({clip.track for clip in project.clips
                           if clip.track.startswith("V") and clip.media_type in {"video", "image"}})
    for track in video_tracks:
        clips = sorted((clip for clip in project.clips
                        if clip.track == track and clip.media_type in {"video", "image"}),
                       key=lambda clip: (clip.start_frame, clip.clip_id))
        for previous, current in zip(clips, clips[1:]):
            delta = current.start_frame - previous.end_frame
            if delta > 0:
                add(
                    f"gap-{track}-{previous.clip_id}-{current.clip_id}",
                    "continuity", "warning" if track == "V1" else "advisory",
                    f"Gap on {track} between adjacent clips",
                    (f"{delta} empty frame(s) between {previous.name} and {current.name}.",),
                    "Check whether the gap is intentional; close it or add a deliberate hold/fade if needed.",
                    clip_id=current.clip_id,
                )
            elif delta < 0:
                add(
                    f"overlap-{track}-{previous.clip_id}-{current.clip_id}",
                    "continuity", "advisory",
                    f"Overlapping clips on {track}",
                    (f"{abs(delta)} frame(s) overlap between {previous.name} and {current.name}.",),
                    "Verify that this overlap is an intentional transition or compositing layer.",
                    clip_id=current.clip_id,
                )

    min_seconds, max_seconds = PACE_LIMITS[pace_profile]
    for clip in project.clips:
        if clip.track.startswith("V") and clip.media_type in {"video", "image"}:
            seconds = clip.duration_frames / max(1, project.fps)
            if seconds < min_seconds:
                add(
                    f"short-shot-{clip.clip_id}", "pacing", "advisory",
                    "Very short shot for the selected pace profile",
                    (f"{seconds:.2f}s shot; {pace_profile} profile advisory floor is {min_seconds:.2f}s.",),
                    "Check readability and whether the cut feels intentionally fast; do not lengthen automatically.",
                    clip_id=clip.clip_id,
                )
            elif seconds > max_seconds:
                add(
                    f"long-shot-{clip.clip_id}", "pacing", "advisory",
                    "Long shot for the selected pace profile",
                    (f"{seconds:.2f}s shot; {pace_profile} profile advisory ceiling is {max_seconds:.2f}s.",),
                    "Check whether the image sustains audience attention or needs a motivated cutaway; long takes may be intentional.",
                    clip_id=clip.clip_id,
                )

    if story is not None:
        story.validate(context) if context is not None else None
        selected = shot_selection.blueprint if shot_selection is not None else story
        assigned = {beat.beat_id: beat for beat in selected.beats}
        for beat in story.beats:
            current = assigned.get(beat.beat_id, beat)
            if current.asset_id is None:
                add(
                    f"unassigned-beat-{beat.beat_id}", "story", "warning",
                    f"Story beat has no assigned visual: {beat.title}",
                    (f"Beat {beat.sequence + 1}: {beat.purpose}",),
                    "Choose suitable footage or deliberately mark this beat for titles, graphics, or narration-led coverage.",
                    beat_id=beat.beat_id,
                )
        if shot_selection is not None:
            for decision in shot_selection.decisions:
                if decision.confidence in {"technical_only", "low"}:
                    add(
                        f"shot-confidence-{decision.beat_id}", "story", "advisory",
                        "Shot assignment needs a human relevance check",
                        tuple(decision.reasons) or (f"Selection confidence: {decision.confidence}",),
                        "Watch the selected source range and confirm it actually communicates this beat; technical ranking is not semantic understanding.",
                        beat_id=decision.beat_id,
                    )

    cue_maps = tuple(audio_cue_maps)
    for index, cue_map in enumerate(cue_maps):
        if not isinstance(cue_map, AudioCueMap):
            raise TypeError("audio_cue_maps must contain AudioCueMap values")
        for cue_index, cue in enumerate(cue_map.cues):
            if cue.cue_type in {"opening_silence", "ending_silence", "pause"}:
                add(
                    f"audio-pause-{index}-{cue_index}", "audio", "advisory",
                    "Measured silence needs editorial listening",
                    (f"{cue.cue_type}: frames {cue.start_frame}-{cue.end_frame}.", cue.reason),
                    "Listen in context and decide whether to preserve the pause, tighten it, or use it as a deliberate beat.",
                )

    errors = sum(item.severity == "error" for item in findings)
    warnings = sum(item.severity == "warning" for item in findings)
    advisories = sum(item.severity == "advisory" for item in findings)
    return DirectorReviewReport(
        tuple(findings), errors, warnings, advisories, _fingerprint(project), True,
    )
