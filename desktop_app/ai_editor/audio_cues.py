"""Frame-accurate editorial cue extraction from measured local audio silence.

This module creates review markers only. It does not claim speech transcription,
music beat detection, semantic audio understanding, or automatic synchronization.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from ai_editor.contracts import EditPlanError
from ai_editor.media_analysis import AudioSummary
from ai_editor.audio_energy import AudioEnergyAnalysis


@dataclass(frozen=True)
class AudioCue:
    start_frame: int
    end_frame: int
    duration_frames: int
    cue_type: str
    confidence: str
    reason: str


@dataclass(frozen=True)
class AudioCueMap:
    fps: int
    media_duration_frames: int
    cues: tuple[AudioCue, ...]
    warnings: tuple[str, ...]
    requires_user_review: bool = True


def build_audio_cue_map(
    audio: AudioSummary,
    *,
    media_duration_seconds: float,
    fps: int,
    minimum_pause_seconds: float = 0.35,
    edge_window_seconds: float = 1.0,
    energy_analysis: AudioEnergyAnalysis | None = None,
) -> AudioCueMap:
    """Convert measured silence intervals into timeline review markers."""
    if not isinstance(audio, AudioSummary):
        raise EditPlanError("A measured AudioSummary is required.")
    for name, value in (("media_duration_seconds", media_duration_seconds),
                        ("minimum_pause_seconds", minimum_pause_seconds),
                        ("edge_window_seconds", edge_window_seconds)):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            raise EditPlanError(f"{name} must be a non-negative finite number.")
    if (media_duration_seconds <= 0 or isinstance(fps, bool)
            or not isinstance(fps, int) or fps < 1):
        raise EditPlanError("A positive media duration and integer frame rate are required.")
    if minimum_pause_seconds > 10 or edge_window_seconds > 5:
        raise EditPlanError("Audio cue thresholds exceed safe limits.")

    if energy_analysis is not None and not isinstance(energy_analysis, AudioEnergyAnalysis):
        raise EditPlanError("Energy analysis must be a measured AudioEnergyAnalysis.")
    total_frames = round(media_duration_seconds * fps)
    cues: list[AudioCue] = []
    warnings: list[str] = []
    previous_end = 0

    for raw_start, raw_end in audio.silence_intervals:
        if (isinstance(raw_start, bool) or isinstance(raw_end, bool)
                or not isinstance(raw_start, (int, float))
                or not isinstance(raw_end, (int, float))
                or not math.isfinite(raw_start) or not math.isfinite(raw_end)):
            warnings.append("An invalid silence interval was ignored.")
            continue
        if raw_end <= raw_start or raw_start < 0 or raw_end > media_duration_seconds + 0.05:
            warnings.append("An out-of-range silence interval was ignored.")
            continue
        start = max(0, min(total_frames, round(raw_start * fps)))
        end = max(0, min(total_frames, round(raw_end * fps)))
        if start < previous_end:
            warnings.append("An overlapping silence interval was ignored.")
            continue
        previous_end = end
        if end - start < round(minimum_pause_seconds * fps):
            continue

        duration = end - start
        if start <= round(edge_window_seconds * fps):
            cue_type = "opening_silence"
            reason = "Measured silence near the beginning; review the opening lead-in."
        elif total_frames - end <= round(edge_window_seconds * fps):
            cue_type = "ending_silence"
            reason = "Measured silence near the end; review the ending tail."
        else:
            cue_type = "pause"
            reason = "Measured silence may provide a natural narration or edit point."

        cues.append(AudioCue(
            start_frame=start,
            end_frame=end,
            duration_frames=duration,
            cue_type=cue_type,
            confidence="measured_silence",
            reason=reason,
        ))

    if energy_analysis is not None:
        for timestamp in energy_analysis.transient_candidates_seconds:
            if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                    or not math.isfinite(timestamp) or timestamp < 0
                    or timestamp > media_duration_seconds):
                warnings.append("An invalid transient candidate was ignored.")
                continue
            frame = min(total_frames, max(0, round(timestamp * fps)))
            cues.append(AudioCue(
                start_frame=frame,
                end_frame=min(total_frames, frame + 1),
                duration_frames=1 if frame < total_frames else 0,
                cue_type="transient_candidate",
                confidence="energy_change_candidate",
                reason="RMS energy change only; not a verified beat. Review against the soundtrack.",
            ))
        warnings.extend(energy_analysis.warnings)
        warnings.append("Energy-change markers are review hints and are not beat-synchronized edits.")

    cues.sort(key=lambda cue: (cue.start_frame, cue.end_frame, cue.cue_type))

    if audio.mean_db is None or audio.peak_db is None:
        warnings.append("Aggregate audio level is unavailable; loudness decisions were not inferred.")
    else:
        warnings.append("Aggregate peak/mean levels are not a music beat or speech activity detector.")

    return AudioCueMap(
        fps=fps,
        media_duration_frames=total_frames,
        cues=tuple(cues),
        warnings=tuple(warnings),
    )
