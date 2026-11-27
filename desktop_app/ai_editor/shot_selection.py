"""Evidence-aware shot selection for narrative beats.

Selection is deterministic and reviewable. Technical metadata can rank usable
ranges, while semantic relevance is scored only from explicit visual
observations supplied by a real analyzer. This module never decodes, uploads,
or modifies media and never applies edits to a timeline.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import re
from typing import Mapping, Sequence

from ai_editor.contracts import EditPlanError
from ai_editor.media_analysis import MediaAnalysisReport
from ai_editor.narrative import StoryBeat, StoryBlueprint
from ai_editor.project_context import ProjectContext


@dataclass(frozen=True)
class VisualObservation:
    asset_id: str
    timestamp_seconds: float
    description: str
    quality_score: float | None = None


@dataclass(frozen=True)
class ShotCandidate:
    candidate_id: str
    asset_id: str
    media_type: str
    source_in_seconds: float
    source_out_seconds: float
    duration_seconds: float
    width: int
    height: int
    semantic_relevance: float | None
    duration_fit: float
    resolution_score: float
    quality_score: float | None
    total_score: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class BeatShotDecision:
    beat_id: str
    candidate_id: str | None
    confidence: str
    score: float | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ShotSelectionReport:
    blueprint: StoryBlueprint
    decisions: tuple[BeatShotDecision, ...]
    candidates_considered: int
    warnings: tuple[str, ...]


def _tokens(value: str) -> set[str]:
    return {
        token.casefold() for token in re.findall(r"[\w]{3,}", value, flags=re.UNICODE)
        if token.casefold() not in {
            "the", "and", "for", "with", "from", "that", "this", "into",
            "about", "your", "their", "visual", "image", "shot", "scene",
        }
    }


def _overlap(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _candidate_windows(
    item,
    analysis,
    target_duration: float,
) -> list[tuple[float, float]]:
    if item.asset.media_type == "image":
        return [(0.0, target_duration)]
    duration = item.duration_seconds
    if duration is None or duration <= 0:
        return []
    boundaries = [0.0]
    boundaries.extend(
        t for t in (analysis.scene_boundaries_seconds if analysis else ())
        if math.isfinite(t) and 0 < t < duration
    )
    boundaries.append(duration)
    boundaries = sorted(set(boundaries))
    windows: list[tuple[float, float]] = []
    for start, end in zip(boundaries, boundaries[1:]):
        if end - start + 1e-6 < target_duration:
            continue
        # Trim long shots to the target duration; center the source range so
        # the selector does not systematically favor the beginning of a shot.
        available = end - start
        offset = max(0.0, (available - target_duration) / 2.0)
        windows.append((start + offset, start + offset + target_duration))
    return windows


def select_shots_for_story(
    story: StoryBlueprint,
    context: ProjectContext,
    media_analysis: MediaAnalysisReport,
    *,
    observations: Sequence[VisualObservation] = (),
    allow_asset_reuse: bool = False,
) -> ShotSelectionReport:
    """Suggest source ranges for unassigned beats; preserve existing assignments."""
    story.validate(context)
    if not isinstance(allow_asset_reuse, bool):
        raise EditPlanError("allow_asset_reuse must be a boolean.")
    analysis_by_asset = {item.asset_id: item for item in media_analysis.assets}
    assets = [
        item for item in context.assets
        if item.exists and item.warning is None
        and item.asset.media_type in {"video", "image"}
    ]
    clean_observations: list[VisualObservation] = []
    known_ids = {item.asset.asset_id for item in assets}
    for observation in observations:
        if observation.asset_id not in known_ids:
            raise EditPlanError("Visual observation references an unknown or unavailable asset.")
        if not isinstance(observation.description, str) or not observation.description.strip():
            raise EditPlanError("Visual observation descriptions must be non-empty.")
        if isinstance(observation.timestamp_seconds, bool) or not isinstance(
            observation.timestamp_seconds, (int, float)
        ) or not math.isfinite(float(observation.timestamp_seconds)) or observation.timestamp_seconds < 0:
            raise EditPlanError("Visual observation timestamps must be finite and non-negative.")
        if observation.quality_score is not None and (
            isinstance(observation.quality_score, bool)
            or not isinstance(observation.quality_score, (int, float))
            or not math.isfinite(float(observation.quality_score))
            or not 0.0 <= float(observation.quality_score) <= 1.0
        ):
            raise EditPlanError("Visual quality scores must be between 0 and 1.")
        clean_observations.append(observation)

    selected_assets: set[str] = {
        beat.asset_id for beat in story.beats if beat.asset_id is not None
    }
    updated_beats: list[StoryBeat] = []
    decisions: list[BeatShotDecision] = []
    warnings: list[str] = []
    candidate_count = 0

    for beat in story.beats:
        if beat.asset_id is not None:
            updated_beats.append(beat)
            decisions.append(BeatShotDecision(
                beat.beat_id, None, "preserved", None,
                ("Existing source assignment was preserved.",),
            ))
            continue

        target = beat.target_duration_seconds
        ranked: list[ShotCandidate] = []
        for item in assets:
            if not allow_asset_reuse and item.asset.asset_id in selected_assets:
                continue
            analysis = analysis_by_asset.get(item.asset.asset_id)
            for index, (start, end) in enumerate(
                _candidate_windows(item, analysis, target)
            ):
                duration = end - start
                duration_fit = max(0.0, 1.0 - abs(duration - target) / max(target, 0.001))
                width = int(item.width or item.asset.width or 0)
                height = int(item.height or item.asset.height or 0)
                pixel_count = width * height
                resolution_score = min(1.0, pixel_count / (1920 * 1080)) if pixel_count else 0.0
                relevant = [
                    obs for obs in clean_observations
                    if obs.asset_id == item.asset.asset_id
                    and (item.asset.media_type == "image" or start <= obs.timestamp_seconds <= end)
                ]
                semantic = None
                quality = None
                evidence: list[str] = [
                    f"Source range {start:.2f}-{end:.2f}s",
                    f"Resolution {width}x{height}" if width and height else "Resolution unavailable",
                ]
                if relevant:
                    descriptions = " ".join(obs.description for obs in relevant)
                    semantic = _overlap(
                        f"{beat.title} {beat.purpose} {beat.visual_intent}", descriptions
                    )
                    scores = [float(obs.quality_score) for obs in relevant if obs.quality_score is not None]
                    quality = sum(scores) / len(scores) if scores else None
                    evidence.append(f"Semantic match from {len(relevant)} visual observation(s): {semantic:.2f}")
                    if quality is not None:
                        evidence.append(f"Analyzer-supplied visual quality: {quality:.2f}")
                else:
                    evidence.append("No semantic visual description supplied; relevance is unknown.")

                # Missing semantic/quality evidence is neutral, not fabricated.
                score = (
                    0.55 * (semantic if semantic is not None else 0.5)
                    + 0.25 * duration_fit
                    + 0.20 * resolution_score
                )
                if quality is not None:
                    score = 0.85 * score + 0.15 * quality
                ranked.append(ShotCandidate(
                    candidate_id=f"{item.asset.asset_id}-{index:04d}",
                    asset_id=item.asset.asset_id,
                    media_type=item.asset.media_type,
                    source_in_seconds=start,
                    source_out_seconds=end,
                    duration_seconds=duration,
                    width=width,
                    height=height,
                    semantic_relevance=semantic,
                    duration_fit=duration_fit,
                    resolution_score=resolution_score,
                    quality_score=quality,
                    total_score=score,
                    evidence=tuple(evidence),
                ))
        candidate_count += len(ranked)
        ranked.sort(key=lambda candidate: (
            candidate.total_score,
            candidate.semantic_relevance if candidate.semantic_relevance is not None else -1.0,
            candidate.resolution_score,
        ), reverse=True)

        if not ranked:
            warnings.append(
                f"{beat.beat_id}: no source range can satisfy the requested duration; left unassigned."
            )
            updated_beats.append(beat)
            decisions.append(BeatShotDecision(
                beat.beat_id, None, "unassigned", None,
                ("No technically eligible source range was found.",),
            ))
            continue

        best = ranked[0]
        if best.semantic_relevance is None:
            confidence = "technical_only"
        elif best.semantic_relevance >= 0.35 and best.total_score >= 0.65:
            confidence = "high"
        elif best.semantic_relevance >= 0.15:
            confidence = "medium"
        else:
            confidence = "low"
        updated_beats.append(replace(
            beat,
            asset_id=best.asset_id,
            source_in_seconds=best.source_in_seconds if best.media_type == "video" else None,
            source_out_seconds=best.source_out_seconds if best.media_type == "video" else None,
        ))
        if not allow_asset_reuse:
            selected_assets.add(best.asset_id)
        decisions.append(BeatShotDecision(
            beat.beat_id, best.candidate_id, confidence,
            best.total_score, best.evidence,
        ))
        if confidence in {"technical_only", "low"}:
            warnings.append(
                f"{beat.beat_id}: selected source needs human review; semantic confidence is {confidence}."
            )

    acts = []
    beat_iter = iter(updated_beats)
    for act in story.acts:
        acts.append(replace(act, beats=tuple(next(beat_iter) for _ in act.beats)))
    updated_story = replace(story, acts=tuple(acts))
    updated_story.validate(context)
    return ShotSelectionReport(
        blueprint=updated_story,
        decisions=tuple(decisions),
        candidates_considered=candidate_count,
        warnings=tuple(warnings),
    )
