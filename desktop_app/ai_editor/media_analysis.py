"""Unified, privacy-local media diagnostics for AI editorial planning.

This pipeline combines shot-boundary detection, bounded visual sampling, and
audio diagnostics. It never invokes a model or transmits media. Sampled JPEG
bytes are discarded after their timestamps and dimensions are recorded.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

from ai_editor.project_context import ProjectContext


@dataclass(frozen=True)
class VisualSampleSummary:
    timestamp_seconds: float
    width: int
    height: int


@dataclass(frozen=True)
class AudioSummary:
    silence_intervals: tuple[tuple[float, float], ...]
    peak_db: float | None
    mean_db: float | None


@dataclass(frozen=True)
class AssetAnalysis:
    asset_id: str
    media_type: str
    scene_boundaries_seconds: tuple[float, ...] = ()
    visual_samples: tuple[VisualSampleSummary, ...] = ()
    audio: AudioSummary | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MediaAnalysisReport:
    schema_version: int
    assets: tuple[AssetAnalysis, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def analyze_project_media(
    context: ProjectContext,
    *,
    visual_sample_count: int = 6,
    max_visual_dimension: int = 768,
    scene_detector: Callable | None = None,
    visual_sampler: Callable | None = None,
    audio_analyzer: Callable | None = None,
) -> MediaAnalysisReport:
    """Run local analysis per asset, isolating failures so one bad file won't abort all.

    Only existing video/audio assets are processed. Images are inventoried by
    project_context and intentionally skipped here. Remote AI analysis is a
    separate, consent-gated layer and is not part of this function.
    """
    if not 1 <= visual_sample_count <= 24:
        raise ValueError("Visual sample count must be between 1 and 24.")
    if not 64 <= max_visual_dimension <= 1280:
        raise ValueError("Maximum visual dimension must be between 64 and 1280.")

    if scene_detector is None:
        from ai_editor.scene_detection import detect_scene_changes
        scene_detector = detect_scene_changes
    if visual_sampler is None:
        from ai_editor.visual_analysis import sample_video_frames
        visual_sampler = sample_video_frames
    if audio_analyzer is None:
        from ai_editor.audio_analysis import analyze_audio
        audio_analyzer = analyze_audio

    results: list[AssetAnalysis] = []
    report_warnings: list[str] = list(context.warnings)
    for item in context.assets:
        asset = item.asset
        warnings: list[str] = []
        scene_times: tuple[float, ...] = ()
        samples: tuple[VisualSampleSummary, ...] = ()
        audio: AudioSummary | None = None

        if not item.exists:
            continue

        if asset.media_type == "video":
            if item.duration_seconds is None or item.duration_seconds <= 0:
                warnings.append("Video duration is unavailable; visual analysis was skipped.")
            else:
                try:
                    detected = scene_detector(asset.path, item.duration_seconds)
                    scene_times = tuple(
                        float(boundary.timestamp_seconds)
                        for boundary in detected.boundaries
                    )
                except Exception as exc:
                    warnings.append(f"Scene detection failed: {exc}")
                try:
                    frames = visual_sampler(
                        asset.path, item.duration_seconds,
                        sample_count=visual_sample_count,
                        max_dimension=max_visual_dimension,
                    )
                    samples = tuple(
                        VisualSampleSummary(
                            float(frame.timestamp_seconds),
                            int(frame.width), int(frame.height),
                        )
                        for frame in frames
                    )
                    # Frame JPEG bytes are deliberately not copied into the report.
                    del frames
                except Exception as exc:
                    warnings.append(f"Visual sampling failed: {exc}")

        if asset.media_type == "audio" or (
            asset.media_type == "video" and asset.has_audio
        ):
            try:
                measured = audio_analyzer(asset.path)
                audio = AudioSummary(
                    silence_intervals=tuple(
                        (float(interval.start_seconds), float(interval.end_seconds))
                        for interval in measured.silence_intervals
                    ),
                    peak_db=measured.peak_db,
                    mean_db=measured.mean_db,
                )
            except Exception as exc:
                warnings.append(f"Audio analysis failed: {exc}")

        if warnings:
            report_warnings.extend(
                f"{asset.asset_id}: {warning}" for warning in warnings
            )
        results.append(AssetAnalysis(
            asset_id=asset.asset_id,
            media_type=asset.media_type,
            scene_boundaries_seconds=scene_times,
            visual_samples=samples,
            audio=audio,
            warnings=tuple(warnings),
        ))

    return MediaAnalysisReport(
        schema_version=1,
        assets=tuple(results),
        warnings=tuple(report_warnings),
    )
