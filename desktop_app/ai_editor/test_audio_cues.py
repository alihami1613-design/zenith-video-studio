"""Tests for silence-derived editorial audio cue markers."""
import unittest

from ai_editor.audio_cues import build_audio_cue_map
from ai_editor.contracts import EditPlanError
from ai_editor.media_analysis import AudioSummary


class AudioCueTests(unittest.TestCase):
    def test_converts_silence_to_frame_accurate_review_cues(self):
        audio = AudioSummary(
            silence_intervals=((0.0, 0.8), (4.25, 5.0), (9.2, 10.0)),
            peak_db=-1.0, mean_db=-18.0,
        )
        result = build_audio_cue_map(
            audio, media_duration_seconds=10.0, fps=30,
        )
        self.assertEqual(result.media_duration_frames, 300)
        self.assertEqual(
            [(cue.start_frame, cue.end_frame, cue.cue_type) for cue in result.cues],
            [(0, 24, "opening_silence"),
             (128, 150, "pause"),
             (276, 300, "ending_silence")],
        )
        self.assertTrue(result.requires_user_review)

    def test_ignores_short_invalid_and_out_of_range_intervals(self):
        audio = AudioSummary(
            silence_intervals=((1.0, 1.1), (-1.0, 1.0), (8.0, 12.0)),
            peak_db=None, mean_db=None,
        )
        result = build_audio_cue_map(
            audio, media_duration_seconds=10.0, fps=24,
        )
        self.assertEqual(result.cues, ())
        self.assertTrue(result.warnings)

    def test_rejects_invalid_fps_and_duration(self):
        audio = AudioSummary((), peak_db=-2.0, mean_db=-18.0)
        with self.assertRaises(EditPlanError):
            build_audio_cue_map(audio, media_duration_seconds=10, fps=0)
        with self.assertRaises(EditPlanError):
            build_audio_cue_map(audio, media_duration_seconds=float("nan"), fps=30)

    def test_rejects_wrong_audio_input_type(self):
        with self.assertRaises(EditPlanError):
            build_audio_cue_map({}, media_duration_seconds=10, fps=30)


if __name__ == "__main__":
    unittest.main()
