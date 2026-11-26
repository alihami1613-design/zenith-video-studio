import unittest
from types import SimpleNamespace

from audio_meter import estimate_track_peaks, peak_to_dbfs


class AudioMeterTests(unittest.TestCase):
    def clip(self, path="voice.wav", **changes):
        values = dict(path=path, track="A1", media_type="audio",
                      source_in=0, duration_frames=150, volume=1.0)
        values.update(changes)
        return SimpleNamespace(**values)

    def test_reads_only_clip_source_window_and_applies_gains(self):
        clip = self.clip(source_in=30, duration_frames=60, volume=0.5)
        peaks = estimate_track_peaks(
            [clip], {"voice.wav": [0.1] * 20 + [0.8, 0.6, 0.1]},
            30, {"A1": {"volume": 0.5}},
        )
        self.assertAlmostEqual(peaks["A1"], 0.2)

    def test_mute_and_solo_are_respected(self):
        clips = [self.clip(), self.clip("music.wav", track="A2")]
        waves = {"voice.wav": [0.8], "music.wav": [0.4]}
        muted = estimate_track_peaks(clips, waves, 30, {
            "A1": {"muted": True}, "A2": {}
        })
        self.assertEqual(muted["A1"], 0)
        solo = estimate_track_peaks(clips, waves, 30, {
            "A1": {"solo": True}, "A2": {}
        })
        self.assertAlmostEqual(solo["A1"], 0.8)
        self.assertEqual(solo["A2"], 0)

    def test_overlap_is_capped_for_meter_display(self):
        peaks = estimate_track_peaks(
            [self.clip(), self.clip()], {"voice.wav": [0.9]}, 30
        )
        self.assertEqual(peaks["A1"], 1.5)

    def test_embedded_video_audio_uses_assigned_mixer_bus(self):
        clip = self.clip(
            path="camera.mp4", track="V1", media_type="video",
            has_audio=True, audio_track="A3",
        )
        peaks = estimate_track_peaks(
            [clip], {"camera.mp4": [0.65]}, 30,
            {"A1": {}, "A2": {}, "A3": {"volume": 0.5}},
        )
        self.assertEqual(peaks["A1"], 0.0)
        self.assertAlmostEqual(peaks["A3"], 0.325)

    def test_dbfs_label(self):
        self.assertEqual(peak_to_dbfs(0), "-∞ dBFS")
        self.assertEqual(peak_to_dbfs(1), "0.0 dBFS")


if __name__ == "__main__":
    unittest.main()
