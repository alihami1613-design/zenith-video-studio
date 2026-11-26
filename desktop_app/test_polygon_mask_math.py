"""Tests for normalized polygon overlay geometry."""
import unittest

from polygon_mask_math import (
    fitted_video_rect, normalized_point_to_widget, widget_point_to_normalized,
)


class PolygonMaskMathTests(unittest.TestCase):
    def test_letterbox_16_9_inside_square_widget(self):
        rect = fitted_video_rect(600, 600, 1920, 1080)
        self.assertEqual(rect, (0.0, 131.25, 600.0, 337.5))

    def test_point_round_trip(self):
        rect = fitted_video_rect(1000, 700, 1920, 1080)
        point = [0.23, 0.81]
        pixel = normalized_point_to_widget(point, rect)
        restored = widget_point_to_normalized(pixel, rect)
        for actual, expected in zip(restored, point):
            self.assertAlmostEqual(actual, expected, places=8)

    def test_drag_is_clamped_to_video_frame(self):
        rect = (100.0, 50.0, 800.0, 450.0)
        self.assertEqual(widget_point_to_normalized((-20.0, 900.0), rect), [0.0, 1.0])

    def test_invalid_rect_returns_origin(self):
        self.assertEqual(widget_point_to_normalized((5.0, 5.0), (0, 0, 0, 0)), [0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
