"""Tests for bounded, frame-accurate speed-ramp segmentation."""
import unittest

from speed_ramp import build_speed_segments


class SpeedRampSegmentationTests(unittest.TestCase):
    def test_constant_speed_integral_is_preserved(self):
        segments = build_speed_segments(60, 30, [{"frame": 0, "rate": 2.0}])
        self.assertAlmostEqual(sum(item["source_duration_frames"] for item in segments), 120.0)
        self.assertTrue(all(item["rate"] == 2.0 for item in segments))

    def test_linear_ramp_integral_is_preserved_and_segments_are_bounded(self):
        segments = build_speed_segments(
            60, 30, [{"frame": 0, "rate": 0.5}, {"frame": 60 - 1, "rate": 2.0}]
        )
        total_source = sum(item["source_duration_frames"] for item in segments)
        self.assertAlmostEqual(total_source, 75.0, delta=1.0)
        self.assertLessEqual(max(item["timeline_frames"] for item in segments), 6)
        self.assertGreater(len(segments), 5)

    def test_first_and_last_rates_extend_to_clip_edges(self):
        segments = build_speed_segments(
            30, 30, [{"frame": 10, "rate": 0.5}, {"frame": 20, "rate": 2.0}]
        )
        self.assertEqual(segments[0]["rate"], 0.5)
        self.assertEqual(segments[-1]["rate"], 2.0)

    def test_rejects_invalid_points(self):
        with self.assertRaises(ValueError):
            build_speed_segments(30, 30, [{"frame": 30, "rate": 1.0}])
        with self.assertRaises(ValueError):
            build_speed_segments(30, 30, [{"frame": 0, "rate": 8.0}])


if __name__ == "__main__":
    unittest.main()
