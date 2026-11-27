"""Tests for reviewable music-aware timing suggestions."""
import unittest

from ai_editor.cinematic_edit import CinematicBeatDecision, CinematicEditDesign
from ai_editor.contracts import EditPlanError
from ai_editor.media_analysis import SpectralAudioSummary
from ai_editor.music_sync import design_music_aware_timing


def design():
    beats = (
        CinematicBeatDecision("beat-1", 0, 0, 120, 4.0, "moderate", "hard_cut", 0, "cut", "", ()),
        CinematicBeatDecision("beat-2", 1, 120, 120, 4.0, "moderate", "hard_cut", 0, "cut", "", ()),
        CinematicBeatDecision("beat-3", 2, 240, 90, 3.0, "moderate", "hard_cut", 0, "cut", "", ()),
    )
    return CinematicEditDesign("balanced", 30, 330, 11.0, beats, ())


def audio(*, bpm=120.0, confidence=0.8, pulses=(4.1, 8.0)):
    return SpectralAudioSummary(8000, 512, 128, bpm, confidence, (), pulses, ())


class MusicSyncTests(unittest.TestCase):
    def test_snaps_boundary_to_nearby_pulse_and_preserves_total_duration(self):
        result = design_music_aware_timing(design(), audio())
        self.assertEqual(result.decisions[0].boundary_frame, 123)
        self.assertEqual(result.decisions[0].adjustment_frames, 3)
        self.assertEqual(result.decisions[0].duration_frames, 123)
        self.assertEqual(result.total_frames, 330)
        self.assertTrue(result.requires_user_approval)

    def test_low_confidence_falls_back_to_story_timing(self):
        result = design_music_aware_timing(design(), audio(confidence=0.1))
        self.assertEqual([d.duration_frames for d in result.decisions], [120, 120, 90])
        self.assertTrue(any("unchanged" in warning for warning in result.warnings))

    def test_missing_audio_keeps_narrative_timing(self):
        result = design_music_aware_timing(design(), None)
        self.assertEqual([d.start_frame for d in result.decisions], [0, 120, 240])
        self.assertEqual(result.estimated_bpm, None)

    def test_final_story_hold_is_not_snapped(self):
        result = design_music_aware_timing(design(), audio(pulses=(4.1, 8.1, 10.9)))
        self.assertEqual(result.decisions[-1].duration_frames, 90)
        self.assertIsNone(result.decisions[-1].matched_pulse_seconds)

    def test_large_shift_and_shot_duration_violation_are_rejected_as_matches(self):
        result = design_music_aware_timing(
            design(), audio(pulses=(4.5,)), maximum_adjustment_seconds=0.1
        )
        self.assertEqual(result.decisions[0].duration_frames, 120)
        self.assertEqual(result.decisions[0].confidence, "unchanged")

    def test_inconsistent_cinematic_timing_is_rejected(self):
        from dataclasses import replace
        bad = replace(design(), total_frames=331)
        with self.assertRaisesRegex(EditPlanError, "total duration"):
            design_music_aware_timing(bad, audio())

    def test_invalid_duration_bounds_are_rejected(self):
        with self.assertRaisesRegex(EditPlanError, "inconsistent"):
            design_music_aware_timing(
                design(), audio(), minimum_shot_seconds=5, maximum_shot_seconds=3
            )

    def test_fps_is_preserved_and_adjustments_are_frame_accurate(self):
        result = design_music_aware_timing(design(), audio(pulses=(4.1,)))
        self.assertEqual(result.fps, 30)
        self.assertEqual(result.decisions[0].start_frame, 0)
        self.assertEqual(result.decisions[1].start_frame, 123)
        self.assertEqual(result.decisions[2].start_frame, 243)


if __ (unittest.main())
