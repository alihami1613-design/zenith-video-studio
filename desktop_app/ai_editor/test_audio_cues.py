"""Tests for silence-derived editorial audio cue markers."""
import unittest

from ai_editor.audio_cues import build_audio_cue_map
from ai_editor.contracts import EditPlanError
from ai_editor.media_analysis import AudioSummary, SpectralAudioSummary
from ai_editor.audio_energy import AudioEnergyAnalysis, AudioEnergyPoint
from ai_editor.rhythm_analysis import RhythmAnalysis


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


    def test_adds_energy_change_markers_as_review_only_frame_cues(self):
        audio = AudioSummary((), peak_db=-1.0, mean_db=-18.0)
        energy = AudioEnergyAnalysis(
            sample_rate=4000,
            window_seconds=0.1,
            analyzed_duration_seconds=5.0,
            energy_envelope=(
                AudioEnergyPoint(0.0, 0.1, -20.0),
                AudioEnergyPoint(0.1, 0.5, -6.0),
            ),
            transient_candidates_seconds=(0.1, 2.25, 5.0, 6.0),
            warnings=("Transient candidates are not verified beats.",),
        )
        result = build_audio_cue_map(
            audio, media_duration_seconds=5.0, fps=30,
            energy_analysis=energy,
        )
        markers = [cue for cue in result.cues if cue.cue_type == "transient_candidate"]
        self.assertEqual(
            [(cue.start_frame, cue.end_frame) for cue in markers],
            [(3, 4), (68, 69)],
        )
        self.assertTrue(all(cue.confidence == "energy_change_candidate" for cue in markers))
        self.assertTrue(any("not a verified beat" in cue.reason for cue in markers))
        self.assertTrue(any("not beat-synchronized edits" in warning for warning in result.warnings))
        self.assertTrue(result.requires_user_review)

    def test_rejects_wrong_energy_analysis_type(self):
        audio = AudioSummary((), peak_db=-1.0, mean_db=-18.0)
        with self.assertRaises(EditPlanError):
            build_audio_cue_map(
                audio, media_duration_seconds=5.0, fps=30,
                energy_analysis={"transient_candidates_seconds": [1.0]},
            )


    def test_maps_estimated_music_pulses_to_review_only_frames(self):
        audio = AudioSummary((), peak_db=-1.0, mean_db=-18.0)
        rhythm = RhythmAnalysis(
            estimated_bpm=120.0, confidence=0.82,
            pulse_period_seconds=0.5,
            pulse_candidates_seconds=(0.0, 0.5, 1.0, 5.0),
            analyzed_duration_seconds=5.0,
            warnings=("RMS pulse estimate only.",),
        )
        result = build_audio_cue_map(
            audio, media_duration_seconds=5.0, fps=30,
            rhythm_analysis=rhythm,
        )
        markers = [cue for cue in result.cues if cue.cue_type == "music_pulse_candidate"]
        self.assertEqual([cue.start_frame for cue in markers], [0, 15, 30])
        self.assertTrue(all("estimated_periodicity_0.82" == cue.confidence for cue in markers))
        self.assertTrue(any("not an automatic music synchronization" in w for w in result.warnings))

    def test_rejects_wrong_rhythm_analysis_type(self):
        audio = AudioSummary((), peak_db=-1.0, mean_db=-18.0)
        with self.assertRaises(EditPlanError):
            build_audio_cue_map(
                audio, media_duration_seconds=5.0, fps=30,
                rhythm_analysis={"estimated_bpm": 120},
            )


    def test_maps_spectral_onsets_and_pulses_to_distinct_review_cues(self):
        audio = AudioSummary((), peak_db=-1.0, mean_db=-18.0)
        spectral = SpectralAudioSummary(
            sample_rate=8000, frame_size=512, hop_size=128,
            estimated_bpm=120.0, tempo_confidence=0.91,
            onset_candidates_seconds=(0.25, 0.75, 5.0),
            pulse_candidates_seconds=(0.0, 0.5, 5.0),
            warnings=("Spectral flux is a candidate detector.",),
        )
        result = build_audio_cue_map(
            audio, media_duration_seconds=5.0, fps=30,
            spectral_audio=spectral,
        )
        onsets = [cue for cue in result.cues if cue.cue_type == "spectral_onset_candidate"]
        pulses = [cue for cue in result.cues if cue.cue_type == "spectral_music_pulse_candidate"]
        self.assertEqual([cue.start_frame for cue in onsets], [8, 23])
        self.assertEqual([cue.start_frame for cue in pulses], [0, 15])
        self.assertTrue(all(cue.duration_frames == 1 for cue in onsets + pulses))
        self.assertTrue(any("review-only" in warning for warning in result.warnings))

    def test_rejects_wrong_spectral_summary_type(self):
        audio = AudioSummary((), peak_db=-1.0, mean_db=-18.0)
        with self.assertRaises(EditPlanError):
            build_audio_cue_map(
                audio, media_duration_seconds=5.0, fps=30,
                spectral_audio={"estimated_bpm": 120},
            )

    def test_rejects_wrong_audio_input_type(self):
        with self.assertRaises(EditPlanError):
            build_audio_cue_map({}, media_duration_seconds=10, fps=30)


if __name__ == "__main__":
    unittest.main()
